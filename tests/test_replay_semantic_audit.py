from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from champions_practice.replay_corpus import DEFAULT_FORMAT, initialize_layout
from champions_practice.replay_semantic_audit import (
    SEMANTIC_AUDIT_SCHEMA,
    SEMANTIC_POLICY_SCHEMA,
    SemanticAuditConfig,
    SemanticAuditError,
    _replay_split,
    _selected_target_count,
    build_semantic_policy_corpus,
    semantic_audit_status,
)


class FakeMoveMetadataWorker:
    showdown_revision = "a" * 40

    TARGETS = {
        "psychic": "normal",
        "protect": "self",
        "closecombat": "normal",
        "dragonpulse": "normal",
        "followme": "self",
        "direclaw": "normal",
    }

    def move_metadata(
        self,
        *,
        battle_format: str,
        move_ids: list[str],
    ) -> dict[str, dict]:
        assert battle_format == DEFAULT_FORMAT
        return {
            move_id: {
                "requested": move_id,
                "exists": move_id in self.TARGETS,
                "id": move_id,
                "name": move_id,
                "target": self.TARGETS.get(move_id),
                "category": "Status" if move_id in {"protect", "followme"} else "Special",
            }
            for move_id in move_ids
        }


def _active(species: str) -> dict:
    return {
        "base_species": species,
        "visible_species": species,
        "condition": "100/100",
        "hp_percent": 100.0,
        "status": None,
        "fainted": False,
        "boosts": {},
    }


def _public_state(turn: int) -> dict:
    return {
        "schema": "showdown-replay-public-state-v1",
        "turn": turn,
        "gametype": "doubles",
        "field": {"weather": None, "conditions": []},
        "sides": {
            "p1": {
                "name": "Alice",
                "preview_species": ["Indeedee-F", "Sneasler", "Rillaboom", "Gardevoir"],
                "active": [_active("Indeedee-F"), _active("Sneasler")],
                "side_conditions": [],
                "revealed": [],
            },
            "p2": {
                "name": "Bob",
                "preview_species": ["Pelipper", "Archaludon", "Swampert", "Grimmsnarl"],
                "active": [_active("Pelipper"), _active("Archaludon")],
                "side_conditions": [],
                "revealed": [],
            },
        },
        "source_prefix": {"line_count": 20 + turn, "sha256": "b" * 64},
    }


def _move(slot: int, move: str, *, gimmicks: list[str] | None = None) -> dict:
    return {
        "slot": slot,
        "kind": "move",
        "move": move,
        "move_name": move,
        "gimmicks": list(gimmicks or []),
        "resolved_target": {"side": "p2", "slot": 1},
        "selected_target": None,
        "target_authority": "resolved-public-target-only",
        "authority": "top-level-public-move",
    }


def _switch(slot: int, species: str) -> dict:
    return {
        "slot": slot,
        "kind": "switch",
        "switch_species": species,
        "authority": "reconstructed-pre-action-switch",
    }


def _joint(side: str, actions: list[dict], *, complete: bool = True) -> dict:
    return {
        "schema": "showdown-replay-joint-action-v1",
        "side": side,
        "identity_complete": complete,
        "exact_showdown_command_available": False,
        "actions": actions,
        "missing": (
            []
            if complete
            else [
                {
                    "slot": 1,
                    "reasons": ["selected-action-prevented-or-unobservable"],
                }
            ]
        ),
    }


def _trajectory(replay_id: str, rating: int) -> dict:
    return {
        "schema": "showdown-public-trajectory-v1",
        "replay_id": replay_id,
        "game_group": replay_id,
        "format_id": DEFAULT_FORMAT,
        "source": {
            "raw_sha256": "c" * 64,
            "rating": rating,
            "uploadtime": 123,
            "players": ["Alice", "Bob"],
            "inputlog_used": False,
        },
        "result": {"winner": "Alice", "tie": False},
        "decision_boundaries": 2,
        "complete_joint_labels": 3,
        "incomplete_joint_labels": 1,
        "decisions": [
            {
                "turn": 1,
                "public_state": _public_state(1),
                "joint_actions": {
                    "p1": _joint(
                        "p1",
                        [_move(1, "psychic"), _move(2, "protect")],
                    ),
                    "p2": _joint(
                        "p2",
                        [_switch(1, "Swampert"), _move(2, "dragonpulse")],
                    ),
                },
                "complete_label_sides": ["p1", "p2"],
            },
            {
                "turn": 2,
                "public_state": _public_state(2),
                "joint_actions": {
                    "p1": _joint(
                        "p1",
                        [_move(2, "direclaw")],
                        complete=False,
                    ),
                    "p2": _joint(
                        "p2",
                        [_move(1, "protect"), _move(2, "dragonpulse")],
                    ),
                },
                "complete_label_sides": ["p2"],
            },
        ],
    }


def _install_trajectory(
    data_root: Path,
    *,
    replay_id: str,
    rating: int,
    with_trajectory: bool = True,
) -> None:
    layout = initialize_layout(data_root)
    with closing(sqlite3.connect(layout.database)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS replays (
                replay_id TEXT PRIMARY KEY,
                format_id TEXT NOT NULL,
                uploadtime INTEGER,
                rating INTEGER,
                players_json TEXT NOT NULL,
                raw_relative_path TEXT NOT NULL,
                raw_sha256 TEXT NOT NULL,
                raw_bytes INTEGER NOT NULL,
                search_metadata_json TEXT NOT NULL,
                detail_metadata_json TEXT NOT NULL,
                downloaded_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS trajectories (
                replay_id TEXT PRIMARY KEY,
                format_id TEXT NOT NULL,
                raw_sha256 TEXT NOT NULL,
                trajectory_relative_path TEXT NOT NULL,
                trajectory_sha256 TEXT NOT NULL,
                trajectory_bytes INTEGER NOT NULL,
                schema_id TEXT NOT NULL,
                decision_boundaries INTEGER NOT NULL,
                complete_joint_labels INTEGER NOT NULL,
                incomplete_joint_labels INTEGER NOT NULL,
                extracted_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO replays VALUES (
                ?, ?, 123, ?, '[]', ?, ?, 2, '{}', '{}', 'now'
            )
            """,
            (
                replay_id,
                DEFAULT_FORMAT,
                rating,
                f"raw/{DEFAULT_FORMAT}/{replay_id}.json",
                "d" * 64,
            ),
        )
        if with_trajectory:
            trajectory = _trajectory(replay_id, rating)
            payload = (
                json.dumps(
                    trajectory,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
            path = layout.trajectories / DEFAULT_FORMAT / f"{replay_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            connection.execute(
                """
                INSERT INTO trajectories VALUES (
                    ?, ?, ?, ?, ?, ?, ?, 2, 3, 1, 'now'
                )
                """,
                (
                    replay_id,
                    DEFAULT_FORMAT,
                    "d" * 64,
                    path.relative_to(layout.root).as_posix(),
                    hashlib.sha256(payload).hexdigest(),
                    len(payload),
                    "showdown-public-trajectory-v1",
                ),
            )
        connection.commit()


def _read_rows(run_root: Path, files: list[dict]) -> list[dict]:
    rows = []
    for file in files:
        path = run_root / file["path"]
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            rows.extend(json.loads(line) for line in handle if line.strip())
    return rows


def test_selected_target_count_matches_public_doubles_geometry():
    state = _public_state(1)

    assert _selected_target_count(
        public_state=state,
        choosing_side="p1",
        source_slot=1,
        target_type="normal",
    ) == 3
    assert _selected_target_count(
        public_state=state,
        choosing_side="p1",
        source_slot=1,
        target_type="adjacentFoe",
    ) == 2
    assert _selected_target_count(
        public_state=state,
        choosing_side="p1",
        source_slot=1,
        target_type="adjacentAlly",
    ) == 1
    assert _selected_target_count(
        public_state=state,
        choosing_side="p1",
        source_slot=1,
        target_type="self",
    ) == 0


def test_replay_split_is_stable_and_group_level():
    replay_id = "gen9championsvgc2026regmc-12345"

    first = _replay_split(replay_id)
    second = _replay_split(replay_id)

    assert first == second
    assert first in {"train", "validation", "test"}


def test_build_semantic_policy_corpus_audits_and_shards_complete_rows(tmp_path: Path):
    data_root = tmp_path / "external"
    _install_trajectory(
        data_root,
        replay_id="gen9championsvgc2026regmc-100",
        rating=1650,
    )
    _install_trajectory(
        data_root,
        replay_id="gen9championsvgc2026regmc-101",
        rating=1350,
    )
    _install_trajectory(
        data_root,
        replay_id="gen9championsvgc2026regmc-102",
        rating=1500,
        with_trajectory=False,
    )

    summary = build_semantic_policy_corpus(
        config=SemanticAuditConfig(
            data_root=data_root,
            shard_rows=2,
            strict=True,
        ),
        worker=FakeMoveMetadataWorker(),
    )

    assert summary["schema"] == SEMANTIC_AUDIT_SCHEMA
    assert summary["policy_schema"] == SEMANTIC_POLICY_SCHEMA
    assert summary["source_archive_replays"] == 3
    assert summary["trajectory_replays_available"] == 2
    assert summary["trajectory_coverage_of_raw_archive"] == pytest.approx(2 / 3)
    assert summary["side_turn_rows"] == 8
    assert summary["semantic_trainable_rows"] == 6
    assert summary["incomplete_rows"] == 2
    assert summary["semantic_label_coverage"] == 0.75
    assert summary["action_families"] == {
        "move+move": 4,
        "switch+move": 2,
    }
    assert summary["missing_reasons"] == {
        "selected-action-prevented-or-unobservable": 2
    }
    assert summary["rating_band_rows"] == {
        "1200-1399": 4,
        "1600-1799": 4,
    }
    assert summary["turn_counts"] == {"1": 4, "2": 4}
    assert summary["exact_menu_context"]["selected_target_ambiguous_rows"] == 6
    assert summary["exact_menu_context"]["switch_party_slot_context_rows"] == 2
    assert summary["exact_menu_context"]["unknown_move_metadata_rows"] == 0
    assert sum(summary["split_rows"].values()) == 6

    run_root = (
        data_root
        / "processed"
        / "replay-policy"
        / DEFAULT_FORMAT
        / "runs"
        / summary["run_id"]
    )
    rows = _read_rows(run_root, summary["dataset"]["files"])
    assert len(rows) == 6
    assert all(row["schema"] == SEMANTIC_POLICY_SCHEMA for row in rows)
    assert all(row["game_group"] == row["replay_id"] for row in rows)
    assert all(row["split"] == _replay_split(row["replay_id"]) for row in rows)
    assert any(
        row["exact_menu_context"]["switch_context_required"]
        for row in rows
    )
    assert any(
        row["exact_menu_context"]["selected_target_ambiguous"]
        for row in rows
    )

    status = semantic_audit_status(data_root)
    assert status["available"] is True
    assert status["run_id"] == summary["run_id"]


def test_same_source_fingerprint_reuses_existing_run(tmp_path: Path):
    data_root = tmp_path / "external"
    _install_trajectory(
        data_root,
        replay_id="gen9championsvgc2026regmc-200",
        rating=1500,
    )
    worker = FakeMoveMetadataWorker()

    first = build_semantic_policy_corpus(
        config=SemanticAuditConfig(data_root=data_root, strict=True),
        worker=worker,
    )
    second = build_semantic_policy_corpus(
        config=SemanticAuditConfig(data_root=data_root, strict=True),
        worker=worker,
    )

    assert second["run_id"] == first["run_id"]
    assert second["generated_at"] == first["generated_at"]


def test_strict_mode_rejects_tampered_trajectory(tmp_path: Path):
    data_root = tmp_path / "external"
    replay_id = "gen9championsvgc2026regmc-300"
    _install_trajectory(data_root, replay_id=replay_id, rating=1500)
    path = (
        data_root
        / "trajectories"
        / DEFAULT_FORMAT
        / f"{replay_id}.json"
    )
    path.write_text("tampered", encoding="utf-8")

    with pytest.raises(SemanticAuditError, match="hash mismatch"):
        build_semantic_policy_corpus(
            config=SemanticAuditConfig(data_root=data_root, strict=True),
            worker=FakeMoveMetadataWorker(),
        )


def test_nonstrict_audit_reports_bounded_failure_examples(tmp_path: Path):
    data_root = tmp_path / "external"
    replay_id = "gen9championsvgc2026regmc-301"
    _install_trajectory(data_root, replay_id=replay_id, rating=1500)
    path = (
        data_root
        / "trajectories"
        / DEFAULT_FORMAT
        / f"{replay_id}.json"
    )
    path.write_text("tampered", encoding="utf-8")

    summary = build_semantic_policy_corpus(
        config=SemanticAuditConfig(data_root=data_root, strict=False),
        worker=FakeMoveMetadataWorker(),
    )

    assert summary["source_failures"] == {"SemanticAuditError": 1}
    assert summary["processing_failures"] == {"SemanticAuditError": 1}
    assert len(summary["source_failure_examples"]) == 1
    assert len(summary["processing_failure_examples"]) == 1
    assert summary["source_failure_examples"][0]["replay_id"] == replay_id
    assert "hash mismatch" in summary["source_failure_examples"][0]["detail"]
