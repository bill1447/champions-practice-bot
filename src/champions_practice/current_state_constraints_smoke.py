"""Real pinned-Showdown public-ledger smoke (no private battle snapshot input)."""

from __future__ import annotations

from copy import deepcopy

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.midgame_reconstruction_smoke import (
    AI_PREVIEW,
    HUMAN_PREVIEW,
    SEED,
    TURN_ONE,
)
from champions_practice.reachability import public_reachability_observation_issue
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM


def main() -> None:
    with ShowdownSearchWorker() as worker:
        state = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=SMOKE_TEAM,
            p2_team=SMOKE_TEAM,
            p1_preview=HUMAN_PREVIEW,
            p2_preview=AI_PREVIEW,
            seed=SEED,
        )
        opening = worker.state_view(state=state, side="p2")
        if public_reachability_observation_issue(opening) is not None:
            raise SystemExit("ERROR: real opening public view did not validate")
        ledger = PublicConstraintLedger.from_public_view(opening)

        advanced = worker.branch_many(
            state=state,
            branches=[{
                "p1_choice": TURN_ONE.p1_choice,
                "p2_choice": TURN_ONE.p2_choice,
                "rng_seed": SEED,
                "include_state": True,
                "view_side": "p2",
            }],
        )[0]["view"]
        if public_reachability_observation_issue(advanced) is not None:
            raise SystemExit("ERROR: real advanced public view did not validate")

        later = ledger.advance(advanced)
        if not later.matches_current_public_projection(advanced):
            raise SystemExit("ERROR: ledger lost exact current public projection")
        if len(later.records) < 2 or not any(
            item.kind == "public_event_delta" for item in later.records
        ):
            raise SystemExit("ERROR: ledger lost historical mechanics evidence")
        if later.advance(advanced).records != later.records:
            raise SystemExit("ERROR: unchanged latest public events were duplicated")

        leaked = deepcopy(advanced)
        leaked["opponent"]["hidden_item"] = "private-truth"
        try:
            later.advance(leaked)
        except ValueError:
            pass
        else:
            raise SystemExit("ERROR: private opponent information reached the ledger")

    print("RESULT: pinned public constraint ledger retains direct and historical facts")
    print("Boundary: ledger has zero live particle-admission or exclusion authority")


if __name__ == "__main__":
    main()
