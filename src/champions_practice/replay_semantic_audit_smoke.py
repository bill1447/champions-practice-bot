"""Pinned-Showdown smoke for replay semantic policy corpus auditing."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from champions_practice.replay_corpus import DEFAULT_FORMAT, initialize_layout
from champions_practice.replay_semantic_audit import (
    SemanticAuditConfig,
    build_semantic_policy_corpus,
)


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


def _move(slot: int, move: str) -> dict:
    return {
        "slot": slot,
        "kind": "move",
        "move": move,
        "move_name": move,
        "gimmicks": [],
        "resolved_target": {"side": "p2", "slot": 1},
        "selected_target": None,
        "target_authority": "resolved-public-target-only",
        "authority": "top-level-public-move",
    }


def _trajectory(replay_id: str) -> dict:
    public_state = {
        "schema": "showdown-replay-public-state-v1",
        "turn": 1,
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
        "source_prefix": {"line_count": 20, "sha256": "a" * 64},
    }
    return {
        "schema": "showdown-public-trajectory-v1",
        "replay_id": replay_id,
        "game_group": replay_id,
        "format_id": DEFAULT_FORMAT,
        "source": {
            "raw_sha256": "b" * 64,
            "rating": 1650,
            "uploadtime": 100,
            "players": ["Alice", "Bob"],
            "inputlog_used": False,
        },
        "result": {"winner": "Alice", "tie": False},
        "decision_boundaries": 1,
        "complete_joint_labels": 2,
        "incomplete_joint_labels": 0,
        "decisions": [
            {
                "turn": 1,
                "public_state": public_state,
                "joint_actions": {
                    "p1": {
                        "schema": "showdown-replay-joint-action-v1",
                        "side": "p1",
                        "identity_complete": True,
                        "exact_showdown_command_available": False,
                        "actions": [_move(1, "Psychic"), _move(2, "Protect")],
                        "missing": [],
                    },
                    "p2": {
                        "schema": "showdown-replay-joint-action-v1",
                        "side": "p2",
                        "identity_complete": True,
                        "exact_showdown_command_available": False,
                        "actions": [_move(1, "Protect"), _move(2, "Dragon Pulse")],
                        "missing": [],
                    },
                },
                "complete_label_sides": ["p1", "p2"],
            }
        ],
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="champions-semantic-audit-") as temp:
        root = Path(temp)
        layout = initialize_layout(root)
        replay_id = f"{DEFAULT_FORMAT}-fixture"
        trajectory = _trajectory(replay_id)
        payload = (
            json.dumps(
                trajectory,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        trajectory_path = layout.trajectories / DEFAULT_FORMAT / f"{replay_id}.json"
        trajectory_path.parent.mkdir(parents=True, exist_ok=True)
        trajectory_path.write_bytes(payload)

        with closing(sqlite3.connect(layout.database)) as connection:
            connection.execute(
                """
                CREATE TABLE replays (
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
                CREATE TABLE trajectories (
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
                    ?, ?, 100, 1650, '[]', ?, ?, 2, '{}', '{}', 'now'
                )
                """,
                (
                    replay_id,
                    DEFAULT_FORMAT,
                    f"raw/{DEFAULT_FORMAT}/{replay_id}.json",
                    "b" * 64,
                ),
            )
            connection.execute(
                """
                INSERT INTO trajectories VALUES (
                    ?, ?, ?, ?, ?, ?, ?, 1, 2, 0, 'now'
                )
                """,
                (
                    replay_id,
                    DEFAULT_FORMAT,
                    "b" * 64,
                    trajectory_path.relative_to(layout.root).as_posix(),
                    hashlib.sha256(payload).hexdigest(),
                    len(payload),
                    "showdown-public-trajectory-v1",
                ),
            )
            connection.commit()

        summary = build_semantic_policy_corpus(
            config=SemanticAuditConfig(
                data_root=root,
                shard_rows=1,
                strict=True,
            )
        )

        if summary["semantic_trainable_rows"] != 2:
            raise SystemExit("ERROR: semantic audit lost complete public labels")
        if summary["move_catalog"]["unknown"] != 0:
            raise SystemExit("ERROR: pinned Showdown did not resolve fixture moves")
        if summary["exact_menu_context"]["selected_target_ambiguous_rows"] < 1:
            raise SystemExit(
                "ERROR: target-selection ambiguity was not detected from pinned move metadata"
            )
        if sum(summary["split_rows"].values()) != 2:
            raise SystemExit("ERROR: semantic audit split accounting is inconsistent")

        print("PASS: pinned replay semantic audit")
        print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
