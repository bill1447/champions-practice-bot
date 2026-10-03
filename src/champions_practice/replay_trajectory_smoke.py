"""Tiny deterministic replay-trajectory corpus smoke for CI."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

from champions_practice.replay_corpus import DEFAULT_FORMAT, initialize_layout
from champions_practice.replay_trajectories import (
    TrajectoryConfig,
    extract_trajectory_corpus,
    trajectory_status,
)


def _log() -> str:
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
            "|turn|1",
            "|move|p1a: Indeedee|Follow Me|p1a: Indeedee",
            "|move|p2a: Pelipper|Protect|p2a: Pelipper",
            "|move|p1b: Sneasler|Close Combat|p2b: Archaludon",
            "|move|p2b: Archaludon|Dragon Pulse|p1b: Sneasler",
            "|upkeep",
            "|turn|2",
            "|switch|p1a: Rillaboom|Rillaboom, L50, M|100/100",
            "|move|p2a: Pelipper|Protect|p2a: Pelipper",
            "|move|p1b: Sneasler|Dire Claw|p2b: Archaludon",
            "|move|p2b: Archaludon|Dragon Pulse|p1b: Sneasler",
            "|win|Alice",
        ]
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="champions-replay-trajectory-") as temp:
        root = Path(temp)
        replay_id = f"{DEFAULT_FORMAT}-fixture"
        detail = {
            "id": replay_id,
            "players": ["Alice", "Bob"],
            "rating": 1500,
            "uploadtime": 100,
            "log": _log(),
            "inputlog": ">p1 move 4 2, move 3 1",
        }
        raw = json.dumps(detail, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()

        layout = initialize_layout(root)
        raw_path = layout.raw / DEFAULT_FORMAT / f"{replay_id}.json"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw)

        with sqlite3.connect(layout.database) as connection:
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
                INSERT INTO replays VALUES (
                    ?, ?, 100, 1500, ?, ?, ?, ?, '{}', '{}', 'now'
                )
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

        stats = extract_trajectory_corpus(
            config=TrajectoryConfig(
                data_root=root,
                max_replays=1,
                strict=True,
            )
        )
        status = trajectory_status(root)

        if stats.extracted != 1 or stats.decision_boundaries != 2:
            raise SystemExit("ERROR: replay trajectory smoke did not extract two turns")
        if stats.complete_joint_labels != 4:
            raise SystemExit(
                "ERROR: replay trajectory smoke lost an observable joint-action label"
            )
        if stats.incomplete_joint_labels != 0:
            raise SystemExit(
                "ERROR: replay trajectory smoke unexpectedly produced incomplete labels"
            )
        if status["replays"] != 1 or status["failures"] != 0:
            raise SystemExit("ERROR: replay trajectory manifest/status mismatch")

        output = (
            root
            / "trajectories"
            / DEFAULT_FORMAT
            / f"{replay_id}.json"
        )
        payload = json.loads(output.read_text(encoding="utf-8"))
        if payload["source"]["inputlog_used"]:
            raise SystemExit("ERROR: replay trajectory extractor consumed inputlog")
        if payload["decisions"][1]["joint_actions"]["p1"]["actions"][0][
            "kind"
        ] != "switch":
            raise SystemExit("ERROR: replay trajectory smoke lost move/switch joint")

        print("PASS: deterministic public replay trajectory extraction")
        print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
