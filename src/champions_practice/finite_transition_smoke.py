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


P1_PREVIEW = "team 5132"
P2_PREVIEW = "team 5132"
PREP_CHOICE = "move protect, move followme"
P1_CHOICE = "move protect, move followme"
P2_CHOICE = "move protect, move followme"
RNG_SEED = "sodium,0123456789abcdef0123456789abcdef"
# Avoid mirror speed ties in this isolated transition smoke. The production
# regression below keeps the exact mirror fixture; this one is deliberately
# small enough that exhaustive negative coverage can complete in CI.
P1_TEAM = (
    SMOKE_TEAM
    .replace(
        "EVs: 32 HP / 32 Def / 2 Spe",
        "EVs: 32 HP / 1 Atk / 32 Def / 1 Spe",
        1,
    )
    .replace(
        "EVs: 2 HP / 32 Atk / 32 Spe",
        "EVs: 2 HP / 32 Atk / 2 Def / 30 Spe",
        1,
    )
    .replace(
        "EVs: 32 HP / 2 Atk / 32 SpD",
        "EVs: 32 HP / 2 Atk / 31 SpD / 1 Spe",
        1,
    )
)

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
        initial_state = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=P1_TEAM,
            p2_team=SMOKE_TEAM,
            p1_preview=P1_PREVIEW,
            p2_preview=P2_PREVIEW,
            seed="sodium,11111111222222223333333344444444",
        )

        # Build a compact stochastic transition deliberately: the first turn
        # establishes a successful Protect chain, then the measured turn repeats
        # Protect. That exercises Showdown randomChance without the enormous
        # accuracy/crit/damage Cartesian product of an ordinary damaging move.
        prepared = worker.branch_many(
            state=initial_state,
            branches=[
                {
                    "p1_choice": PREP_CHOICE,
                    "p2_choice": PREP_CHOICE,
                    "include_state": True,
                    "view_side": "p2",
                    "rng_seed": "sodium,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "previews": PREVIEWS,
                }
            ],
        )[0]
        state = prepared["state"]

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

        # Force the same finite tree through tiny positive-only chunks.
        # The first chunk must return an opaque frontier; later chunks may
        # witness the known public outcome but can never gain negative authority.
        resumed = finite_public_transition_reachability(
            worker,
            state=state,
            side="p2",
            p1_choice=P1_CHOICE,
            p2_choice=P2_CHOICE,
            expected_public_view=expected,
            previews=PREVIEWS,
            max_leaves=1,
        )
        if resumed.continuation_token is None:
            raise SystemExit(
                "ERROR: bounded finite transition did not return a resumable frontier"
            )
        continuation = resumed.continuation_token
        resumed_witness = None
        for _ in range(32):
            resumed = finite_public_transition_reachability(
                worker,
                state=state,
                side="p2",
                p1_choice=P1_CHOICE,
                p2_choice=P2_CHOICE,
                expected_public_view=expected,
                previews=PREVIEWS,
                max_leaves=1,
                continuation_token=continuation,
            )
            if resumed.evidence.status is ReachabilityStatus.WITNESSED:
                resumed_witness = resumed
                break
            if resumed.evidence.establishes_impossibility:
                raise SystemExit(
                    "ERROR: resumed finite frontier gained negative authority"
                )
            continuation = resumed.continuation_token
            if continuation is None:
                break
        if resumed_witness is None:
            raise SystemExit(
                "ERROR: resumed finite frontier did not recover known outcome"
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
        print("Stochastic fixture: repeated Protect randomChance")
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
