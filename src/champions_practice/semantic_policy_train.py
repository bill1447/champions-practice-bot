"""Train the first replay-derived semantic action prior.

This model is deliberately weaker than an exact legal-menu behavior clone. Public
replays do not prove the actor's complete request or submitted target, so training
uses complete semantic action identity and sampled semantic alternatives. The model
is an offline prior only; exact Showdown legality and search remain authoritative.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import random
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

import numpy as np

from champions_practice.replay_corpus import (
    DATA_ROOT_ENV,
    DEFAULT_FORMAT,
    _utc_now,
    _validate_public_id,
    initialize_layout,
)
from champions_practice.replay_semantic_audit import (
    SEMANTIC_AUDIT_SCHEMA,
    SEMANTIC_POLICY_SCHEMA,
)
from champions_practice.semantic_policy_features import (
    DEFAULT_ACTION_BUCKETS,
    DEFAULT_STATE_BUCKETS,
    FEATURE_SCHEMA,
    RATING_WEIGHTS,
    action_tokens,
    canonical_action_key,
    hash_tokens,
    normalized_semantic_label,
    rating_weight,
    state_tokens,
)
from champions_practice.semantic_policy_registry import (
    SemanticPolicyRegistryError,
    register_dataset_alias,
    register_training_alias,
    resolve_dataset_reference,
)


MODEL_SCHEMA = "semantic-two-tower-adagrad-v1"
TRAINING_REPORT_SCHEMA = "semantic-policy-training-report-v1"
DEFAULT_EPOCHS = 3
DEFAULT_BATCH_SIZE = 256
DEFAULT_TRAIN_NEGATIVES = 15
DEFAULT_EVAL_NEGATIVES = 63
DEFAULT_EMBEDDING_DIM = 64
DEFAULT_LEARNING_RATE = 0.08
DEFAULT_SHUFFLE_BUFFER = 8192
DEFAULT_SEED = 150
_RECALL_K = (1, 4, 8, 16)


class SemanticPolicyTrainingError(RuntimeError):
    """Training inputs or outputs violate the semantic-policy contract."""


@dataclass(frozen=True)
class TrainingConfig:
    data_root: Path
    format_id: str = DEFAULT_FORMAT
    run_id: str | None = None
    epochs: int = DEFAULT_EPOCHS
    batch_size: int = DEFAULT_BATCH_SIZE
    train_negatives: int = DEFAULT_TRAIN_NEGATIVES
    eval_negatives: int = DEFAULT_EVAL_NEGATIVES
    embedding_dim: int = DEFAULT_EMBEDDING_DIM
    state_buckets: int = DEFAULT_STATE_BUCKETS
    action_buckets: int = DEFAULT_ACTION_BUCKETS
    learning_rate: float = DEFAULT_LEARNING_RATE
    shuffle_buffer: int = DEFAULT_SHUFFLE_BUFFER
    seed: int = DEFAULT_SEED
    max_train_rows: int = 0
    max_eval_rows: int = 0
    dataset_alias: str | None = None
    training_alias: str | None = None
    refresh: bool = False

    def __post_init__(self) -> None:
        _validate_public_id(self.format_id, label="format")
        integer_positive = {
            "epochs": self.epochs,
            "batch_size": self.batch_size,
            "train_negatives": self.train_negatives,
            "eval_negatives": self.eval_negatives,
            "embedding_dim": self.embedding_dim,
            "state_buckets": self.state_buckets,
            "action_buckets": self.action_buckets,
            "shuffle_buffer": self.shuffle_buffer,
        }
        for name, value in integer_positive.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name, value in {
            "max_train_rows": self.max_train_rows,
            "max_eval_rows": self.max_eval_rows,
        }.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.eval_negatives < 15:
            raise ValueError("eval_negatives must be at least 15 for recall@16")
        if not math.isfinite(self.learning_rate) or self.learning_rate <= 0:
            raise ValueError("learning_rate must be positive and finite")
        if self.state_buckets < 128 or self.action_buckets < 128:
            raise ValueError("feature bucket counts must be at least 128")
        for label, value in (
            ("dataset alias", self.dataset_alias),
            ("training alias", self.training_alias),
        ):
            if value is not None:
                _validate_public_id(value, label=label)


@dataclass(frozen=True)
class ActionEntry:
    key: str
    label: dict[str, Any]
    family: str
    count: int
    feature_ids: tuple[int, ...]


class ActionVocabulary:
    def __init__(self, entries: list[ActionEntry]) -> None:
        if not entries:
            raise SemanticPolicyTrainingError("training action vocabulary is empty")
        self.entries = entries
        self.by_key = {entry.key: entry for entry in entries}
        self.global_keys = tuple(entry.key for entry in entries)
        grouped: dict[str, list[str]] = defaultdict(list)
        for entry in entries:
            grouped[entry.family].append(entry.key)
        self.by_family = {
            family: tuple(sorted(keys))
            for family, keys in grouped.items()
        }

    def contains(self, key: str) -> bool:
        return key in self.by_key

    def feature_ids_for_label(
        self,
        label: dict[str, Any],
        *,
        action_buckets: int,
    ) -> tuple[int, ...]:
        key = canonical_action_key(label)
        entry = self.by_key.get(key)
        if entry is not None:
            return entry.feature_ids
        return hash_tokens(action_tokens(label), action_buckets)

    def sample_negatives(
        self,
        *,
        positive_key: str,
        family: str,
        count: int,
        rng: random.Random,
    ) -> list[ActionEntry]:
        if count < 1:
            return []
        primary = self.by_family.get(family, ())
        candidates = primary if len(primary) > 1 else self.global_keys
        selected: list[ActionEntry] = []
        seen = {positive_key}
        attempts = 0
        max_attempts = max(128, count * 32)
        while len(selected) < count and attempts < max_attempts:
            attempts += 1
            source = candidates if candidates else self.global_keys
            key = source[rng.randrange(len(source))]
            if key in seen:
                if len(seen) >= len(source):
                    candidates = self.global_keys
                continue
            seen.add(key)
            selected.append(self.by_key[key])
        if len(selected) < count:
            for key in self.global_keys:
                if key in seen:
                    continue
                selected.append(self.by_key[key])
                seen.add(key)
                if len(selected) >= count:
                    break
        if len(selected) < count:
            raise SemanticPolicyTrainingError(
                "action vocabulary is too small for requested negative count"
            )
        return selected


def _safe_child(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise SemanticPolicyTrainingError(
            f"dataset path escapes external corpus root: {relative!r}"
        ) from error
    return path


def _load_dataset_summary(
    *,
    data_root: Path,
    format_id: str,
    run_id: str | None,
) -> tuple[dict[str, Any], Path]:
    layout = initialize_layout(data_root)
    base = layout.processed / "replay-policy" / format_id
    if run_id is None:
        latest = base / "latest-summary.json"
        if not latest.is_file():
            raise SemanticPolicyTrainingError(
                "no replay-policy audit exists; run audit-replay-policy.ps1 first"
            )
        latest_summary = json.loads(latest.read_text(encoding="utf-8"))
        run_id = latest_summary.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise SemanticPolicyTrainingError("dataset run id is missing")
    run_id = resolve_dataset_reference(
        data_root,
        run_id,
        format_id=format_id,
    )
    summary_path = base / "runs" / run_id / "summary.json"
    if not summary_path.is_file():
        raise SemanticPolicyTrainingError(f"dataset run {run_id!r} does not exist")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("schema") != SEMANTIC_AUDIT_SCHEMA:
        raise SemanticPolicyTrainingError("unsupported semantic audit schema")
    if summary.get("policy_schema") != SEMANTIC_POLICY_SCHEMA:
        raise SemanticPolicyTrainingError("unsupported semantic policy row schema")
    if summary.get("run_id") != run_id:
        raise SemanticPolicyTrainingError("dataset run id does not match summary")
    if summary.get("format_id") != format_id:
        raise SemanticPolicyTrainingError("dataset format does not match requested format")
    return summary, summary_path.parent


def _split_files(
    summary: dict[str, Any],
    run_dir: Path,
    split: str,
) -> list[Path]:
    dataset = summary.get("dataset")
    if not isinstance(dataset, dict):
        raise SemanticPolicyTrainingError("dataset summary has no dataset block")
    files = dataset.get("files")
    if not isinstance(files, list):
        raise SemanticPolicyTrainingError("dataset summary has no shard list")
    selected: list[Path] = []
    for entry in files:
        if not isinstance(entry, dict):
            raise SemanticPolicyTrainingError("dataset shard entry is malformed")
        relative = entry.get("path")
        if not isinstance(relative, str):
            raise SemanticPolicyTrainingError("dataset shard has no path")
        if not relative.startswith(f"{split}/"):
            continue
        path = _safe_child(run_dir, relative)
        if not path.is_file():
            raise SemanticPolicyTrainingError(f"dataset shard is missing: {path}")
        selected.append(path)
    if not selected:
        raise SemanticPolicyTrainingError(f"dataset has no {split} shards")
    return selected


def _shard_manifest(paths: Iterable[Path], *, run_dir: Path) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for path in paths:
        raw = path.read_bytes()
        manifest.append(
            {
                "path": path.relative_to(run_dir).as_posix(),
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return manifest


def _iter_rows(paths: Iterable[Path], *, limit: int = 0) -> Iterator[dict[str, Any]]:
    emitted = 0
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as error:
                    raise SemanticPolicyTrainingError(
                        f"invalid JSON in {path}:{line_number}"
                    ) from error
                if not isinstance(row, dict) or row.get("schema") != SEMANTIC_POLICY_SCHEMA:
                    raise SemanticPolicyTrainingError(
                        f"unsupported policy row in {path}:{line_number}"
                    )
                yield row
                emitted += 1
                if limit and emitted >= limit:
                    return


def _buffered_rows(
    paths: Iterable[Path],
    *,
    limit: int,
    buffer_size: int,
    seed: int,
) -> Iterator[dict[str, Any]]:
    rng = random.Random(seed)
    buffer: list[dict[str, Any]] = []
    for row in _iter_rows(paths, limit=limit):
        if len(buffer) < buffer_size:
            buffer.append(row)
            continue
        index = rng.randrange(len(buffer))
        yield buffer[index]
        buffer[index] = row
    rng.shuffle(buffer)
    yield from buffer


def _build_action_vocabulary(
    paths: Iterable[Path],
    *,
    action_buckets: int,
    limit: int,
) -> ActionVocabulary:
    counts: Counter[str] = Counter()
    labels: dict[str, dict[str, Any]] = {}
    families: dict[str, str] = {}
    for row in _iter_rows(paths, limit=limit):
        label = row.get("semantic_label")
        if not isinstance(label, dict):
            raise SemanticPolicyTrainingError("policy row has no semantic label")
        normalized = normalized_semantic_label(label)
        key = canonical_action_key(normalized)
        counts[key] += 1
        labels.setdefault(key, normalized)
        families.setdefault(key, normalized["action_family"])

    entries = [
        ActionEntry(
            key=key,
            label=labels[key],
            family=families[key],
            count=count,
            feature_ids=hash_tokens(action_tokens(labels[key]), action_buckets),
        )
        for key, count in sorted(counts.items())
    ]
    return ActionVocabulary(entries)


def _vocabulary_payload(vocabulary: ActionVocabulary) -> bytes:
    payload = {
        "schema": "semantic-action-vocabulary-v1",
        "entries": [
            {
                "key": entry.key,
                "label": entry.label,
                "family": entry.family,
                "count": entry.count,
                "feature_ids": list(entry.feature_ids),
            }
            for entry in vocabulary.entries
        ],
    }
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _row_features(
    row: dict[str, Any],
    *,
    vocabulary: ActionVocabulary,
    state_buckets: int,
    action_buckets: int,
) -> tuple[tuple[int, ...], str, dict[str, Any], float]:
    public_state = row.get("public_state")
    side = row.get("side")
    label = row.get("semantic_label")
    band = row.get("rating_band")
    if not isinstance(public_state, dict):
        raise SemanticPolicyTrainingError("policy row has no public state")
    if side not in {"p1", "p2"}:
        raise SemanticPolicyTrainingError("policy row has invalid side")
    if not isinstance(label, dict):
        raise SemanticPolicyTrainingError("policy row has no semantic label")
    if not isinstance(band, str):
        raise SemanticPolicyTrainingError("policy row has no rating band")
    state_ids = hash_tokens(
        state_tokens(public_state, side=side),
        state_buckets,
    )
    normalized = normalized_semantic_label(label)
    key = canonical_action_key(normalized)
    return state_ids, key, normalized, rating_weight(band)


def _pad_sequences(
    sequences: list[tuple[int, ...]],
) -> tuple[np.ndarray, np.ndarray]:
    width = max((len(sequence) for sequence in sequences), default=1)
    ids = np.zeros((len(sequences), width), dtype=np.int32)
    mask = np.zeros((len(sequences), width), dtype=np.float32)
    for row_index, sequence in enumerate(sequences):
        if not sequence:
            continue
        ids[row_index, : len(sequence)] = sequence
        mask[row_index, : len(sequence)] = 1.0
    return ids, mask


def _pad_candidate_sequences(
    candidates: list[list[tuple[int, ...]]],
) -> tuple[np.ndarray, np.ndarray]:
    batch = len(candidates)
    count = len(candidates[0]) if candidates else 0
    width = max(
        (len(sequence) for row in candidates for sequence in row),
        default=1,
    )
    ids = np.zeros((batch, count, width), dtype=np.int32)
    mask = np.zeros((batch, count, width), dtype=np.float32)
    for batch_index, row in enumerate(candidates):
        if len(row) != count:
            raise SemanticPolicyTrainingError("candidate counts differ within batch")
        for candidate_index, sequence in enumerate(row):
            if not sequence:
                continue
            ids[batch_index, candidate_index, : len(sequence)] = sequence
            mask[batch_index, candidate_index, : len(sequence)] = 1.0
    return ids, mask


def _embed_state(
    table: np.ndarray,
    ids: np.ndarray,
    mask: np.ndarray,
) -> np.ndarray:
    count = np.maximum(mask.sum(axis=1, keepdims=True), 1.0)
    return (table[ids] * mask[..., None]).sum(axis=1) / count


def _embed_actions(
    table: np.ndarray,
    ids: np.ndarray,
    mask: np.ndarray,
) -> np.ndarray:
    count = np.maximum(mask.sum(axis=2, keepdims=True), 1.0)
    return (table[ids] * mask[..., None]).sum(axis=2) / count


def _scores(
    state_table: np.ndarray,
    action_table: np.ndarray,
    state_ids: np.ndarray,
    state_mask: np.ndarray,
    action_ids: np.ndarray,
    action_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    state_vectors = _embed_state(state_table, state_ids, state_mask)
    action_vectors = _embed_actions(action_table, action_ids, action_mask)
    scale = math.sqrt(state_table.shape[1])
    scores = np.einsum("bd,bcd->bc", state_vectors, action_vectors) / scale
    return scores, state_vectors, action_vectors


def _softmax(values: np.ndarray) -> np.ndarray:
    shifted = values - values.max(axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=1, keepdims=True)


def _sparse_adagrad_update(
    table: np.ndarray,
    accumulator: np.ndarray,
    ids: np.ndarray,
    token_gradients: np.ndarray,
    *,
    learning_rate: float,
) -> None:
    flat_ids = ids.reshape(-1)
    flat_gradients = token_gradients.reshape(-1, table.shape[1])
    valid = flat_ids != 0
    if not np.any(valid):
        return
    flat_ids = flat_ids[valid]
    flat_gradients = flat_gradients[valid]
    touched = np.unique(flat_ids)
    positions = np.searchsorted(touched, flat_ids)
    aggregated = np.zeros((len(touched), table.shape[1]), dtype=np.float32)
    np.add.at(aggregated, positions, flat_gradients.astype(np.float32, copy=False))
    norms = np.linalg.norm(aggregated, axis=1, keepdims=True)
    scale = np.maximum(norms / 5.0, 1.0)
    aggregated /= scale
    accumulator[touched] += np.mean(aggregated * aggregated, axis=1)
    denominator = np.sqrt(accumulator[touched])[:, None] + 1e-6
    table[touched] -= learning_rate * aggregated / denominator


class SemanticTwoTower:
    def __init__(
        self,
        *,
        state_buckets: int,
        action_buckets: int,
        embedding_dim: int,
        seed: int,
    ) -> None:
        rng = np.random.default_rng(seed)
        self.state_table = rng.normal(
            0.0,
            0.02,
            size=(state_buckets, embedding_dim),
        ).astype(np.float32)
        self.action_table = rng.normal(
            0.0,
            0.02,
            size=(action_buckets, embedding_dim),
        ).astype(np.float32)
        self.state_table[0] = 0
        self.action_table[0] = 0
        self.state_accumulator = np.zeros(state_buckets, dtype=np.float32)
        self.action_accumulator = np.zeros(action_buckets, dtype=np.float32)

    def train_batch(
        self,
        *,
        state_ids: np.ndarray,
        state_mask: np.ndarray,
        action_ids: np.ndarray,
        action_mask: np.ndarray,
        weights: np.ndarray,
        learning_rate: float,
    ) -> tuple[float, float]:
        scores, state_vectors, action_vectors = _scores(
            self.state_table,
            self.action_table,
            state_ids,
            state_mask,
            action_ids,
            action_mask,
        )
        probabilities = _softmax(scores)
        losses = -np.log(np.maximum(probabilities[:, 0], 1e-12))
        weight_sum = float(weights.sum())
        if weight_sum <= 0:
            raise SemanticPolicyTrainingError("batch has no positive training weight")
        loss_numerator = float(np.sum(losses * weights))

        score_gradient = probabilities
        score_gradient[:, 0] -= 1.0
        score_gradient *= (weights / weight_sum)[:, None]
        normalization = math.sqrt(self.state_table.shape[1])

        state_vector_gradient = (
            np.einsum("bc,bcd->bd", score_gradient, action_vectors)
            / normalization
        )
        action_vector_gradient = (
            score_gradient[:, :, None] * state_vectors[:, None, :]
            / normalization
        )

        state_counts = np.maximum(state_mask.sum(axis=1), 1.0)
        state_token_gradient = (
            state_vector_gradient[:, None, :]
            * state_mask[..., None]
            / state_counts[:, None, None]
        )
        action_counts = np.maximum(action_mask.sum(axis=2), 1.0)
        action_token_gradient = (
            action_vector_gradient[:, :, None, :]
            * action_mask[..., None]
            / action_counts[:, :, None, None]
        )

        _sparse_adagrad_update(
            self.state_table,
            self.state_accumulator,
            state_ids,
            state_token_gradient,
            learning_rate=learning_rate,
        )
        _sparse_adagrad_update(
            self.action_table,
            self.action_accumulator,
            action_ids,
            action_token_gradient,
            learning_rate=learning_rate,
        )
        self.state_table[0] = 0
        self.action_table[0] = 0
        return loss_numerator, weight_sum

    def score_batch(
        self,
        *,
        state_ids: np.ndarray,
        state_mask: np.ndarray,
        action_ids: np.ndarray,
        action_mask: np.ndarray,
    ) -> np.ndarray:
        scores, _, _ = _scores(
            self.state_table,
            self.action_table,
            state_ids,
            state_mask,
            action_ids,
            action_mask,
        )
        return scores


def _build_batch(
    rows: list[dict[str, Any]],
    *,
    vocabulary: ActionVocabulary,
    state_buckets: int,
    action_buckets: int,
    negatives: int,
    rng: random.Random,
) -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    list[dict[str, Any]],
]:
    states: list[tuple[int, ...]] = []
    action_candidates: list[list[tuple[int, ...]]] = []
    weights: list[float] = []
    groups: list[dict[str, str]] = []

    for row in rows:
        state_ids, positive_key, normalized, weight = _row_features(
            row,
            vocabulary=vocabulary,
            state_buckets=state_buckets,
            action_buckets=action_buckets,
        )
        family = normalized["action_family"]
        positive_ids = vocabulary.feature_ids_for_label(
            normalized,
            action_buckets=action_buckets,
        )
        negatives_selected = vocabulary.sample_negatives(
            positive_key=positive_key,
            family=family,
            count=negatives,
            rng=rng,
        )
        states.append(state_ids)
        action_candidates.append(
            [positive_ids] + [entry.feature_ids for entry in negatives_selected]
        )
        weights.append(weight)
        groups.append(
            {
                "rating_band": str(row.get("rating_band")),
                "action_family": family,
                "turn_band": str(row.get("turn_band")),
                "positive_key": positive_key,
                "candidate_keys": [
                    positive_key,
                    *[entry.key for entry in negatives_selected],
                ],
            }
        )

    state_id_array, state_mask = _pad_sequences(states)
    action_id_array, action_mask = _pad_candidate_sequences(action_candidates)
    return (
        state_id_array,
        state_mask,
        action_id_array,
        action_mask,
        np.asarray(weights, dtype=np.float32),
        groups,
    )


def _batched(
    rows: Iterable[dict[str, Any]],
    *,
    batch_size: int,
) -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def _empty_metric() -> dict[str, Any]:
    return {
        "rows": 0,
        "unseen_positive_actions": 0,
        **{f"hits_at_{k}": 0 for k in _RECALL_K},
    }


def _finalize_metric(metric: dict[str, Any]) -> dict[str, Any]:
    rows = int(metric["rows"])
    result = {
        "rows": rows,
        "unseen_positive_actions": int(metric["unseen_positive_actions"]),
    }
    for k in _RECALL_K:
        hits = int(metric[f"hits_at_{k}"])
        result[f"sampled_recall_at_{k}"] = round(hits / rows, 6) if rows else 0.0
    return result


def _metric_groups() -> dict[str, Any]:
    return {
        "overall": {"all": _empty_metric()},
        "rating_band": defaultdict(_empty_metric),
        "action_family": defaultdict(_empty_metric),
        "turn_band": defaultdict(_empty_metric),
        "training_vocabulary_status": defaultdict(_empty_metric),
    }


def _metric_destinations(
    metrics: dict[str, Any],
    group: dict[str, Any],
    *,
    unseen: bool,
) -> list[dict[str, Any]]:
    return [
        metrics["overall"]["all"],
        metrics["rating_band"][group["rating_band"]],
        metrics["action_family"][group["action_family"]],
        metrics["turn_band"][group["turn_band"]],
        metrics["training_vocabulary_status"]["unseen" if unseen else "seen"],
    ]


def _record_rank(metric: dict[str, Any], *, rank: int, unseen: bool) -> None:
    metric["rows"] += 1
    metric["unseen_positive_actions"] += int(unseen)
    for k in _RECALL_K:
        metric[f"hits_at_{k}"] += int(rank <= k)


def _finalize_metric_groups(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "overall": _finalize_metric(metrics["overall"]["all"]),
        "rating_band": {
            key: _finalize_metric(value)
            for key, value in sorted(metrics["rating_band"].items())
        },
        "action_family": {
            key: _finalize_metric(value)
            for key, value in sorted(metrics["action_family"].items())
        },
        "turn_band": {
            key: _finalize_metric(value)
            for key, value in sorted(metrics["turn_band"].items())
        },
        "training_vocabulary_status": {
            key: _finalize_metric(value)
            for key, value in sorted(
                metrics["training_vocabulary_status"].items()
            )
        },
    }


def _evaluate(
    model: SemanticTwoTower,
    *,
    paths: list[Path],
    vocabulary: ActionVocabulary,
    config: TrainingConfig,
    split: str,
) -> dict[str, Any]:
    rng = random.Random(config.seed + (17 if split == "validation" else 29))
    model_metrics = _metric_groups()
    baseline_metrics = _metric_groups()

    rows = _iter_rows(paths, limit=config.max_eval_rows)
    for batch in _batched(rows, batch_size=config.batch_size):
        (
            state_ids,
            state_mask,
            action_ids,
            action_mask,
            _,
            groups,
        ) = _build_batch(
            batch,
            vocabulary=vocabulary,
            state_buckets=config.state_buckets,
            action_buckets=config.action_buckets,
            negatives=config.eval_negatives,
            rng=rng,
        )
        scores = model.score_batch(
            state_ids=state_ids,
            state_mask=state_mask,
            action_ids=action_ids,
            action_mask=action_mask,
        )
        positive = scores[:, 0]
        ranks = 1 + np.sum(scores[:, 1:] >= positive[:, None], axis=1)

        for index, group in enumerate(groups):
            unseen = not vocabulary.contains(group["positive_key"])
            candidate_keys = group["candidate_keys"]
            frequency_scores = [
                vocabulary.by_key[key].count if vocabulary.contains(key) else 0
                for key in candidate_keys
            ]
            baseline_rank = 1 + sum(
                score >= frequency_scores[0]
                for score in frequency_scores[1:]
            )

            for metric in _metric_destinations(
                model_metrics,
                group,
                unseen=unseen,
            ):
                _record_rank(metric, rank=int(ranks[index]), unseen=unseen)
            for metric in _metric_destinations(
                baseline_metrics,
                group,
                unseen=unseen,
            ):
                _record_rank(metric, rank=int(baseline_rank), unseen=unseen)

    model_results = _finalize_metric_groups(model_metrics)
    baseline_results = _finalize_metric_groups(baseline_metrics)
    return {
        "candidate_count": config.eval_negatives + 1,
        "candidate_source": (
            "same-action-family semantic labels sampled from the training vocabulary; "
            "fallback to global vocabulary when the family is too small"
        ),
        "tie_policy": "pessimistic; equal-scoring negatives rank ahead of the positive",
        "warning": (
            "Sampled recall is a representation/training metric, not exact legal-menu "
            "recall and not a gameplay-strength metric."
        ),
        **model_results,
        "state_blind_baseline": {
            "name": "most-frequent-semantic-joint-action-within-action-family",
            "uses_public_state": False,
            "score": "training-row frequency of each semantic joint action",
            "candidate_pool": "identical sampled candidates used for learned-model recall",
            "tie_policy": (
                "pessimistic; equal-frequency negatives rank ahead of the positive"
            ),
            **baseline_results,
        },
    }


def _training_identity(
    *,
    dataset_summary: dict[str, Any],
    config: TrainingConfig,
) -> str:
    identity = {
        "schema": TRAINING_REPORT_SCHEMA,
        "model_schema": MODEL_SCHEMA,
        "feature_schema": FEATURE_SCHEMA,
        "dataset_run_id": dataset_summary["run_id"],
        "source_fingerprint": dataset_summary["source_fingerprint"],
        "epochs": config.epochs,
        "batch_size": config.batch_size,
        "train_negatives": config.train_negatives,
        "eval_negatives": config.eval_negatives,
        "embedding_dim": config.embedding_dim,
        "state_buckets": config.state_buckets,
        "action_buckets": config.action_buckets,
        "learning_rate": config.learning_rate,
        "shuffle_buffer": config.shuffle_buffer,
        "seed": config.seed,
        "max_train_rows": config.max_train_rows,
        "max_eval_rows": config.max_eval_rows,
        "rating_weights": RATING_WEIGHTS,
    }
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


def train_semantic_policy(config: TrainingConfig) -> dict[str, Any]:
    layout = initialize_layout(config.data_root)
    summary, run_dir = _load_dataset_summary(
        data_root=config.data_root,
        format_id=config.format_id,
        run_id=config.run_id,
    )
    if config.dataset_alias is not None:
        register_dataset_alias(
            config.data_root,
            alias=config.dataset_alias,
            run_id=summary["run_id"],
            format_id=config.format_id,
        )
    train_files = _split_files(summary, run_dir, "train")
    validation_files = _split_files(summary, run_dir, "validation")
    test_files = _split_files(summary, run_dir, "test")

    training_id = _training_identity(dataset_summary=summary, config=config)
    output_base = layout.models / "semantic-policy" / summary["run_id"]
    output_dir = output_base / training_id
    report_path = output_dir / "report.json"
    latest_path = output_base / "latest-report.json"
    if report_path.is_file() and not config.refresh:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        latest_path.parent.mkdir(parents=True, exist_ok=True)
        latest_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if config.training_alias is not None:
            register_training_alias(
                config.data_root,
                alias=config.training_alias,
                training_id=training_id,
                dataset_reference=summary["run_id"],
                format_id=config.format_id,
            )
        return report

    started = time.monotonic()
    shard_manifest = {
        split: _shard_manifest(paths, run_dir=run_dir)
        for split, paths in (
            ("train", train_files),
            ("validation", validation_files),
            ("test", test_files),
        )
    }
    vocabulary = _build_action_vocabulary(
        train_files,
        action_buckets=config.action_buckets,
        limit=config.max_train_rows,
    )
    vocabulary_bytes = _vocabulary_payload(vocabulary)
    vocabulary_sha = hashlib.sha256(vocabulary_bytes).hexdigest()

    model = SemanticTwoTower(
        state_buckets=config.state_buckets,
        action_buckets=config.action_buckets,
        embedding_dim=config.embedding_dim,
        seed=config.seed,
    )

    epoch_reports: list[dict[str, Any]] = []
    for epoch in range(config.epochs):
        rng = random.Random(config.seed + 1000 + epoch)
        loss_numerator = 0.0
        weight_sum = 0.0
        row_count = 0
        rows = _buffered_rows(
            train_files,
            limit=config.max_train_rows,
            buffer_size=config.shuffle_buffer,
            seed=config.seed + epoch,
        )
        for batch in _batched(rows, batch_size=config.batch_size):
            (
                state_ids,
                state_mask,
                action_ids,
                action_mask,
                weights,
                _,
            ) = _build_batch(
                batch,
                vocabulary=vocabulary,
                state_buckets=config.state_buckets,
                action_buckets=config.action_buckets,
                negatives=config.train_negatives,
                rng=rng,
            )
            batch_loss, batch_weight = model.train_batch(
                state_ids=state_ids,
                state_mask=state_mask,
                action_ids=action_ids,
                action_mask=action_mask,
                weights=weights,
                learning_rate=config.learning_rate,
            )
            loss_numerator += batch_loss
            weight_sum += batch_weight
            row_count += len(batch)

        validation = _evaluate(
            model,
            paths=validation_files,
            vocabulary=vocabulary,
            config=config,
            split="validation",
        )
        epoch_reports.append(
            {
                "epoch": epoch + 1,
                "training_rows": row_count,
                "rating_weighted_loss": round(
                    loss_numerator / weight_sum if weight_sum else 0.0,
                    6,
                ),
                "validation_sampled_recall": validation["overall"],
            }
        )

    validation_report = _evaluate(
        model,
        paths=validation_files,
        vocabulary=vocabulary,
        config=config,
        split="validation",
    )
    test_report = _evaluate(
        model,
        paths=test_files,
        vocabulary=vocabulary,
        config=config,
        split="test",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "model.npz"
    np.savez_compressed(
        model_path,
        state_table=model.state_table,
        action_table=model.action_table,
    )
    vocabulary_path = output_dir / "action-vocabulary.json.gz"
    vocabulary_path.write_bytes(gzip.compress(vocabulary_bytes, mtime=0))

    report = {
        "schema": TRAINING_REPORT_SCHEMA,
        "model_schema": MODEL_SCHEMA,
        "feature_schema": FEATURE_SCHEMA,
        "training_id": training_id,
        "generated_at": _utc_now(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "format_id": config.format_id,
        "dataset": {
            "run_id": summary["run_id"],
            "source_fingerprint": summary["source_fingerprint"],
            "showdown_revision": summary["showdown_revision"],
            "semantic_trainable_rows": summary["semantic_trainable_rows"],
            "split_rows": summary["split_rows"],
            "shards": shard_manifest,
        },
        "configuration": {
            "epochs": config.epochs,
            "batch_size": config.batch_size,
            "train_negatives": config.train_negatives,
            "eval_negatives": config.eval_negatives,
            "embedding_dim": config.embedding_dim,
            "state_buckets": config.state_buckets,
            "action_buckets": config.action_buckets,
            "learning_rate": config.learning_rate,
            "shuffle_buffer": config.shuffle_buffer,
            "seed": config.seed,
            "max_train_rows": config.max_train_rows,
            "max_eval_rows": config.max_eval_rows,
            "rating_weights": RATING_WEIGHTS,
        },
        "action_vocabulary": {
            "entries": len(vocabulary.entries),
            "content_sha256": vocabulary_sha,
            "path": vocabulary_path.name,
        },
        "epochs": epoch_reports,
        "validation": validation_report,
        "test": test_report,
        "artifacts": {
            "model": {
                "path": model_path.name,
                "bytes": model_path.stat().st_size,
                "sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
            },
            "vocabulary": {
                "path": vocabulary_path.name,
                "bytes": vocabulary_path.stat().st_size,
                "sha256": hashlib.sha256(vocabulary_path.read_bytes()).hexdigest(),
            },
        },
        "authority": {
            "training_input": (
                "complete public semantic action identity from replay-policy shards"
            ),
            "negative_candidates": (
                "sampled semantic alternatives; not claimed to be exact legal choices"
            ),
            "selected_target": "not trained in v1",
            "live_decision_authority": False,
            "search_role": (
                "offline prior candidate only; exact Showdown legality/mechanics and "
                "protected exact-search baseline remain authoritative"
            ),
        },
    }
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if config.training_alias is not None:
        register_training_alias(
            config.data_root,
            alias=config.training_alias,
            training_id=training_id,
            dataset_reference=summary["run_id"],
            format_id=config.format_id,
        )
    return report


def training_status(
    data_root: str | Path,
    *,
    format_id: str = DEFAULT_FORMAT,
    run_id: str | None = None,
) -> dict[str, Any]:
    layout = initialize_layout(data_root)
    if run_id is None:
        summary, _ = _load_dataset_summary(
            data_root=Path(data_root),
            format_id=format_id,
            run_id=None,
        )
        run_id = summary["run_id"]
    path = layout.models / "semantic-policy" / run_id / "latest-report.json"
    if not path.is_file():
        return {
            "schema": TRAINING_REPORT_SCHEMA,
            "available": False,
            "format_id": format_id,
            "dataset_run_id": run_id,
        }
    return {
        **json.loads(path.read_text(encoding="utf-8")),
        "available": True,
    }


def _resolve_data_root(value: str | None) -> Path:
    selected = value or os.environ.get(DATA_ROOT_ENV)
    if not selected:
        raise SemanticPolicyTrainingError(f"Pass --data-root or set {DATA_ROOT_ENV}.")
    return Path(selected)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train the replay-derived semantic action prior."
    )
    parser.add_argument("--data-root")
    parser.add_argument("--format", default=DEFAULT_FORMAT, dest="format_id")
    parser.add_argument("--run-id")
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--train-negatives",
        type=int,
        default=DEFAULT_TRAIN_NEGATIVES,
    )
    parser.add_argument(
        "--eval-negatives",
        type=int,
        default=DEFAULT_EVAL_NEGATIVES,
    )
    parser.add_argument(
        "--embedding-dim",
        type=int,
        default=DEFAULT_EMBEDDING_DIM,
    )
    parser.add_argument(
        "--state-buckets",
        type=int,
        default=DEFAULT_STATE_BUCKETS,
    )
    parser.add_argument(
        "--action-buckets",
        type=int,
        default=DEFAULT_ACTION_BUCKETS,
    )
    parser.add_argument(
        "--learning-rate",
        type=float,
        default=DEFAULT_LEARNING_RATE,
    )
    parser.add_argument(
        "--shuffle-buffer",
        type=int,
        default=DEFAULT_SHUFFLE_BUFFER,
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--max-train-rows", type=int, default=0)
    parser.add_argument("--max-eval-rows", type=int, default=0)
    parser.add_argument("--dataset-alias")
    parser.add_argument("--training-alias")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--status", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    try:
        data_root = _resolve_data_root(args.data_root)
        if args.status:
            print(
                json.dumps(
                    training_status(
                        data_root,
                        format_id=args.format_id,
                        run_id=args.run_id,
                    ),
                    indent=2,
                    sort_keys=True,
                )
            )
            return
        report = train_semantic_policy(
            TrainingConfig(
                data_root=data_root,
                format_id=args.format_id,
                run_id=args.run_id,
                epochs=args.epochs,
                batch_size=args.batch_size,
                train_negatives=args.train_negatives,
                eval_negatives=args.eval_negatives,
                embedding_dim=args.embedding_dim,
                state_buckets=args.state_buckets,
                action_buckets=args.action_buckets,
                learning_rate=args.learning_rate,
                shuffle_buffer=args.shuffle_buffer,
                seed=args.seed,
                max_train_rows=args.max_train_rows,
                max_eval_rows=args.max_eval_rows,
                dataset_alias=args.dataset_alias,
                training_alias=args.training_alias,
                refresh=args.refresh,
            )
        )
        print(json.dumps(report, indent=2, sort_keys=True))
    except (
        SemanticPolicyTrainingError,
        SemanticPolicyRegistryError,
        ValueError,
        OSError,
        json.JSONDecodeError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
