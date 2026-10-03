"""Audit public replay trajectories and build a semantic-action policy corpus.

The broad public replay corpus cannot prove each choosing player's full Showdown
request, so this stage deliberately stops short of exact-menu labels. It produces
replay-disjoint semantic joint-action rows from complete public action identity and
measures the context that would still be required to recover exact commands.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean, median
from typing import Any, Iterable, Protocol

from champions_practice.replay_corpus import (
    DATA_ROOT_ENV,
    DEFAULT_FORMAT,
    _connect_manifest,
    _utc_now,
    _validate_public_id,
    initialize_layout,
)
from champions_practice.replay_trajectories import TRAJECTORY_SCHEMA
from champions_practice.search_worker import MoveMetadataWorker


SEMANTIC_POLICY_SCHEMA = "showdown-replay-semantic-policy-v1"
SEMANTIC_AUDIT_SCHEMA = "showdown-replay-semantic-audit-v1"
SPLIT_SCHEMA = "replay-group-sha256-90-5-5-v1"
DEFAULT_SHARD_ROWS = 50_000

_CHOOSABLE_TARGETS = {
    "normal",
    "any",
    "adjacentAlly",
    "adjacentAllyOrSelf",
    "adjacentFoe",
}


class SemanticAuditError(RuntimeError):
    """The semantic replay corpus could not be built without weakening authority."""


class MoveMetadataProvider(Protocol):
    @property
    def showdown_revision(self) -> str: ...

    def move_metadata(
        self,
        *,
        battle_format: str,
        move_ids: list[str],
    ) -> dict[str, dict[str, Any]]: ...


@dataclass(frozen=True)
class SemanticAuditConfig:
    data_root: Path
    format_id: str = DEFAULT_FORMAT
    max_replays: int = 0
    shard_rows: int = DEFAULT_SHARD_ROWS
    refresh: bool = False
    strict: bool = False

    def __post_init__(self) -> None:
        _validate_public_id(self.format_id, label="format")
        if (
            isinstance(self.max_replays, bool)
            or not isinstance(self.max_replays, int)
            or self.max_replays < 0
        ):
            raise ValueError("max_replays must be a non-negative integer")
        if (
            isinstance(self.shard_rows, bool)
            or not isinstance(self.shard_rows, int)
            or self.shard_rows < 1
        ):
            raise ValueError("shard_rows must be a positive integer")


def _to_id(value: object) -> str:
    return "".join(character for character in str(value or "").lower() if character.isalnum())


def _trajectory_rows(
    connection: sqlite3.Connection,
    *,
    format_id: str,
    max_replays: int,
) -> sqlite3.Cursor:
    limit = "" if max_replays == 0 else " LIMIT ?"
    parameters: tuple[Any, ...]
    if max_replays == 0:
        parameters = (format_id, TRAJECTORY_SCHEMA)
    else:
        parameters = (format_id, TRAJECTORY_SCHEMA, max_replays)
    return connection.execute(
        """
        SELECT replay_id, trajectory_relative_path, trajectory_sha256
        FROM trajectories
        WHERE format_id = ? AND schema_id = ?
        ORDER BY replay_id ASC
        """ + limit,
        parameters,
    )


def _safe_path(root: Path, relative: str) -> Path:
    path = (root / Path(relative)).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise SemanticAuditError(
            f"trajectory path escapes external corpus root: {relative}"
        ) from error
    return path


def _load_trajectory(
    root: Path,
    replay_id: str,
    relative_path: str,
    expected_sha256: str,
) -> dict[str, Any]:
    if not isinstance(relative_path, str) or not relative_path:
        raise SemanticAuditError(f"trajectory {replay_id} has no relative path")
    path = _safe_path(root, relative_path)
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise SemanticAuditError(
            f"trajectory hash mismatch for {replay_id}: expected {expected_sha256}, got {actual}"
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SemanticAuditError(f"trajectory {replay_id} is invalid JSON") from error
    if not isinstance(payload, dict):
        raise SemanticAuditError(f"trajectory {replay_id} is not an object")
    if payload.get("schema") != TRAJECTORY_SCHEMA:
        raise SemanticAuditError(
            f"trajectory {replay_id} has unsupported schema {payload.get('schema')!r}"
        )
    if payload.get("replay_id") != replay_id:
        raise SemanticAuditError(f"trajectory replay id mismatch for {replay_id}")
    if payload.get("game_group") != replay_id:
        raise SemanticAuditError(
            f"trajectory {replay_id} does not preserve replay-disjoint game_group"
        )
    return payload


def _iter_actions(trajectory: dict[str, Any]) -> Iterable[dict[str, Any]]:
    decisions = trajectory.get("decisions")
    if not isinstance(decisions, list):
        return
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        joints = decision.get("joint_actions")
        if not isinstance(joints, dict):
            continue
        for side in ("p1", "p2"):
            label = joints.get(side)
            if not isinstance(label, dict):
                continue
            actions = label.get("actions")
            if not isinstance(actions, list):
                continue
            for action in actions:
                if isinstance(action, dict):
                    yield action


def _collect_source(
    connection: sqlite3.Connection,
    *,
    root: Path,
    config: SemanticAuditConfig,
) -> tuple[str, set[str], int, Counter[str]]:
    digest = hashlib.sha256()
    move_ids: set[str] = set()
    valid = 0
    failures: Counter[str] = Counter()
    for replay_id, relative, trajectory_sha in _trajectory_rows(
        connection,
        format_id=config.format_id,
        max_replays=config.max_replays,
    ):
        try:
            trajectory = _load_trajectory(root, replay_id, relative, trajectory_sha)
        except Exception as error:
            failures[type(error).__name__] += 1
            if config.strict:
                raise
            continue
        digest.update(replay_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(trajectory_sha.encode("ascii"))
        digest.update(b"\n")
        valid += 1
        for action in _iter_actions(trajectory):
            if action.get("kind") == "move":
                move = _to_id(action.get("move"))
                if move:
                    move_ids.add(move)
    return digest.hexdigest(), move_ids, valid, failures


def _metadata_batches(
    worker: MoveMetadataProvider,
    *,
    battle_format: str,
    move_ids: set[str],
) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    ordered = sorted(move_ids)
    for offset in range(0, len(ordered), 4096):
        metadata.update(
            worker.move_metadata(
                battle_format=battle_format,
                move_ids=ordered[offset : offset + 4096],
            )
        )
    return metadata


def _replay_split(replay_id: str) -> str:
    bucket = int(hashlib.sha256(replay_id.encode("utf-8")).hexdigest()[:8], 16) % 10_000
    if bucket < 9_000:
        return "train"
    if bucket < 9_500:
        return "validation"
    return "test"


def _rating_band(rating: object) -> str:
    if isinstance(rating, bool) or not isinstance(rating, int):
        return "unrated"
    if rating < 1200:
        return "<1200"
    if rating < 1400:
        return "1200-1399"
    if rating < 1600:
        return "1400-1599"
    if rating < 1800:
        return "1600-1799"
    return "1800+"


def _turn_band(turn: int) -> str:
    if turn == 1:
        return "1"
    if turn <= 4:
        return "2-4"
    if turn <= 8:
        return "5-8"
    if turn <= 12:
        return "9-12"
    return "13+"


def _active_occupied(public_state: dict[str, Any], side: str, slot: int) -> bool:
    sides = public_state.get("sides")
    if not isinstance(sides, dict):
        return False
    side_state = sides.get(side)
    if not isinstance(side_state, dict):
        return False
    active = side_state.get("active")
    if not isinstance(active, list) or slot < 1 or slot > len(active):
        return False
    value = active[slot - 1]
    return isinstance(value, dict) and value.get("fainted") is not True


def _target_loc_occupied(
    public_state: dict[str, Any],
    choosing_side: str,
    target_loc: int,
) -> bool:
    if target_loc > 0:
        target_side = "p2" if choosing_side == "p1" else "p1"
        return _active_occupied(public_state, target_side, target_loc)
    return _active_occupied(public_state, choosing_side, -target_loc)


def _valid_target_loc(
    *,
    source_slot: int,
    target_loc: int,
    target_type: str,
    active_per_half: int = 2,
) -> bool:
    if target_loc == 0 or abs(target_loc) > active_per_half:
        return False
    source_loc = -source_slot
    is_self = source_loc == target_loc
    is_foe = target_loc > 0
    across = -(active_per_half + 1 - target_loc)
    is_adjacent = (
        abs(across - source_loc) <= 1
        if target_loc > 0
        else abs(target_loc - source_loc) == 1
    )
    if target_type == "normal":
        return is_adjacent
    if target_type == "adjacentAlly":
        return is_adjacent and not is_foe
    if target_type == "adjacentAllyOrSelf":
        return (is_adjacent and not is_foe) or is_self
    if target_type == "adjacentFoe":
        return is_adjacent and is_foe
    if target_type == "any":
        return not is_self
    return False


def _selected_target_count(
    *,
    public_state: dict[str, Any],
    choosing_side: str,
    source_slot: int,
    target_type: str | None,
) -> int:
    if target_type not in _CHOOSABLE_TARGETS:
        return 0
    count = 0
    for target_loc in (1, 2, -1, -2):
        if not _valid_target_loc(
            source_slot=source_slot,
            target_loc=target_loc,
            target_type=target_type,
        ):
            continue
        if _target_loc_occupied(public_state, choosing_side, target_loc):
            count += 1
    return count


def _semantic_action(
    action: dict[str, Any],
    *,
    side: str,
    public_state: dict[str, Any],
    move_metadata: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    slot = action.get("slot")
    kind = action.get("kind")
    if isinstance(slot, bool) or not isinstance(slot, int) or slot < 1:
        raise SemanticAuditError("semantic action has invalid slot")
    if kind == "move":
        move = _to_id(action.get("move"))
        if not move:
            raise SemanticAuditError("semantic move action has no move id")
        metadata = move_metadata.get(move, {})
        target_type = metadata.get("target") if metadata.get("exists") else None
        target_count = _selected_target_count(
            public_state=public_state,
            choosing_side=side,
            source_slot=slot,
            target_type=target_type,
        )
        gimmicks = action.get("gimmicks", [])
        if not isinstance(gimmicks, list) or not all(
            isinstance(value, str) for value in gimmicks
        ):
            raise SemanticAuditError("semantic move gimmicks are malformed")
        semantic = {
            "slot": slot,
            "kind": "move",
            "move": move,
            "gimmicks": sorted(_to_id(value) for value in gimmicks if _to_id(value)),
        }
        audit = {
            "target_type": target_type,
            "selected_target_candidate_count": target_count,
            "selected_target_ambiguous": target_count > 1,
            "move_metadata_known": bool(metadata.get("exists")),
        }
        return semantic, audit
    if kind == "switch":
        species = action.get("switch_species")
        if not isinstance(species, str) or not species:
            raise SemanticAuditError("semantic switch action has no species")
        return (
            {
                "slot": slot,
                "kind": "switch",
                "switch_species": species,
                "switch_species_id": _to_id(species),
            },
            {
                "requires_party_slot_context": True,
            },
        )
    if kind == "pass":
        return {"slot": slot, "kind": "pass"}, {}
    raise SemanticAuditError(f"unsupported semantic action kind {kind!r}")


def _semantic_label(
    label: dict[str, Any],
    *,
    side: str,
    public_state: dict[str, Any],
    move_metadata: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    actions = label.get("actions")
    if not isinstance(actions, list):
        raise SemanticAuditError("joint action label has no actions")
    converted: list[dict[str, Any]] = []
    action_audit: list[dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, dict):
            raise SemanticAuditError("joint action contains non-object action")
        semantic, audit = _semantic_action(
            action,
            side=side,
            public_state=public_state,
            move_metadata=move_metadata,
        )
        converted.append(semantic)
        action_audit.append({"slot": semantic["slot"], **audit})
    converted.sort(key=lambda action: action["slot"])
    action_audit.sort(key=lambda action: action["slot"])
    family = "+".join(action["kind"] for action in converted)
    target_ambiguous = any(
        audit.get("selected_target_ambiguous") is True for audit in action_audit
    )
    switch_context = any(
        audit.get("requires_party_slot_context") is True for audit in action_audit
    )
    generic_mega = any(
        "mega" in action.get("gimmicks", [])
        for action in converted
        if action["kind"] == "move"
    )
    metadata_unknown = any(
        audit.get("move_metadata_known") is False for audit in action_audit
    )
    requirements = []
    if target_ambiguous:
        requirements.append("selected-target")
    if switch_context:
        requirements.append("party-slot-order")
    if generic_mega:
        requirements.append("exact-mega-variant")
    if metadata_unknown:
        requirements.append("move-metadata")
    return (
        {
            "actions": converted,
            "action_family": family,
        },
        {
            "actions": action_audit,
            "selected_target_ambiguous": target_ambiguous,
            "switch_context_required": switch_context,
            "generic_mega_context": generic_mega,
            "move_metadata_unknown": metadata_unknown,
            "exact_menu_context_requirements": requirements,
        },
    )


class _SplitShardWriter:
    def __init__(self, root: Path, split: str, shard_rows: int) -> None:
        self.root = root / split
        self.root.mkdir(parents=True, exist_ok=True)
        self.split = split
        self.shard_rows = shard_rows
        self.total_rows = 0
        self._shard_index = -1
        self._rows_in_shard = 0
        self._handle: Any = None
        self.files: list[dict[str, Any]] = []

    def _open_next(self) -> None:
        self.close_current()
        self._shard_index += 1
        self._rows_in_shard = 0
        name = f"part-{self._shard_index:05d}.jsonl.gz"
        path = self.root / name
        self._handle = gzip.open(path, "wt", encoding="utf-8", newline="\n")
        self.files.append({"path": f"{self.split}/{name}", "rows": 0})

    def write(self, row: dict[str, Any]) -> None:
        if self._handle is None or self._rows_in_shard >= self.shard_rows:
            self._open_next()
        self._handle.write(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        self._handle.write("\n")
        self._rows_in_shard += 1
        self.total_rows += 1
        self.files[-1]["rows"] += 1

    def close_current(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def close(self) -> None:
        self.close_current()


def _counter_dict(counter: Counter[Any]) -> dict[str, int]:
    return {
        str(key): int(value)
        for key, value in sorted(counter.items(), key=lambda item: str(item[0]))
    }


def _percentile(values: list[int], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * fraction)))
    return float(ordered[index])


def build_semantic_policy_corpus(
    *,
    config: SemanticAuditConfig,
    worker: MoveMetadataProvider | None = None,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    layout = initialize_layout(config.data_root, project_root=project_root)
    connection = _connect_manifest(layout.database)
    owned_worker: MoveMetadataWorker | None = None
    try:
        raw_replays = int(
            connection.execute(
                "SELECT COUNT(*) FROM replays WHERE format_id = ?",
                (config.format_id,),
            ).fetchone()[0]
        )
        trajectory_replays = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM trajectories
                WHERE format_id = ? AND schema_id = ?
                """,
                (config.format_id, TRAJECTORY_SCHEMA),
            ).fetchone()[0]
        )
        source_fingerprint, move_ids, usable_source_replays, source_failures = _collect_source(
            connection,
            root=layout.root,
            config=config,
        )

        if worker is None:
            owned_worker = MoveMetadataWorker(project_root)
            worker = owned_worker
        move_metadata = _metadata_batches(
            worker,
            battle_format=config.format_id,
            move_ids=move_ids,
        )
        showdown_revision = worker.showdown_revision

        identity = hashlib.sha256()
        identity.update(SEMANTIC_POLICY_SCHEMA.encode("ascii"))
        identity.update(b"\0")
        identity.update(SPLIT_SCHEMA.encode("ascii"))
        identity.update(b"\0")
        identity.update(config.format_id.encode("ascii"))
        identity.update(b"\0")
        identity.update(source_fingerprint.encode("ascii"))
        identity.update(b"\0")
        identity.update(showdown_revision.encode("ascii"))
        run_id = identity.hexdigest()[:20]

        base = layout.processed / "replay-policy" / config.format_id
        runs = base / "runs"
        run_dir = runs / run_id
        summary_path = run_dir / "summary.json"
        latest_path = base / "latest-summary.json"
        if summary_path.is_file() and not config.refresh:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            latest_path.parent.mkdir(parents=True, exist_ok=True)
            latest_path.write_text(
                json.dumps(summary, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return summary

        temp_dir = runs / f".building-{run_id}-{os.getpid()}"
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=False)

        writers = {
            split: _SplitShardWriter(temp_dir, split, config.shard_rows)
            for split in ("train", "validation", "test")
        }
        side_turns = 0
        complete_rows = 0
        incomplete_rows = 0
        action_families: Counter[str] = Counter()
        missing_reasons: Counter[str] = Counter()
        rating_rows: Counter[str] = Counter()
        rating_replays: Counter[str] = Counter()
        turn_counts: Counter[int] = Counter()
        turn_bands: Counter[str] = Counter()
        split_rows: Counter[str] = Counter()
        split_replays: Counter[str] = Counter()
        target_ambiguous_rows = 0
        target_sensitive_rows = 0
        switch_rows = 0
        generic_mega_rows = 0
        unknown_move_metadata_rows = 0
        usable_per_replay: list[int] = []
        processing_failures: Counter[str] = Counter()
        processed_replays = 0

        try:
            for replay_id, relative, trajectory_sha in _trajectory_rows(
                connection,
                format_id=config.format_id,
                max_replays=config.max_replays,
            ):
                try:
                    trajectory = _load_trajectory(
                        layout.root,
                        replay_id,
                        relative,
                        trajectory_sha,
                    )
                    source = trajectory.get("source", {})
                    rating = source.get("rating") if isinstance(source, dict) else None
                    rating_band = _rating_band(rating)
                    split = _replay_split(replay_id)
                    split_replays[split] += 1
                    rating_replays[rating_band] += 1
                    replay_usable = 0

                    decisions = trajectory.get("decisions")
                    if not isinstance(decisions, list):
                        raise SemanticAuditError(
                            f"trajectory {replay_id} has no decision list"
                        )
                    for decision in decisions:
                        if not isinstance(decision, dict):
                            raise SemanticAuditError(
                                f"trajectory {replay_id} has a non-object decision"
                            )
                        turn = decision.get("turn")
                        if isinstance(turn, bool) or not isinstance(turn, int) or turn < 1:
                            raise SemanticAuditError(
                                f"trajectory {replay_id} has invalid turn"
                            )
                        public_state = decision.get("public_state")
                        joints = decision.get("joint_actions")
                        if not isinstance(public_state, dict) or not isinstance(joints, dict):
                            raise SemanticAuditError(
                                f"trajectory {replay_id} has malformed decision state"
                            )

                        for side in ("p1", "p2"):
                            side_turns += 1
                            turn_counts[turn] += 1
                            turn_bands[_turn_band(turn)] += 1
                            rating_rows[rating_band] += 1
                            label = joints.get(side)
                            if not isinstance(label, dict):
                                incomplete_rows += 1
                                missing_reasons["missing-joint-label"] += 1
                                continue
                            if label.get("identity_complete") is not True:
                                incomplete_rows += 1
                                missing = label.get("missing", [])
                                reasons_found = False
                                if isinstance(missing, list):
                                    for entry in missing:
                                        if not isinstance(entry, dict):
                                            continue
                                        reasons = entry.get("reasons", [])
                                        if not isinstance(reasons, list):
                                            continue
                                        for reason in reasons:
                                            if isinstance(reason, str) and reason:
                                                missing_reasons[reason] += 1
                                                reasons_found = True
                                if not reasons_found:
                                    missing_reasons["unspecified-incomplete-label"] += 1
                                continue

                            semantic, context = _semantic_label(
                                label,
                                side=side,
                                public_state=public_state,
                                move_metadata=move_metadata,
                            )
                            complete_rows += 1
                            replay_usable += 1
                            split_rows[split] += 1
                            action_families[semantic["action_family"]] += 1
                            target_ambiguous_rows += int(
                                context["selected_target_ambiguous"]
                            )
                            target_sensitive_rows += int(
                                any(
                                    int(action.get("selected_target_candidate_count", 0)) > 0
                                    for action in context["actions"]
                                )
                            )
                            switch_rows += int(context["switch_context_required"])
                            generic_mega_rows += int(context["generic_mega_context"])
                            unknown_move_metadata_rows += int(
                                context["move_metadata_unknown"]
                            )

                            row = {
                                "schema": SEMANTIC_POLICY_SCHEMA,
                                "replay_id": replay_id,
                                "game_group": replay_id,
                                "split": split,
                                "turn": turn,
                                "turn_band": _turn_band(turn),
                                "side": side,
                                "rating": rating if isinstance(rating, int) else None,
                                "rating_band": rating_band,
                                "public_state": public_state,
                                "semantic_label": semantic,
                                "exact_menu_context": context,
                                "source": {
                                    "trajectory_sha256": trajectory_sha,
                                    "raw_sha256": (
                                        source.get("raw_sha256")
                                        if isinstance(source, dict)
                                        else None
                                    ),
                                    "trajectory_schema": TRAJECTORY_SCHEMA,
                                },
                            }
                            writers[split].write(row)

                    usable_per_replay.append(replay_usable)
                    processed_replays += 1
                except Exception as error:
                    processing_failures[type(error).__name__] += 1
                    if config.strict:
                        raise
                    continue
        finally:
            for writer in writers.values():
                writer.close()

        generated_at = _utc_now()
        trajectory_coverage = (
            round(trajectory_replays / raw_replays, 6) if raw_replays else 0.0
        )
        semantic_coverage = (
            round(complete_rows / side_turns, 6) if side_turns else 0.0
        )
        summary = {
            "schema": SEMANTIC_AUDIT_SCHEMA,
            "policy_schema": SEMANTIC_POLICY_SCHEMA,
            "split_schema": SPLIT_SCHEMA,
            "run_id": run_id,
            "format_id": config.format_id,
            "generated_at": generated_at,
            "showdown_revision": showdown_revision,
            "source_fingerprint": source_fingerprint,
            "source_archive_replays": raw_replays,
            "trajectory_replays_available": trajectory_replays,
            "trajectory_replays_scanned": usable_source_replays,
            "trajectory_coverage_of_raw_archive": trajectory_coverage,
            "source_failures": _counter_dict(source_failures),
            "processing_failures": _counter_dict(processing_failures),
            "side_turn_rows": side_turns,
            "semantic_trainable_rows": complete_rows,
            "incomplete_rows": incomplete_rows,
            "semantic_label_coverage": semantic_coverage,
            "action_families": _counter_dict(action_families),
            "missing_reasons": _counter_dict(missing_reasons),
            "rating_band_rows": _counter_dict(rating_rows),
            "rating_band_replays": _counter_dict(rating_replays),
            "turn_counts": _counter_dict(turn_counts),
            "turn_bands": _counter_dict(turn_bands),
            "split_rows": _counter_dict(split_rows),
            "split_replays": _counter_dict(split_replays),
            "exact_menu_context": {
                "selected_target_ambiguous_rows": target_ambiguous_rows,
                "target_sensitive_rows": target_sensitive_rows,
                "switch_party_slot_context_rows": switch_rows,
                "generic_mega_context_rows": generic_mega_rows,
                "unknown_move_metadata_rows": unknown_move_metadata_rows,
                "note": (
                    "These are public semantic-label context requirements, not "
                    "fabricated exact-menu commands."
                ),
            },
            "usable_rows_per_replay": {
                "count": len(usable_per_replay),
                "mean": (
                    round(fmean(usable_per_replay), 3)
                    if usable_per_replay
                    else 0.0
                ),
                "median": (
                    float(median(usable_per_replay))
                    if usable_per_replay
                    else 0.0
                ),
                "p90": _percentile(usable_per_replay, 0.90),
                "max": max(usable_per_replay, default=0),
            },
            "move_catalog": {
                "unique_move_ids": len(move_ids),
                "known": sum(
                    1 for row in move_metadata.values() if row.get("exists") is True
                ),
                "unknown": sum(
                    1 for row in move_metadata.values() if row.get("exists") is not True
                ),
            },
            "dataset": {
                "root": f"processed/replay-policy/{config.format_id}/runs/{run_id}",
                "shard_rows": config.shard_rows,
                "files": [
                    file
                    for split in ("train", "validation", "test")
                    for file in writers[split].files
                ],
            },
        }

        (temp_dir / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if run_dir.exists():
            shutil.rmtree(run_dir)
        os.replace(temp_dir, run_dir)
        latest_path.parent.mkdir(parents=True, exist_ok=True)
        latest_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return summary
    finally:
        if owned_worker is not None:
            owned_worker.close()
        connection.close()


def semantic_audit_status(
    data_root: str | Path,
    *,
    format_id: str = DEFAULT_FORMAT,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    layout = initialize_layout(data_root, project_root=project_root)
    path = layout.processed / "replay-policy" / format_id / "latest-summary.json"
    if not path.is_file():
        return {
            "schema": SEMANTIC_AUDIT_SCHEMA,
            "format_id": format_id,
            "available": False,
            "data_root": str(layout.root),
        }
    summary = json.loads(path.read_text(encoding="utf-8"))
    return {
        **summary,
        "available": True,
        "data_root": str(layout.root),
    }


def _resolve_data_root(value: str | None) -> Path:
    selected = value or os.environ.get(DATA_ROOT_ENV)
    if not selected:
        raise SemanticAuditError(f"Pass --data-root or set {DATA_ROOT_ENV}.")
    return Path(selected)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit public replay trajectories and build replay-disjoint semantic "
            "policy shards."
        )
    )
    parser.add_argument("--data-root", help=f"External corpus root; or set {DATA_ROOT_ENV}.")
    parser.add_argument("--format", default=DEFAULT_FORMAT, dest="format_id")
    parser.add_argument(
        "--max-replays",
        type=int,
        default=0,
        help="Maximum trajectories to scan; 0 means all available.",
    )
    parser.add_argument(
        "--shard-rows",
        type=int,
        default=DEFAULT_SHARD_ROWS,
        help="Maximum semantic examples per compressed JSONL shard.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Rebuild even when the same source fingerprint already has a run.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Stop on the first corrupt or malformed trajectory.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print the latest semantic audit without rebuilding.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    try:
        data_root = _resolve_data_root(args.data_root)
        if args.status:
            print(
                json.dumps(
                    semantic_audit_status(data_root, format_id=args.format_id),
                    indent=2,
                    sort_keys=True,
                )
            )
            return
        summary = build_semantic_policy_corpus(
            config=SemanticAuditConfig(
                data_root=data_root,
                format_id=args.format_id,
                max_replays=args.max_replays,
                shard_rows=args.shard_rows,
                refresh=args.refresh,
                strict=args.strict,
            )
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
    except (SemanticAuditError, ValueError, OSError, sqlite3.Error) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
