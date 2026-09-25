"""Production-like damaging-turn smoke for adaptive RNG conditioning."""

from champions_practice.belief_controller import (
    BeliefDecision,
    _BeliefBattleCoordinator,
)
from champions_practice.belief_smoke import _public_priors
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM

LIVE_SEED = "sodium,87654321000000020000000300000004"
HUMAN_PREVIEW = "team 1256"
AI_PREVIEW = "team 4512"
HUMAN_TURN_ONE = "move psychic +1, move protect"
AI_TURN_ONE = "move expandingforce +1, move protect"


def main() -> None:
    with ShowdownSearchWorker() as worker:
        coordinator = _BeliefBattleCoordinator(
            worker,
            battle_format=CHAMPIONS_FORMAT,
            ai_team=SMOKE_TEAM,
            opponent_priors=_public_priors(),
            world_limit=8,
            particles_per_world=1,
            max_particles=8,
            candidate_limit=4,
            response_limit=4,
            decision_budget_seconds=8.0,
            conditioning_budget_seconds=8.0,
            particle_seed=5501,
        )
        try:
            coordinator.start(
                opponent_team=SMOKE_TEAM,
                p1_name="Human",
                p2_name="Belief AI",
                session_seed=LIVE_SEED,
            )
            coordinator.submit_preview(
                human_choice=HUMAN_PREVIEW,
                ai_choice=AI_PREVIEW,
            )
            before = coordinator._engine.last_public_view
            if not isinstance(before, dict):
                raise SystemExit("ERROR: damaging-turn smoke has no preview view")
            if not coordinator._engine.particles:
                raise SystemExit("ERROR: damaging-turn smoke created no particles")

            if HUMAN_TURN_ONE not in coordinator.human_legal_choices():
                raise SystemExit("ERROR: controlled damaging human action is not legal")
            ai_legal = coordinator._ai_legal_choices()
            if AI_TURN_ONE not in ai_legal:
                raise SystemExit("ERROR: controlled AI action is not legal")

            forced = BeliefDecision(
                choice=AI_TURN_ONE,
                mode="controlled-smoke",
                particle_count=len(coordinator._engine.particles),
                candidate_count=0,
                branch_count=0,
                elapsed_seconds=0.0,
            )
            original_choose = coordinator._engine.choose_ai_action
            coordinator._engine.choose_ai_action = (
                lambda *, legal_live: forced
            )
            try:
                ready = coordinator.lock_ai_action()
            finally:
                coordinator._engine.choose_ai_action = original_choose

            update = coordinator.commit_human_action(
                token=ready.token,
                human_choice=HUMAN_TURN_ONE,
            )
            after = coordinator._engine.last_public_view
            if not isinstance(after, dict):
                raise SystemExit("ERROR: damaging turn produced no AI public view")

            actions = after.get("opponent_last_actions")
            if not isinstance(actions, list):
                raise SystemExit("ERROR: public opponent actions are missing")
            action_by_slot = {
                action.get("slot"): action
                for action in actions
                if isinstance(action, dict)
            }
            psychic = action_by_slot.get(1)
            protect = action_by_slot.get(2)
            if (
                psychic is None
                or psychic.get("move") != "psychic"
                or psychic.get("target") != 1
                or protect is None
                or protect.get("move") != "protect"
            ):
                raise SystemExit(
                    "ERROR: public action extraction did not recover the human choice: "
                    f"{actions!r}"
                )

            before_our = {
                pokemon["species"]: pokemon["hp_percent"]
                for pokemon in before["player"]["active_details"]
                if isinstance(pokemon, dict)
            }
            after_our = {
                pokemon["species"]: pokemon["hp_percent"]
                for pokemon in after["player"]["active_details"]
                if isinstance(pokemon, dict)
            }
            before_their = {
                pokemon["base_species"]: pokemon["hp_percent"]
                for pokemon in before["opponent"]["active"]
                if isinstance(pokemon, dict)
            }
            after_their = {
                pokemon["base_species"]: pokemon["hp_percent"]
                for pokemon in after["opponent"]["active"]
                if isinstance(pokemon, dict)
            }
            our_damage = any(
                after_our.get(species, hp) < hp
                for species, hp in before_our.items()
            )
            their_damage = any(
                after_their.get(species, hp) < hp
                for species, hp in before_their.items()
            )
            if not our_damage or not their_damage:
                raise SystemExit(
                    "ERROR: damaging-turn smoke did not produce public damage on both sides"
                )
            if update.generated_branches > 768:
                raise SystemExit(
                    "ERROR: observed-action conditioning exceeded bounded branch budget: "
                    f"{update.generated_branches}"
                )

            if update.conditioning_over_budget:
                raise SystemExit("ERROR: damaging-turn conditioning exceeded 8 seconds")
            if update.degraded:
                raise SystemExit(
                    "ERROR: ordinary damage RNG left the coordinator degraded"
                )
            if update.matched_branches <= 0 or not coordinator._engine.particles:
                raise SystemExit(
                    "ERROR: adaptive RNG conditioning retained no posterior particles"
                )
            if update.conditioning_seconds >= 8.0:
                raise SystemExit("ERROR: damaging-turn conditioning missed production budget")

            next_legal = coordinator._ai_legal_choices()
            next_decision = coordinator._engine.choose_ai_action(
                legal_live=next_legal,
            )
            if next_decision.mode != "belief-search":
                raise SystemExit(
                    "ERROR: belief search did not resume after damaging turn: "
                    f"{next_decision.fallback_reason}"
                )
            if next_decision.choice not in next_legal:
                raise SystemExit("ERROR: post-damage search choice is not live-legal")

            print("Production-like two-damage-turn belief conditioning")
            print(f"Initial particles: {update.particles_before}")
            print(f"Observed opponent actions: {actions}")
            print(f"Branches generated: {update.generated_branches}")
            print(f"Matching branches: {update.matched_branches}")
            print(f"Posterior particles: {update.particles_after}")
            print(f"Conditioning time: {update.conditioning_seconds:.3f} seconds")
            print(f"Next belief-search choice: {next_decision.choice}")
            print(f"Next search time: {next_decision.elapsed_seconds:.3f} seconds")
            print("Production conditioning deadline: 8.0 seconds")
            print("RESULT: two-sided damage RNG survives and belief search resumes")
        finally:
            coordinator.close()


if __name__ == "__main__":
    main()
