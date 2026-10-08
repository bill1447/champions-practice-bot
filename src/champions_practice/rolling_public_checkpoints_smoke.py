"""Pinned-Showdown rolling public checkpoint smoke through two resolved turns.

The oracle is only a test fixture. The rolling API receives player-visible
observations, owned submitted actions, public priors, and first-turn independently
certified checkpoints. It never receives the hidden oracle's submitted
opponent command, exact state, session ID or RNG ancestry.
"""

from __future__ import annotations

from champions_practice.belief_smoke import _public_priors
from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.belief_worlds import preview_choice_for_world
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.current_state_proposals import build_current_state_set_proposals
from champions_practice.midgame_reconstruction_smoke import (
    AI_PREVIEW, SEED, HUMAN_PREVIEW, TURN_ONE, TURN_TWO,
)
from champions_practice.observation_beliefs import public_observation_signature
from champions_practice.public_scaffold_bootstrap import bootstrap_public_current_scaffolds
from champions_practice.rolling_public_checkpoints import (
    advance_rolling_public_checkpoints,
    validate_public_bootstrap_checkpoint,
)
from champions_practice.search_worker import HypotheticalSearchWorker
from champions_practice.teams import SMOKE_TEAM


def _mechanics(state: dict) -> dict:
    """Offline oracle comparison, entirely separate from projection acceptance."""
    return {key: value for key, value in state.items() if key != "log"}


def main() -> None:
    priors = _public_priors()
    with HypotheticalSearchWorker() as worker:
        initial = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=SMOKE_TEAM, p2_team=SMOKE_TEAM,
            p1_preview=HUMAN_PREVIEW, p2_preview=AI_PREVIEW,
            seed=SEED, p1_name="Human", p2_name="Practice AI",
        )
        public_preview = worker.state_view(state=initial, side="p2")
        preview_ledger = PublicConstraintLedger.from_public_view(public_preview)
        preview_batch = build_current_state_set_proposals(
            ledger=preview_ledger, current_view=public_preview,
            priors=priors, limit=32,
        )
        selected = next(
            (
                entry for entry in preview_batch.proposals
                if {"Metagross", "Armarouge", "Indeedee-F", "Sneasler"}.issubset(
                    entry.selected_species
                )
            ), None,
        )
        if selected is None:
            raise SystemExit("ERROR: no fitting public prior for rolling fixture")

        opponent_preview = preview_choice_for_world(
            build_public_opponent_belief(public_preview), selected.world,
        )
        oracle_root = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=selected.team_text, p2_team=SMOKE_TEAM,
            p1_preview=opponent_preview, p2_preview=AI_PREVIEW,
            seed=SEED, p1_name="Human", p2_name="Practice AI",
        )
        previews = {
            "p1": list(public_preview["opponent"]["preview_species"]),
            "p2": [member["species"] for member in public_preview["player"]["team"]],
        }
        opening = worker.state_view(
            state=oracle_root, side="p2", previews=previews,
        )
        oracle_one = worker.branch_many(
            state=oracle_root, branches=[{
                "p1_choice": TURN_ONE.p1_choice,
                "p2_choice": TURN_ONE.p2_choice,
                "rng_seed": SEED,
                "include_state": True,
                "view_side": "p2",
                "previews": previews,
            }],
        )[0]
        first = oracle_one["view"]
        one_ledger = PublicConstraintLedger.from_public_view(opening).advance(first)
        one_batch = build_current_state_set_proposals(
            ledger=one_ledger, current_view=first, priors=priors, limit=32,
        )
        same_prior = next(
            (entry for entry in one_batch.proposals
             if entry.team_text == selected.team_text), None,
        )
        if same_prior is None:
            raise SystemExit("ERROR: first-turn approved set prior unavailable")
        one_report = bootstrap_public_current_scaffolds(
            worker,
            opening_view=opening, current_view=first,
            ledger=one_ledger,
            prior_batch=one_batch.__class__(
                proposals=(same_prior,),
                source_turn=one_batch.source_turn,
                source_signature=one_batch.source_signature,
                candidates_considered=one_batch.candidates_considered,
                rejected_missing_public_moves=one_batch.rejected_missing_public_moves,
                missing_prior=one_batch.missing_prior,
            ),
            battle_format=CHAMPIONS_FORMAT, ai_team=SMOKE_TEAM,
            ai_preview_choice=AI_PREVIEW,
            known_own_choice=TURN_ONE.p2_choice,
            rng_seeds=(SEED,), max_roots=1, max_branches=32,
            max_witnesses=8,
        )
        if not one_report.witnesses:
            raise SystemExit("ERROR: public-only first checkpoint bootstrap failed")

        certified = tuple(
            checkpoint for witness in one_report.witnesses
            if (checkpoint := validate_public_bootstrap_checkpoint(
                worker, witness=witness, ledger=one_ledger,
                current_view=first, prior_batch=one_batch,
            )) is not None
        )
        if not certified:
            raise SystemExit("ERROR: no public-validated first-turn checkpoint")

        # Independent offline truth: the constructor below is never given
        # TURN_TWO.p1_choice, the oracle state, or a true-world selection.
        oracle_two = worker.branch_many(
            state=oracle_one["state"],
            branches=[{
                "p1_choice": TURN_TWO.p1_choice,
                "p2_choice": TURN_TWO.p2_choice,
                "rng_seed": SEED,
                "include_state": True,
                "view_side": "p2",
                "previews": previews,
            }],
        )[0]
        current = oracle_two["view"]
        two_ledger = one_ledger.advance(current)
        two_batch = build_current_state_set_proposals(
            ledger=two_ledger, current_view=current,
            priors=priors, limit=32,
        )
        report = advance_rolling_public_checkpoints(
            worker,
            previous_view=first, current_view=current,
            previous_ledger=one_ledger, current_ledger=two_ledger,
            previous_prior_batch=one_batch, prior_batch=two_batch,
            checkpoints=certified,
            known_own_choice=TURN_TWO.p2_choice,
            rng_seeds=(SEED,),
            max_checkpoints=8,
            max_opponent_choices=16,
            max_branches=96,
            max_witnesses=8,
        )
        if not report.checkpoints:
            raise SystemExit(
                "ERROR: public-only rolling step found no turn-three scaffold: "
                f"{report.unresolved_reason}; parent={report.validated_parents}, "
                f"branches={report.simulated_branches}"
            )
        if not any(_mechanics(c.state) == _mechanics(oracle_two["state"])
                   for c in report.checkpoints):
            raise SystemExit("ERROR: independently verified true-world mechanics state lost")

        for candidate in report.checkpoints:
            if candidate.live_admission_authorized:
                raise SystemExit("ERROR: rolling checkpoint acquired live authority")
            projected = worker.state_view(
                state=candidate.state, side="p2", previews=previews,
            )
            if projected["request"] != current["request"]:
                raise SystemExit("ERROR: rolling checkpoint changed choosing-side request")
            if public_observation_signature(projected) != two_ledger.current_signature:
                raise SystemExit("ERROR: rolling checkpoint changed public projection")
        if report.exhaustive_disproofs or report.live_admission_authorized:
            raise SystemExit("ERROR: positive-only bootstrap claimed negative authority")

    print("RESULT: two-turn public checkpoint rolling bootstrap passed")
    print(f"First-turn public witnesses: {len(one_report.witnesses)}")
    print(f"Certified first-turn checkpoints: {len(certified)}")
    print(f"Second-step Showdown branches: {report.simulated_branches}")
    print(f"Current-turn public-compatible checkpoints: {len(report.checkpoints)}")
    print("Offline true-world survival: YES (independent native-state comparison)")
    print("No old particles, sealed human command or oracle state supplied")
    print("Scope: one-step checkpoint rolling; arbitrary collapse without checkpoint unresolved")
    print("Authority: no live admission or hidden-world disproof")


if __name__ == "__main__":
    main()
