"""Pinned-Showdown post-preview six-public-to-four-native prior gate.

Unlike older midgame smokes that defaulted previews to selected native members,
this fixture carries the FULL six-name public team preview while Showdown's
picked-four rule retains only four native side Pokemon. No hidden live battle
state or oracle information is used.
"""

from __future__ import annotations

from copy import deepcopy

from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.belief_worlds import preview_choice_for_world
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.current_state_proposals import build_current_state_set_proposals
from champions_practice.current_state_reconstruction import _matches_approved_prior
from champions_practice.demo_fixture import demo_public_priors
from champions_practice.search_worker import HypotheticalSearchWorker
from champions_practice.teams import SMOKE_TEAM


PREVIEW = (
    "Indeedee-F", "Sneasler", "Gardevoir",
    "Armarouge", "Rillaboom", "Metagross",
)
BROUGHT = {"Indeedee-F", "Sneasler", "Gardevoir", "Rillaboom"}
SEED = "sodium,00000001000000020000000300000004"


def main() -> None:
    with HypotheticalSearchWorker() as worker:
        native_opening = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=SMOKE_TEAM,
            p2_team=SMOKE_TEAM,
            p1_preview="team 2135",
            p2_preview="team 2135",
            seed=SEED,
        )
        previews = {"p1": list(PREVIEW), "p2": list(PREVIEW)}
        public_view = worker.state_view(
            state=native_opening, side="p2", previews=previews,
        )
        if tuple(public_view["opponent"]["preview_species"]) != PREVIEW:
            raise SystemExit("ERROR: pinned public preview was not six-name complete")

        ledger = PublicConstraintLedger.from_public_view(public_view)
        batch = build_current_state_set_proposals(
            ledger=ledger, current_view=public_view,
            priors=demo_public_priors(), limit=32,
        )
        proposal = next(
            (proposal for proposal in batch.proposals
             if set(proposal.selected_species) == BROUGHT),
            None,
        )
        if proposal is None:
            raise SystemExit("ERROR: selected four not represented in six-name prior")
        if len(proposal.world.sets) != 6:
            raise SystemExit("ERROR: public prior did not preserve six preview sets")

        preview_command = preview_choice_for_world(
            build_public_opponent_belief(public_view), proposal.world,
        )
        if preview_command != "team 2135":
            raise SystemExit(
                f"ERROR: unexpected publicly grounded preview: {preview_command}"
            )
        candidate = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=proposal.team_text,
            p2_team=SMOKE_TEAM,
            p1_preview=preview_command,
            p2_preview="team 2135",
            seed=SEED,
        )
        native_members = candidate["sides"][0]["pokemon"]
        if len(native_members) != 4:
            raise SystemExit(
                "ERROR: pinned Champions did not retain exactly four native members"
            )
        if not _matches_approved_prior(candidate, proposal):
            raise SystemExit(
                "ERROR: exact native picked four rejected against six public prior"
            )

        # Different bring-four from the *same* approved six sets must fail.
        other_selection = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=proposal.team_text,
            p2_team=SMOKE_TEAM,
            p1_preview="team 2146",
            p2_preview="team 2135",
            seed=SEED,
        )
        if _matches_approved_prior(other_selection, proposal):
            raise SystemExit("ERROR: unselected legal four impersonated approved four")

        # Also reject altered original-set attributes. This test changes a
        # copied native state ONLY; it does not fabricate a valid hypothesis.
        mutated = deepcopy(candidate)
        mutated["sides"][0]["pokemon"][0]["set"]["nature"] = "Hasty"
        if _matches_approved_prior(mutated, proposal):
            raise SystemExit("ERROR: altered native set passed exact prior identity")

        print("RESULT: pinned six-preview/four-selected set provenance passed")
        print(f"Public preview species: {len(proposal.world.sets)}")
        print(f"Native selected Pokemon: {len(native_members)}")
        print("Unselected legal subset admitted: NO")
        print("Altered approved set admitted: NO")


if __name__ == "__main__":
    main()
