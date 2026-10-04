"""Post-hoc diagnostics and comparison tooling for saved semantic-policy models."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from champions_practice.replay_corpus import DEFAULT_FORMAT, _utc_now
from champions_practice.semantic_policy_registry import (
    preferred_dataset_alias,
    preferred_training_alias,
    resolve_training_reference,
)
from champions_practice.semantic_policy_train import (
    MODEL_SCHEMA,
    ActionEntry,
    ActionVocabulary,
    SemanticPolicyTrainingError,
    SemanticTwoTower,
    TrainingConfig,
    _evaluate,
    _load_dataset_summary,
    _split_files,
)

DIAGNOSTICS_SCHEMA = "semantic-policy-diagnostics-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise SemanticPolicyTrainingError(
            f"artifact path escapes training directory: {relative!r}"
        ) from error
    if not path.is_file():
        raise SemanticPolicyTrainingError(f"saved policy artifact is missing: {path}")
    return path


def _load_vocabulary(path: Path) -> ActionVocabulary:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or payload.get("schema") != "semantic-action-vocabulary-v1":
        raise SemanticPolicyTrainingError("unsupported saved action vocabulary")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise SemanticPolicyTrainingError("saved action vocabulary has no entries")
    entries: list[ActionEntry] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise SemanticPolicyTrainingError("saved action vocabulary entry is malformed")
        key = raw.get("key")
        label = raw.get("label")
        family = raw.get("family")
        count = raw.get("count")
        feature_ids = raw.get("feature_ids")
        if (
            not isinstance(key, str)
            or not isinstance(label, dict)
            or not isinstance(family, str)
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 1
            or not isinstance(feature_ids, list)
            or not all(isinstance(value, int) for value in feature_ids)
        ):
            raise SemanticPolicyTrainingError("saved action vocabulary entry is invalid")
        entries.append(
            ActionEntry(
                key=key,
                label=label,
                family=family,
                count=count,
                feature_ids=tuple(feature_ids),
            )
        )
    return ActionVocabulary(entries)


def _config_from_report(data_root: Path, report: dict[str, Any]) -> TrainingConfig:
    configuration = report.get("configuration")
    dataset = report.get("dataset")
    if not isinstance(configuration, dict) or not isinstance(dataset, dict):
        raise SemanticPolicyTrainingError("training report is missing configuration metadata")
    required = (
        "epochs",
        "batch_size",
        "train_negatives",
        "eval_negatives",
        "embedding_dim",
        "state_buckets",
        "action_buckets",
        "learning_rate",
        "shuffle_buffer",
        "seed",
        "max_train_rows",
        "max_eval_rows",
    )
    missing = [key for key in required if key not in configuration]
    if missing:
        raise SemanticPolicyTrainingError(
            f"training report is missing configuration fields: {', '.join(missing)}"
        )
    return TrainingConfig(
        data_root=data_root,
        format_id=str(report.get("format_id", DEFAULT_FORMAT)),
        run_id=str(dataset.get("run_id")),
        epochs=int(configuration["epochs"]),
        batch_size=int(configuration["batch_size"]),
        train_negatives=int(configuration["train_negatives"]),
        eval_negatives=int(configuration["eval_negatives"]),
        embedding_dim=int(configuration["embedding_dim"]),
        state_buckets=int(configuration["state_buckets"]),
        action_buckets=int(configuration["action_buckets"]),
        learning_rate=float(configuration["learning_rate"]),
        shuffle_buffer=int(configuration["shuffle_buffer"]),
        seed=int(configuration["seed"]),
        max_train_rows=int(configuration["max_train_rows"]),
        max_eval_rows=int(configuration["max_eval_rows"]),
    )


def evaluate_saved_training(
    data_root: str | Path,
    training_reference: str,
    *,
    dataset_reference: str | None = None,
    format_id: str = DEFAULT_FORMAT,
) -> dict[str, Any]:
    """Evaluate a saved model without rerunning any training epochs."""
    data_root = Path(data_root)
    resolved = resolve_training_reference(
        data_root,
        training_reference,
        dataset_reference=dataset_reference,
        format_id=format_id,
    )
    report_path = Path(resolved["report_path"])
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    if report.get("model_schema") != MODEL_SCHEMA:
        raise SemanticPolicyTrainingError(
            f"unsupported saved model schema {report.get('model_schema')!r}"
        )
    dataset = report.get("dataset")
    if not isinstance(dataset, dict) or dataset.get("run_id") != resolved["dataset_run_id"]:
        raise SemanticPolicyTrainingError(
            "training report dataset does not match its storage location"
        )

    config = _config_from_report(data_root, report)
    summary, run_dir = _load_dataset_summary(
        data_root=data_root,
        format_id=config.format_id,
        run_id=resolved["dataset_run_id"],
    )
    validation_files = _split_files(summary, run_dir, "validation")
    test_files = _split_files(summary, run_dir, "test")

    output_dir = report_path.parent.resolve()
    artifacts = report.get("artifacts")
    action_vocabulary = report.get("action_vocabulary")
    if not isinstance(artifacts, dict) or not isinstance(action_vocabulary, dict):
        raise SemanticPolicyTrainingError("training report is missing artifact metadata")
    model_meta = artifacts.get("model")
    vocabulary_meta = artifacts.get("vocabulary")
    if not isinstance(model_meta, dict) or not isinstance(vocabulary_meta, dict):
        raise SemanticPolicyTrainingError("training report artifact metadata is malformed")

    model_path = _artifact_path(output_dir, str(model_meta.get("path")))
    vocabulary_path = _artifact_path(output_dir, str(vocabulary_meta.get("path")))
    if model_meta.get("sha256") != _sha256(model_path):
        raise SemanticPolicyTrainingError("saved model hash does not match training report")
    if vocabulary_meta.get("sha256") != _sha256(vocabulary_path):
        raise SemanticPolicyTrainingError(
            "saved action vocabulary hash does not match training report"
        )

    vocabulary = _load_vocabulary(vocabulary_path)
    expected_entries = action_vocabulary.get("entries")
    if expected_entries != len(vocabulary.entries):
        raise SemanticPolicyTrainingError(
            "saved action vocabulary entry count does not match training report"
        )

    model = SemanticTwoTower(
        state_buckets=config.state_buckets,
        action_buckets=config.action_buckets,
        embedding_dim=config.embedding_dim,
        seed=config.seed,
    )
    with np.load(model_path) as saved:
        state_table = saved["state_table"]
        action_table = saved["action_table"]
    if state_table.shape != model.state_table.shape:
        raise SemanticPolicyTrainingError(
            f"saved state table shape {state_table.shape} does not match configuration "
            f"{model.state_table.shape}"
        )
    if action_table.shape != model.action_table.shape:
        raise SemanticPolicyTrainingError(
            f"saved action table shape {action_table.shape} does not match configuration "
            f"{model.action_table.shape}"
        )
    model.state_table = state_table.astype(np.float32, copy=True)
    model.action_table = action_table.astype(np.float32, copy=True)

    diagnostics = {
        "schema": DIAGNOSTICS_SCHEMA,
        "generated_at": _utc_now(),
        "training_id": resolved["training_id"],
        "dataset_run_id": resolved["dataset_run_id"],
        "format_id": config.format_id,
        "source_training_report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "model_sha256": _sha256(model_path),
        "vocabulary_sha256": _sha256(vocabulary_path),
        "validation": _evaluate(
            model,
            paths=validation_files,
            vocabulary=vocabulary,
            config=config,
            split="validation",
        ),
        "test": _evaluate(
            model,
            paths=test_files,
            vocabulary=vocabulary,
            config=config,
            split="test",
        ),
        "authority": {
            "live_decision_authority": False,
            "exact_legality_authority": "pinned Showdown",
            "purpose": (
                "offline sampled semantic diagnostics only; no selector integration "
                "or candidate starvation authority"
            ),
        },
    }
    diagnostics_path = output_dir / "diagnostics.json"
    diagnostics_path.write_text(
        json.dumps(diagnostics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return diagnostics


def _load_evaluation_source(report_path: Path) -> tuple[dict[str, Any], bool]:
    diagnostics_path = report_path.parent / "diagnostics.json"
    if diagnostics_path.is_file():
        diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
        if diagnostics.get("schema") == DIAGNOSTICS_SCHEMA:
            return diagnostics, True
    return json.loads(report_path.read_text(encoding="utf-8")), False


def _metric_value(block: dict[str, Any] | None, key: str) -> float | None:
    if not isinstance(block, dict):
        return None
    value = block.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def compare_training_runs(
    data_root: str | Path,
    training_references: list[str],
    *,
    format_id: str = DEFAULT_FORMAT,
) -> list[dict[str, Any]]:
    if len(training_references) < 2:
        raise SemanticPolicyTrainingError("comparison requires at least two training runs")
    rows: list[dict[str, Any]] = []
    for reference in training_references:
        resolved = resolve_training_reference(
            data_root,
            reference,
            format_id=format_id,
        )
        report_path = Path(resolved["report_path"])
        evaluation, has_diagnostics = _load_evaluation_source(report_path)
        test = evaluation.get("test")
        if not isinstance(test, dict):
            raise SemanticPolicyTrainingError(
                f"training run {reference!r} has no test evaluation"
            )
        overall = test.get("overall")
        baseline = test.get("state_blind_baseline")
        baseline_overall = baseline.get("overall") if isinstance(baseline, dict) else None
        vocabulary_status = test.get("training_vocabulary_status")
        seen = (
            vocabulary_status.get("seen")
            if isinstance(vocabulary_status, dict)
            else None
        )
        unseen = (
            vocabulary_status.get("unseen")
            if isinstance(vocabulary_status, dict)
            else None
        )
        dataset_run_id = resolved["dataset_run_id"]
        training_id = resolved["training_id"]
        rows.append(
            {
                "run": preferred_training_alias(data_root, training_id) or reference,
                "training_id": training_id,
                "dataset": (
                    preferred_dataset_alias(data_root, dataset_run_id)
                    or dataset_run_id
                ),
                "dataset_run_id": dataset_run_id,
                "diagnostics": has_diagnostics,
                "test_rows": int(overall.get("rows", 0)) if isinstance(overall, dict) else 0,
                "top1": _metric_value(overall, "sampled_recall_at_1"),
                "top4": _metric_value(overall, "sampled_recall_at_4"),
                "top8": _metric_value(overall, "sampled_recall_at_8"),
                "top16": _metric_value(overall, "sampled_recall_at_16"),
                "blind_top1": _metric_value(
                    baseline_overall,
                    "sampled_recall_at_1",
                ),
                "seen_rows": int(seen.get("rows", 0)) if isinstance(seen, dict) else None,
                "seen_top1": _metric_value(seen, "sampled_recall_at_1"),
                "unseen_rows": (
                    int(unseen.get("rows", 0)) if isinstance(unseen, dict) else None
                ),
                "unseen_top1": _metric_value(unseen, "sampled_recall_at_1"),
            }
        )
    return rows


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{100.0 * value:.2f}%"


def format_comparison_table(rows: list[dict[str, Any]]) -> str:
    headers = (
        "run",
        "dataset",
        "rows",
        "top1",
        "top4",
        "top8",
        "top16",
        "blind1",
        "seen1",
        "unseen1",
    )
    values: list[tuple[str, ...]] = []
    for row in rows:
        unseen_label = _percent(row["unseen_top1"])
        if row["unseen_rows"] is not None:
            unseen_label += f" ({row['unseen_rows']})"
        seen_label = _percent(row["seen_top1"])
        if row["seen_rows"] is not None:
            seen_label += f" ({row['seen_rows']})"
        values.append(
            (
                str(row["run"]),
                str(row["dataset"]),
                str(row["test_rows"]),
                _percent(row["top1"]),
                _percent(row["top4"]),
                _percent(row["top8"]),
                _percent(row["top16"]),
                _percent(row["blind_top1"]),
                seen_label,
                unseen_label,
            )
        )
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in values))
        for index in range(len(headers))
    ]
    lines = [
        "  ".join(
            header.ljust(widths[index])
            for index, header in enumerate(headers)
        ),
        "  ".join("-" * width for width in widths),
    ]
    lines.extend(
        "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        for row in values
    )
    return "\n".join(lines)
