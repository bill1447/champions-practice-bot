"""Pinned-runtime first current-turn scaffold bootstrap with no old particles.

Construct an offline oracle battle solely for test verification. The bootstrap
receives *only* its player-visible opening and next-turn views, the #182 public
ledger, #183 priors, own known action, and explicit hypothetical RNG seeds.
No oracle state, human submitted command, hidden team, or session ID is passed
into the bootstrap. True-world survival is measured out of band.
"""

from __future__ import annotations

from dataclasses import replace

from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.belief_worlds import preview_choice_for_world
from champions_practice.belief_smoke import _public_priors
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.current_state_proposals import build_current_state_set_proposals
from champions_practice.midgame_reconstruction_smoke import (
    AI_PREVIEW, SEED, HUMAN_PREVIEW, TURN_ONE,
)
from champions_practice.observation_beliefs import public_observation_signature
from champions_practice.public_scaffold_bootstrap import bootstrap_public_current_scaffolds
from champions_practice.search_worker import HypotheticalSearchWorker
from champions_practice.teams import SMOKE_TEAM


def mechanics(state):
    """Compare actual pinned mechanical state separately from acceptance logic."""
    return {
        key: value for key, value in state.items()
        if key not in {"log"}
    }


def main() -> None:
    with HypotheticalSearchWorker() as worker:
        baseline = worker.create_state(
            battle_format=CHAMPIONS_FORMAT, p1_team=SMOKE_TEAM, p2_team=SMOKE_TEAM,
            p1_preview=HUMAN_PREVIEW, p2_preview=AI_PREVIEW, seed=SEED,
            p1_name="Human", p2_name="Practice AI",
        )
        baseline_public = worker.state_view(state=baseline, side="p2")
        base_ledger = PublicConstraintLedger.from_public_view(baseline_public)
        opening_batch = build_current_state_set_proposals(
            ledger=base_ledger, current_view=baseline_public,
            priors=_public_priors(), limit=32,
        )
        selected = next((
            entry for entry in opening_batch.proposals
            if {"Metagross", "Armarouge", "Indeedee-F", "Sneasler"}.issubset(
                entry.selected_species
            )
        ), None)
        if selected is None:
            raise SystemExit("ERROR: no fitting prior selected for first-scaffold fixture")

        original_preview = preview_choice_for_world(
            build_public_opponent_belief(baseline_public), selected.world
        )
        oracle_root = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=selected.team_text, p2_team=SMOKE_TEAM,
            p1_preview=original_preview, p2_preview=AI_PREVIEW,
            seed=SEED, p1_name="Human", p2_name="Practice AI",
        )
        previews = {
            "p1": list(baseline_public["opponent"]["preview_species"]),
            "p2": [mon["species"] for mon in baseline_public["player"]["team"]],
        }
        opening = worker.state_view(state=oracle_root, side="p2", previews=previews)
        if TURN_ONE.p1_choice not in worker.legal_choices(state=oracle_root, side="p1"):
            raise SystemExit("ERROR: oracle turn-one opponent action not legal")
        if TURN_ONE.p2_choice not in worker.legal_choices(state=oracle_root, side="p2"):
            raise SystemExit("ERROR: oracle turn-one own action not legal")
        oracle = worker.branch_many(
            state=oracle_root,
            branches=[{
                "p1_choice": TURN_ONE.p1_choice,
                "p2_choice": TURN_ONE.p2_choice,
                "rng_seed": SEED,
                "include_state": True,
                "view_side": "p2",
                "previews": previews,
            }],
        )[0]
        current = oracle["view"]
        ledger = PublicConstraintLedger.from_public_view(opening).advance(current)
        all_proposals = build_current_state_set_proposals(
            ledger=ledger, current_view=current,
            priors=_public_priors(), limit=32,
        )
        matching = next((
            entry for entry in all_proposals.proposals
            if entry.team_text == selected.team_text
        ), None)
        if matching is None:
            raise SystemExit("ERROR: public-prior proposal lost fixture's static set")

        # A single explicit public prior is enough to verify the first-world
        # construction; no historical posterior, oracle command or oracle state
        # is passed to the function being tested.
        candidate_pool = replace(all_proposals, proposals=(matching,))
        report = bootstrap_public_current_scaffolds(
            worker, opening_view=opening, current_view=current,
            ledger=ledger, prior_batch=candidate_pool,
            battle_format=CHAMPIONS_FORMAT,
            ai_team=SMOKE_TEAM, ai_preview_choice=AI_PREVIEW,
            known_own_choice=TURN_ONE.p2_choice, rng_seeds=(SEED,),
            max_roots=1, max_branches=32, max_witnesses=4,
        )
        if not report.witnesses:
            raise SystemExit(
                "ERROR: public-only bootstrap did not construct a first current-turn scaffold: "
                f"{report.unsupported_reason}; roots={report.fresh_roots}, "
                f"branches={report.simulated_branches}"
            )
        if any(w.live_admission_authorized for w in report.witnesses):
            raise SystemExit("ERROR: scaffold incorrectly acquired live authority")
        if report.exhaustive_disproofs:
            raise SystemExit("ERROR: bounded witness search asserted hidden-world disproof")

        if not any(mechanics(w.state) == mechanics(oracle["state"])
                   for w in report.witnesses):
            raise SystemExit(
                "ERROR: public-only bootstrap failed offline true-world survival"
            )
        for witness in report.witnesses:
            projection = worker.state_view(
                state=witness.state, side="p2", previews=previews,
            )
            if projection["request"] != current["request"]:
                raise SystemExit("ERROR: scaffold changed own request")
            if public_observation_signature(projection) != ledger.current_signature:
                raise SystemExit("ERROR: scaffold disagreed with public observation")

    print("RESULT: generated initial current-turn scaffold from fresh public prior")
    print(f"Fresh pinned roots: {report.fresh_roots}")
    print(f"Bounded exact branches: {report.simulated_branches}")
    print(f"Public-compatible sequential witnesses: {len(report.witnesses)}")
    print("Offline true-world survival: YES (independent state comparison)")
    print("No particle ancestry or private human command passed to bootstrap")
    print("Scope: one fully observed turn; no midgame arbitrary-history support")
    print("Authority: zero live admissions or exhaustive exclusions")


if __name__ == "__main__":
    main()
