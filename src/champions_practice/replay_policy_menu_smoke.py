"""Pinned-Showdown integration smoke for replay legal-menu matching."""

from __future__ import annotations

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.replay_policy_dataset import (
    LEGAL_MENU_AUTHORITY,
    adapt_replay_decision_to_policy_example,
)
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM

SEED = "sodium,00000001000000020000000300000004"
PREVIEW = "team 2135"


def _move(slot: int, move: str) -> dict:
    return {
        "slot": slot,
        "kind": "move",
        "move": move,
        "move_name": move,
        "gimmicks": [],
        "resolved_target": None,
        "selected_target": None,
        "target_authority": "resolved-public-target-only",
        "authority": "top-level-public-move",
    }


def main() -> None:
    with ShowdownSearchWorker() as worker:
        started = worker.start_session(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=SMOKE_TEAM,
            p2_team=SMOKE_TEAM,
            p1_name="Replay P1",
            p2_name="Replay P2",
            seed=SEED,
        )
        session_id = started["session_id"]
        try:
            worker.choose_session(
                session_id,
                p1_choice=PREVIEW,
                p2_choice=PREVIEW,
            )
            menu = tuple(worker.session_legal_choices(session_id, side="p1"))
            view = worker.session_view(session_id, side="p1")["view"]
        finally:
            worker.close_session(session_id)

        party_species = tuple(
            pokemon["species"] for pokemon in view["player"]["team"]
        )
        decision = {
            "turn": 1,
            "public_state": {
                "schema": "showdown-replay-public-state-v1",
                "turn": 1,
            },
            "joint_actions": {
                "p1": {
                    "schema": "showdown-replay-joint-action-v1",
                    "side": "p1",
                    "identity_complete": True,
                    "exact_showdown_command_available": False,
                    "actions": [
                        _move(1, "Protect"),
                        _move(2, "Follow Me"),
                    ],
                    "missing": [],
                }
            },
        }
        example = adapt_replay_decision_to_policy_example(
            replay_id="integration-fixture",
            game_group="integration-fixture",
            decision=decision,
            side="p1",
            legal_choices=menu,
            party_species=party_species,
            menu_authority=LEGAL_MENU_AUTHORITY,
            showdown_revision=worker.showdown_revision,
        )

    if not menu:
        raise SystemExit("ERROR: pinned Showdown returned an empty turn-one menu")
    if not example["trainable"]:
        raise SystemExit(
            "ERROR: observable Protect + Follow Me joint did not map to the "
            "pinned-Showdown legal menu"
        )
    if example["label_choice"] not in menu:
        raise SystemExit("ERROR: adapter label is not an exact menu member")
    if example["label_choice"] != "move protect, move followme":
        raise SystemExit(
            "ERROR: unexpected exact menu label: "
            f"{example['label_choice']!r}"
        )
    if example["menu_provenance"]["showdown_revision"] != worker.showdown_revision:
        raise SystemExit("ERROR: policy example lost Showdown revision provenance")

    print("PASS: replay action identity maps to one exact pinned-Showdown menu entry")
    print(f"Legal choices: {len(menu)}")
    print(f"Label: {example['label_choice']}")


if __name__ == "__main__":
    main()
