"""Pinned-Showdown smoke for isolated public-prior rebase proposals.

A fresh Showdown root is a legitimate concrete opening hypothesis, but not a
midgame replacement. Both projections must agree and the method never grants
live admission authority. No private session snapshot is given to the generator.
"""

from __future__ import annotations

from champions_practice.belief_smoke import _public_priors
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.current_state_proposals import (
    RebaseProposalStatus,
    build_current_state_set_proposals,
    probe_fresh_prior_projections,
)
from champions_practice.midgame_reconstruction_smoke import (
    AI_PREVIEW,
    HUMAN_PREVIEW,
    SEED,
    TURN_ONE,
)
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM


def main() -> None:
    with ShowdownSearchWorker() as worker:
        trusted_opening = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=SMOKE_TEAM, p2_team=SMOKE_TEAM,
            p1_preview=HUMAN_PREVIEW, p2_preview=AI_PREVIEW,
            seed=SEED,
        )
        opening_view = worker.state_view(state=trusted_opening, side="p2")
        ledger = PublicConstraintLedger.from_public_view(opening_view)
        batch = build_current_state_set_proposals(
            ledger=ledger, current_view=opening_view,
            priors=_public_priors(), limit=8,
        )
        if not batch.proposals:
            raise SystemExit("ERROR: public priors produced no candidate hypotheses")
        probes = probe_fresh_prior_projections(
            worker, ledger=ledger, current_view=opening_view,
            proposals=batch, battle_format=CHAMPIONS_FORMAT,
            ai_team=SMOKE_TEAM, ai_preview_choice=AI_PREVIEW,
            seed=SEED, max_probes=3,
        )
        if not probes or any(item.live_admission_authorized for item in probes):
            raise SystemExit("ERROR: projection probe granted live authority")
        if any(
            item.status is RebaseProposalStatus.PROJECTION_MATCH
            and (not item.own_request_equal or not item.public_projection_equal)
            for item in probes
        ):
            raise SystemExit("ERROR: matched projection bypassed own-side request")
        if any(
            item.status is not RebaseProposalStatus.PROJECTION_MATCH
            and item.matching_opening_state is not None
            for item in probes
        ):
            raise SystemExit("ERROR: mismatched candidate retained concrete state")

        transition = worker.branch_many(
            state=trusted_opening,
            branches=[{
                "p1_choice": TURN_ONE.p1_choice,
                "p2_choice": TURN_ONE.p2_choice,
                "rng_seed": SEED,
                "include_state": True,
                "view_side": "p2",
            }],
        )[0]
        current_view = transition["view"]
        later = ledger.advance(current_view)
        current_batch = build_current_state_set_proposals(
            ledger=later, current_view=current_view,
            priors=_public_priors(), limit=8,
        )
        if not current_batch.proposals:
            raise SystemExit("ERROR: later public constraints lost every prior")
        later_probes = probe_fresh_prior_projections(
            worker, ledger=later, current_view=current_view,
            proposals=current_batch, battle_format=CHAMPIONS_FORMAT,
            ai_team=SMOKE_TEAM, ai_preview_choice=AI_PREVIEW,
            seed=SEED, max_probes=1,
        )
        if any(
            item.status is not RebaseProposalStatus.NOT_CURRENT_STATE
            or item.matching_opening_state is not None
            or item.live_admission_authorized
            for item in later_probes
        ):
            raise SystemExit(
                "ERROR: fresh opening was misrepresented as current midgame state"
            )

    print("RESULT: pinned public-prior candidate generation and dual projection gate passed")
    print(f"Opening static hypotheses: {len(batch.proposals)}")
    print(f"Opening concrete probes: {len(probes)}")
    print(f"Midgame static hypotheses: {len(current_batch.proposals)}")
    print("Boundary: no fresh root is admitted as a later-turn belief")


if __name__ == "__main__":
    main()
