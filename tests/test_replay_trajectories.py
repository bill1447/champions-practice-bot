from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from champions_practice.replay_corpus import DEFAULT_FORMAT, initialize_layout
from champions_practice.replay_trajectories import (
    TRAJECTORY_SCHEMA,
    TrajectoryConfig,
    TrajectoryExtractionError,
    extract_public_trajectory,
    extract_trajectory_corpus,
    trajectory_status,
)


def _base_log() -> str:
    return "\n".join(
        [
            "|player|p1|Alice||1500",
            "|player|p2|Bob||1500",
            "|gametype|doubles",
            "|poke|p1|Indeedee-F, L50, F|",
            "|poke|p1|Sneasler, L50, M|",
            "|poke|p1|Rillaboom, L50, M|",
            "|poke|p1|Gardevoir, L50, F|",
            "|poke|p2|Pelipper, L50, M|",
            "|poke|p2|Archaludon, L50|",
            "|poke|p2|Swampert, L50, M|",
            "|poke|p2|Grimmsnarl, L50, M|",
            "|teampreview|4",
            "|switch|p1a: Indeedee|Indeedee-F, L50, F|100/100",
            "|switch|p1b: Sneasler|Sneasler, L50, M|100/100",
            "|switch|p2a: Pelipper|Pelipper, L50, M|100/100",
            "|switch|p2b: Archaludon|Archaludon, L50|100/100",
            "|-ability|p1a: Indeedee|Psychic Surge",
            "|-fieldstart|move: Psychic Terrain",
            "|turn|1",
            "|move|p1a: Indeedee|Follow Me|p1a: Indeedee",
            "|move|p2a: Pelipper|Protect|p2a: Pelipper",
            "|move|p1b: Sneasler|Close Combat|p2b: Archaludon",
            "|-damage|p2b: Archaludon|60/100",
            "|move|p2b: Archaludon|Dragon Pulse|p1b: Sneasler",
            "|-damage|p1b: Sneasler|55/100",
            "|upkeep",
            "|turn|2",
            "|switch|p1a: Rillaboom|Rillaboom, L50, M|100/100",
            "|move|p2a: Pelipper|Protect|p2a: Pelipper",
            "|move|p1b: Sneasler|Dire Claw|p2b: Archaludon",
            "|move|p2b: Archaludon|Dragon Pulse|p1b: Sneasler",
            "|upkeep",
            "|win|Alice",
        ]
    )


def _detail(replay_id: str, log: str | None = None) -> dict:
    return {
        "id": replay_id,
        "format": "[Gen 9] Champions 2026 Reg M-C",
        "players": ["Alice", "Bob"],
        "rating": 1500,
        "uploadtime": 100,
        "log": log or _base_log(),
        "inputlog": ">p1 move 4 2, move 3 1\n>p2 switch 6, move 1 2",
    }


def _extract(log: str | None = None) -> dict:
    replay_id = f"{DEFAULT_FORMAT}-100"
    return extract_public_trajectory(
        _detail(replay_id, log),
        replay_id=replay_id,
        format_id=DEFAULT_FORMAT,
        raw_sha256="a" * 64,
        rating=1500,
        uploadtime=100,
    )


def _revealed(state: dict, side: str, species: str) -> dict:
    return next(
        entry
        for entry in state["sides"][side]["revealed"]
        if entry["species"] == species
    )


def test_extracts_public_prefix_state_and_joint_action_identity():
    trajectory = _extract()

    assert trajectory["schema"] == TRAJECTORY_SCHEMA
    assert trajectory["source"]["inputlog_used"] is False
    assert trajectory["game_group"] == trajectory["replay_id"]
    assert trajectory["decision_boundaries"] == 2
    assert trajectory["complete_joint_labels"] == 4
    assert trajectory["incomplete_joint_labels"] == 0

    turn1, turn2 = trajectory["decisions"]
    assert turn1["public_state"]["field"]["conditions"] == ["psychicterrain"]
    assert _revealed(
        turn1["public_state"],
        "p1",
        "Sneasler",
    )["moves"] == []

    p1_turn1 = turn1["joint_actions"]["p1"]
    assert [action["move"] for action in p1_turn1["actions"]] == [
        "followme",
        "closecombat",
    ]
    assert p1_turn1["actions"][1]["resolved_target"] == {
        "side": "p2",
        "slot": 2,
    }
    assert p1_turn1["actions"][1]["selected_target"] is None
    assert p1_turn1["exact_showdown_command_available"] is False

    assert _revealed(
        turn2["public_state"],
        "p1",
        "Sneasler",
    )["moves"] == ["closecombat"]
    assert turn2["public_state"]["sides"]["p1"]["active"][0]["base_species"] == (
        "Indeedee-F"
    )
    p1_turn2 = turn2["joint_actions"]["p1"]
    assert p1_turn2["actions"][0] == {
        "slot": 1,
        "kind": "switch",
        "switch_species": "Rillaboom",
        "authority": "reconstructed-pre-action-switch",
    }
    assert p1_turn2["actions"][1]["move"] == "direclaw"


def test_inputlog_does_not_change_extracted_decision_rows():
    replay_id = f"{DEFAULT_FORMAT}-101"
    first = _detail(replay_id)
    second = _detail(replay_id)
    first["inputlog"] = ">p1 move 1 1, move 1 1"
    second["inputlog"] = ">p1 move 4 -1, switch 6"

    left = extract_public_trajectory(
        first,
        replay_id=replay_id,
        format_id=DEFAULT_FORMAT,
        raw_sha256="b" * 64,
    )
    right = extract_public_trajectory(
        second,
        replay_id=replay_id,
        format_id=DEFAULT_FORMAT,
        raw_sha256="b" * 64,
    )

    assert left == right
    assert left["source"]["inputlog_used"] is False


def test_called_move_is_not_mistaken_for_second_selected_action():
    log = _base_log().replace(
        "|move|p1a: Indeedee|Follow Me|p1a: Indeedee",
        "\n".join(
            [
                "|move|p1a: Indeedee|Metronome|p1a: Indeedee",
                "|move|p1a: Indeedee|Thunderbolt|p2b: Archaludon|"
                "[from] move: Metronome",
            ]
        ),
        1,
    )

    trajectory = _extract(log)
    p1 = trajectory["decisions"][0]["joint_actions"]["p1"]

    assert p1["identity_complete"]
    assert p1["actions"][0]["move"] == "metronome"
    assert all(action.get("move") != "thunderbolt" for action in p1["actions"])


def test_prevented_action_leaves_side_incomplete_instead_of_fabricating_label():
    log = _base_log().replace(
        "|move|p1a: Indeedee|Follow Me|p1a: Indeedee",
        "|cant|p1a: Indeedee|par|Follow Me",
        1,
    )

    trajectory = _extract(log)
    decision = trajectory["decisions"][0]
    p1 = decision["joint_actions"]["p1"]

    assert not p1["identity_complete"]
    assert decision["complete_label_sides"] == ["p2"]
    assert p1["missing"] == [
        {
            "slot": 1,
            "reasons": ["selected-action-prevented-or-unobservable"],
        }
    ]


def test_public_snapshot_cannot_contain_move_revealed_later_in_same_turn():
    trajectory = _extract()
    turn1 = trajectory["decisions"][0]["public_state"]
    turn2 = trajectory["decisions"][1]["public_state"]

    assert _revealed(turn1, "p2", "Archaludon")["moves"] == []
    assert _revealed(turn2, "p2", "Archaludon")["moves"] == ["dragonpulse"]
    assert turn1["source_prefix"]["sha256"] != turn2["source_prefix"]["sha256"]


def _install_raw_replay(
    data_root: Path,
    *,
    replay_id: str,
    detail: dict,
) -> Path:
    layout = initialize_layout(data_root)
    raw = json.dumps(detail, separators=(",", ":")).encode("utf-8")
    raw_path = layout.raw / DEFAULT_FORMAT / f"{replay_id}.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()

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
            INSERT INTO replays VALUES (?, ?, 100, 1500, ?, ?, ?, ?, '{}', '{}', 'now')
            """,
            (
                replay_id,
                DEFAULT_FORMAT,
                json.dumps(["Alice", "Bob"]),
                raw_path.relative_to(layout.root).as_posix(),
                digest,
                len(raw),
            ),
        )
        connection.commit()
    return raw_path


def test_corpus_extraction_is_incremental_and_preserves_game_boundary(tmp_path: Path):
    data_root = tmp_path / "external"
    replay_id = f"{DEFAULT_FORMAT}-200"
    _install_raw_replay(data_root, replay_id=replay_id, detail=_detail(replay_id))

    first = extract_trajectory_corpus(
        config=TrajectoryConfig(
            data_root=data_root,
            max_replays=1,
            strict=True,
        )
    )
    second = extract_trajectory_corpus(
        config=TrajectoryConfig(
            data_root=data_root,
            max_replays=1,
            strict=True,
        )
    )

    assert first.extracted == 1
    assert first.decision_boundaries == 2
    assert first.complete_joint_labels == 4
    assert second.extracted == 0
    assert second.already_current == 1

    output = (
        data_root
        / "trajectories"
        / DEFAULT_FORMAT
        / f"{replay_id}.json"
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["game_group"] == replay_id

    status = trajectory_status(data_root)
    assert status["replays"] == 1
    assert status["decision_boundaries"] == 2
    assert status["failures"] == 0


def test_raw_hash_mismatch_fails_closed(tmp_path: Path):
    data_root = tmp_path / "external"
    replay_id = f"{DEFAULT_FORMAT}-201"
    raw_path = _install_raw_replay(
        data_root,
        replay_id=replay_id,
        detail=_detail(replay_id),
    )
    raw_path.write_text("tampered", encoding="utf-8")

    with pytest.raises(TrajectoryExtractionError, match="hash mismatch"):
        extract_trajectory_corpus(
            config=TrajectoryConfig(
                data_root=data_root,
                max_replays=1,
                strict=True,
            )
        )
