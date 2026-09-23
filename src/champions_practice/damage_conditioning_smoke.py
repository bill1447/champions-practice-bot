"""Production-like damaging-turn smoke for adaptive RNG conditioning."""

from champions_practice.belief_controller import BeliefBattleController, BeliefDecision
from champions_practice.belief_smoke import _public_priors
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM

LIVE_SEED = "sodium,87654321000000020000000300000004"
HUMAN_PREVIEW = "team 1256"
AI_PREVIEW = "team 4512"
HUMAN_TURN_ONE = "move psychic +1, move protect"
AI_TURN_ONE = "move wideguard, move protect"


def main() -> None:
    with ShowdownSearchWorker() as worker:
        controller = BeliefBattleController(
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
            controller.start(
                opponent_team=SMOKE_TEAM,
                p1_name="Human",
                p2_name="Belief AI",
                session_seed=LIVE_SEED,
            )
            controller.submit_preview(
                human_choice=HUMAN_PREVIEW,
                ai_choice=AI_PREVIEW,
            )
            if not controller.particles:
                raise SystemExit("ERROR: damaging-turn smoke created no particles")

            if HUMAN_TURN_ONE not in controller.human_legal_choices():
                raise SystemExit("ERROR: controlled damaging human action is not legal")
            if AI_TURN_ONE not in controller.ai_legal_choices():
                raise SystemExit("ERROR: controlled AI action is not legal")

            forced = BeliefDecision(
                choice=AI_TURN_ONE,
                mode="controlled-smoke",
                particle_count=len(controller.particles),
                candidate_count=0,
                branch_count=0,
                elapsed_seconds=0.0,
            )
            update = controller.resolve_turn(
                human_choice=HUMAN_TURN_ONE,
                decision=forced,
            )

            if update.conditioning_over_budget:
                raise SystemExit("ERROR: damaging-turn conditioning exceeded 8 seconds")
            if update.degraded:
                raise SystemExit(
                    "ERROR: ordinary damage RNG left the controller degraded"
                )
            if update.matched_branches <= 0 or not controller.particles:
                raise SystemExit(
                    "ERROR: adaptive RNG conditioning retained no posterior particles"
                )
            if update.conditioning_seconds >= 8.0:
                raise SystemExit("ERROR: damaging-turn conditioning missed production budget")

            next_decision = controller.choose_ai_action()
            if next_decision.mode != "belief-search":
                raise SystemExit(
                    "ERROR: belief search did not resume after damaging turn: "
                    f"{next_decision.fallback_reason}"
                )
            if next_decision.choice not in controller.ai_legal_choices():
                raise SystemExit("ERROR: post-damage search choice is not live-legal")

            print("Production-like damaging-turn belief conditioning")
            print(f"Initial particles: {update.particles_before}")
            print(f"Branches generated: {update.generated_branches}")
            print(f"Matching branches: {update.matched_branches}")
            print(f"Posterior particles: {update.particles_after}")
            print(f"Conditioning time: {update.conditioning_seconds:.3f} seconds")
            print(f"Next belief-search choice: {next_decision.choice}")
            print(f"Next search time: {next_decision.elapsed_seconds:.3f} seconds")
            print("Production conditioning deadline: 8.0 seconds")
            print("RESULT: ordinary damage RNG survives and belief search resumes")
        finally:
            controller.close()


if __name__ == "__main__":
    main()
