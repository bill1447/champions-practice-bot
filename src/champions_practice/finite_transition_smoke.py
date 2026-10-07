"""Pinned-Showdown smoke for bounded finite stochastic transition reachability."""

from __future__ import annotations

import copy

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import public_observation_signature
from champions_practice.reachability import (
    ReachabilityStatus,
    finite_public_transition_reachability,
)
from champions_practice.search_worker import HypotheticalSearchWorker
from champions_practice.teams import SMOKE_TEAM


P1_PREVIEW = "team 2135"
P2_PREVIEW = "team 2135"
P1_CHOICE = "move protect, move trickroom"
P2_CHOICE = "move closecombat +2, move imprison"
RNG_SEED = "sodium,0123456789abcdef0123456789abcdef"
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


def main() -> None:
    with HypotheticalSearchWorker() as worker:
        state = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=SMOKE_TEAM,
            p2_team=SMOKE_TEAM,
            p1_preview=P1_PREVIEW,
            p2_preview=P2_PREVIEW,
            seed="sodium,11111111222222223333333344444444",
        )
        branch = worker.branch_many(
            state=state,
            branches=[
                {
                    "p1_choice": P1_CHOICE,
                    "p2_choice": P2_CHOICE,
                    "include_state": True,
                    "view_side": "p2",
                    "rng_seed": RNG_SEED,
                    "previews": PREVIEWS,
                }
            ],
        )[0]
        expected = branch["view"]

        witness = finite_public_transition_reachability(
            worker,
            state=state,
            side="p2",
            p1_choice=P1_CHOICE,
            p2_choice=P2_CHOICE,
            expected_public_view=expected,
            previews=PREVIEWS,
            max_leaves=4096,
        )
        if witness.evidence.status is not ReachabilityStatus.WITNESSED:
            raise SystemExit(
                "ERROR: finite transition enumeration did not recover a known "
                f"Showdown outcome: {witness.evidence}"
            )
        if witness.public_view is None:
            raise SystemExit("ERROR: finite transition witness omitted public view")
        if (
            public_observation_signature(witness.public_view)
            != public_observation_signature(expected)
        ):
            raise SystemExit(
                "ERROR: finite transition witness did not match target public view"
            )

        impossible = copy.deepcopy(expected)
        impossible["field"]["weather"] = "raindance"
        disproof = finite_public_transition_reachability(
            worker,
            state=state,
            side="p2",
            p1_choice=P1_CHOICE,
            p2_choice=P2_CHOICE,
            expected_public_view=impossible,
            previews=PREVIEWS,
            max_leaves=4096,
        )
        if disproof.evidence.status is not ReachabilityStatus.EXHAUSTIVELY_DISPROVED:
            raise SystemExit(
                "ERROR: finite transition enumeration did not exhaustively "
                f"disprove impossible weather: {disproof.evidence}"
            )
        if not disproof.evidence.establishes_impossibility:
            raise SystemExit("ERROR: exhaustive finite disproof lacks negative authority")

        print("Pinned Showdown finite stochastic transition reachability")
        print(f"Witness leaves examined: {witness.leaves_examined}")
        print(f"Witness random depth: {witness.max_depth}")
        print(f"Disproof leaves examined: {disproof.leaves_examined}")
        print(f"Disproof random depth: {disproof.max_depth}")
        print(
            "RESULT: finite random-call enumeration witnesses reachable outcomes "
            "and grants negative authority only after exhaustive completion"
        )


if __name__ == "__main__":
    main()
