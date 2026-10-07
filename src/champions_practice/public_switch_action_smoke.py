"""Pinned-Showdown smoke for public selected-switch command evidence."""

from __future__ import annotations

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import (
    filter_choices_by_public_actions,
    observed_public_actions,
    public_opponent_actions_fully_observed,
)
from champions_practice.search_worker import HypotheticalSearchWorker
from champions_practice.teams import SMOKE_TEAM


PREVIEW = "team 2135"
PREVIEWS = {
    "p1": [
        "Indeedee-F",
        "Sneasler",
        "Gardevoir",
        "Armarouge",
        "Rillaboom",
        "Metagross",
    ],
    "p2": [
        "Indeedee-F",
        "Sneasler",
        "Gardevoir",
        "Armarouge",
        "Rillaboom",
        "Metagross",
    ],
}


def _mixed_switch_choice(choices: tuple[str, ...]) -> str:
    for choice in choices:
        commands = [part.strip() for part in choice.split(",")]
        if (
            len(commands) == 2
            and any(command.startswith("switch ") for command in commands)
            and any(command.startswith("move protect") for command in commands)
        ):
            return choice
    raise SystemExit("ERROR: no mixed Protect + selected-switch command is legal")


def main() -> None:
    with HypotheticalSearchWorker() as worker:
        state = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=SMOKE_TEAM,
            p2_team=SMOKE_TEAM,
            p1_preview=PREVIEW,
            p2_preview=PREVIEW,
            seed="sodium,16616616616616616616616616616616",
        )
        before = worker.state_view(
            state=state,
            side="p2",
            previews=PREVIEWS,
        )
        p1_legal = tuple(worker.legal_choices(state=state, side="p1"))
        p2_legal = tuple(worker.legal_choices(state=state, side="p2"))
        p1_choice = _mixed_switch_choice(p1_legal)
        p2_choice = next(
            (
                choice
                for choice in p2_legal
                if choice == "move protect, move protect"
            ),
            p2_legal[0],
        )

        result = worker.branch_many(
            state=state,
            branches=[
                {
                    "p1_choice": p1_choice,
                    "p2_choice": p2_choice,
                    "include_state": True,
                    "view_side": "p2",
                    "rng_seed": "sodium,0123456789abcdef0123456789abcdef",
                    "previews": PREVIEWS,
                }
            ],
        )[0]
        view = result["view"]
        actions = observed_public_actions(
            view,
            previous_public_view=before,
        )

        switch_actions = [
            action for action in actions if action[1] == "switch"
        ]
        move_actions = [
            action for action in actions if action[1] == "move"
        ]
        if len(switch_actions) != 1 or len(move_actions) != 1:
            raise SystemExit(
                "ERROR: selected switch + move did not produce complete public "
                f"semantic command evidence: {actions!r}"
            )
        if not public_opponent_actions_fully_observed(
            view,
            previous_public_view=before,
        ):
            raise SystemExit(
                "ERROR: mixed selected switch + move was not recognized as a "
                "complete public joint action"
            )

        resolved = filter_choices_by_public_actions(
            p1_legal,
            view,
            previous_public_view=before,
            state=state,
            side="p1",
            fail_open=False,
        )
        if p1_choice not in resolved:
            raise SystemExit(
                "ERROR: public switch species did not resolve back to the exact "
                f"Showdown command: expected {p1_choice!r}, got {resolved!r}"
            )
        if not resolved:
            raise SystemExit("ERROR: public switch evidence resolved no legal commands")

        print("Public selected-switch command evidence")
        print(f"Submitted p1 command: {p1_choice}")
        print(f"Observed semantic actions: {actions}")
        print(f"Resolved exact commands: {resolved}")
        print(
            "RESULT: a pre-resolution public switch is reconstructed by species "
            "and resolved to particle-local Showdown switch indexes"
        )


if __name__ == "__main__":
    main()
