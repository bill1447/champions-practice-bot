"""Real pinned Champions midgame HP-only re-materialization smoke for #184.

This smoke never passes a live session or private-truth snapshot to the
reconstruction API. The scaffold is created and advanced by the isolated
hypothetical worker, and is explicitly tied to its approved public team prior.
"""

from __future__ import annotations

from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.belief_worlds import preview_choice_for_world
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.current_state_proposals import build_current_state_set_proposals
from champions_practice.current_state_reconstruction import (
    CurrentTurnScaffold,
    _native_hp_only_change,
    reconstruct_current_hp_hypotheses,
)
from champions_practice.midgame_reconstruction_smoke import (
    AI_PREVIEW,
    HUMAN_PREVIEW,
    SEED,
    TURN_ONE,
)
from champions_practice.observation_beliefs import public_observation_signature
from champions_practice.search_worker import HypotheticalSearchWorker
from champions_practice.teams import SMOKE_TEAM
from champions_practice.belief_smoke import _public_priors


def main() -> None:
    priors = _public_priors()
    with HypotheticalSearchWorker() as worker:
        initial = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=SMOKE_TEAM,
            p2_team=SMOKE_TEAM,
            p1_preview=HUMAN_PREVIEW,
            p2_preview=AI_PREVIEW,
            seed=SEED,
        )
        opening = worker.state_view(state=initial, side="p2")
        opening_ledger = PublicConstraintLedger.from_public_view(opening)
        opening_batch = build_current_state_set_proposals(
            ledger=opening_ledger, current_view=opening, priors=priors, limit=32,
        )
        if not opening_batch.proposals:
            raise SystemExit("ERROR: no approved prior for native HP test")

        selected = next(
            (
                item for item in opening_batch.proposals
                if {"Metagross", "Armarouge"}.issubset(item.selected_species)
                and {"Indeedee-F", "Sneasler"}.issubset(item.selected_species)
            ), None
        )
        if selected is None:
            raise SystemExit("ERROR: expected four-member selected prior is missing")

        preview = preview_choice_for_world(
            build_public_opponent_belief(opening), selected.world
        )
        root = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=selected.team_text,
            p2_team=SMOKE_TEAM,
            p1_preview=preview,
            p2_preview=AI_PREVIEW,
            seed=SEED,
        )
        if TURN_ONE.p1_choice not in worker.legal_choices(state=root, side="p1"):
            raise SystemExit("ERROR: selected approved public prior cannot play test turn")
        if TURN_ONE.p2_choice not in worker.legal_choices(state=root, side="p2"):
            raise SystemExit("ERROR: AI cannot play fixed test turn")

        previews = {
            "p1": list(opening["opponent"]["preview_species"]),
            "p2": [mon["species"] for mon in opening["player"]["team"]],
        }

        # Search a small explicitly bounded set of hypothetical RNG branches
        # for a public HP bucket containing >=2 native exact integer HP values.
        # The state for each attempt is entirely Showdown-produced, not built
        # by the reconstruction module or a live private session.
        selected_report = None
        selected_source = None
        for index in range(1, 17):
            variant = worker.branch_many(
                state=root,
                branches=[{
                    "p1_choice": TURN_ONE.p1_choice,
                    "p2_choice": TURN_ONE.p2_choice,
                    "include_state": True,
                    "view_side": "p2",
                    "previews": previews,
                    "rng_seed": f"sodium,{index:08x}000000020000000300000004",
                }],
            )[0]
            current_view = variant["view"]
            ledger = PublicConstraintLedger.from_public_view(current_view)
            batch = build_current_state_set_proposals(
                ledger=ledger, current_view=current_view, priors=priors, limit=32,
            )
            same_prior = next(
                (
                    entry for entry in batch.proposals
                    if entry.team_text == selected.team_text
                ), None
            )
            if same_prior is None:
                continue
            parent = variant["state"]
            report = reconstruct_current_hp_hypotheses(
                worker,
                ledger=ledger,
                current_view=current_view,
                prior_batch=batch,
                scaffolds=(CurrentTurnScaffold(same_prior.proposal_id, parent),),
                max_hypotheses_per_scaffold=4,
            )
            if report.candidates:
                selected_report = report
                selected_source = parent
                for candidate in report.candidates:
                    assert not candidate.live_admission_authorized
                    assert candidate.exact_request_equal
                    assert candidate.public_projection_equal
                    assert candidate.native_state_delta_hp_only
                    assert _native_hp_only_change(parent, candidate.state)
                    projection = worker.state_view(
                        state=candidate.state,
                        side="p2",
                        previews={
                            "p1": list(ledger.preview_species),
                            "p2": [mon["species"] for mon in current_view["player"]["team"]],
                        },
                    )
                    assert public_observation_signature(projection) == ledger.current_signature
                break

        if selected_report is None or selected_source is None:
            raise SystemExit(
                "ERROR: bounded pinned Showdown fixture found no HP interval variant"
            )
        if selected_report.live_admission_authorized:
            raise SystemExit("ERROR: HP reconstruction incorrectly claimed live authority")
        print("RESULT: pinned Showdown midgame native HP reconstruction passed")
        print(f"Exact-HP hypotheses: {len(selected_report.candidates)}")
        print("Mechanical change boundary: one opponent Pokemon.hp only")
        print("Authority boundary: no live admission or historical disproof")


if __name__ == "__main__":
    main()
