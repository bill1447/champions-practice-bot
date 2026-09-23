"""Real-session smoke for the persistent public-belief battle controller."""

from champions_practice.belief_controller import BeliefBattleController
from champions_practice.belief_smoke import _public_priors
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM

LIVE_SEED = "sodium,12345678000000020000000300000004"
HUMAN_PREVIEW = "team 2615"
AI_PREVIEW = "team 4512"
HUMAN_TURN_ONE = "move protect, move protect"


def main() -> None:
    with ShowdownSearchWorker() as worker:
        controller = BeliefBattleController(
            worker,
            battle_format=CHAMPIONS_FORMAT,
            ai_team=SMOKE_TEAM,
            opponent_priors=_public_priors(),
            world_limit=2,
            particles_per_world=1,
            max_particles=2,
            candidate_limit=2,
            response_limit=2,
            decision_budget_seconds=60.0,
            conditioning_budget_seconds=60.0,
            particle_seed=5301,
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
                raise SystemExit("ERROR: controller created no public-belief particles")

            decision = controller.choose_ai_action()
            if decision.mode != "belief-search":
                raise SystemExit(
                    "ERROR: first live decision did not come from belief search: "
                    f"{decision.fallback_reason}"
                )
            if decision.choice not in controller.ai_legal_choices():
                raise SystemExit("ERROR: belief search returned a non-live-legal choice")

            if HUMAN_TURN_ONE not in controller.human_legal_choices():
                raise SystemExit("ERROR: controlled human turn-one action is not legal")

            update = controller.resolve_turn(
                human_choice=HUMAN_TURN_ONE,
                decision=decision,
            )
            if update.degraded or not controller.particles:
                raise SystemExit(
                    "ERROR: live public observation collapsed the persistent posterior"
                )
            if update.matched_branches <= 0:
                raise SystemExit("ERROR: no hypothetical branch matched the live observation")

            controller.decision_budget_seconds = 1e-9
            fallback = controller.choose_ai_action()
            if fallback.mode != "fallback":
                raise SystemExit("ERROR: tiny decision budget did not trigger fallback")
            if fallback.fallback_reason not in {
                "candidate-screening-deadline",
                "belief-search-deadline",
            }:
                raise SystemExit(
                    "ERROR: unexpected deadline fallback reason: "
                    f"{fallback.fallback_reason}"
                )
            if fallback.choice not in controller.ai_legal_choices():
                raise SystemExit("ERROR: deadline fallback returned a non-live-legal choice")

            print("Persistent public-belief battle controller")
            print(f"Initial particles: {update.particles_before}")
            print(f"Belief-search choice: {decision.choice}")
            print(f"Search candidates: {decision.candidate_count}")
            print(f"Search branches: {decision.branch_count}")
            print(f"Search seconds: {decision.elapsed_seconds:.3f}")
            print(f"Conditioning branches: {update.generated_branches}")
            print(f"Conditioning matches: {update.matched_branches}")
            print(f"Posterior particles: {update.particles_after}")
            print(f"Conditioning seconds: {update.conditioning_seconds:.3f}")
            print(f"Deadline fallback: {fallback.choice}")
            print(f"Fallback reason: {fallback.fallback_reason}")
            print("Live session snapshot read by controller: NO")
            print("Live hidden RNG seed supplied to particles: NO")
            print("RESULT: persistent particles now drive a real turn-by-turn decision loop")
        finally:
            controller.close()


if __name__ == "__main__":
    main()
