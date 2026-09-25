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
HUMAN_TURN_TWO = "switch 3, switch 4"
AI_TURN_TWO = "switch 3, switch 4"


def main() -> None:
    with ShowdownSearchWorker() as worker:
        def forbidden_snapshot(*args, **kwargs):
            raise AssertionError("controller attempted to read live hidden snapshot")

        worker.session_snapshot = forbidden_snapshot
        controller = BeliefBattleController(
            worker,
            battle_format=CHAMPIONS_FORMAT,
            ai_team=SMOKE_TEAM,
            opponent_priors=_public_priors(),
            world_limit=6,
            particles_per_world=1,
            max_particles=6,
            candidate_limit=2,
            response_limit=2,
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
                raise SystemExit(
                    "ERROR: controller created no public-belief particles; "
                    f"first public mismatches={controller.preview_mismatch_paths}; "
                    f"values={controller.preview_mismatch_values}"
                )

            ready = controller.lock_ai_action()
            if hasattr(ready, "choice") or "move " in repr(ready):
                raise SystemExit("ERROR: sealed AI payload leaked before human commit")
            if HUMAN_TURN_ONE not in controller.human_legal_choices():
                raise SystemExit("ERROR: controlled human turn-one action is not legal")

            update = controller.resolve_locked_turn(
                token=ready.token,
                human_choice=HUMAN_TURN_ONE,
            )
            decision = update.decision
            if decision.mode != "belief-search":
                raise SystemExit(
                    "ERROR: first live decision did not come from belief search: "
                    f"{decision.fallback_reason}"
                )
            if decision.choice not in controller.ai_legal_choices():
                raise SystemExit("ERROR: belief search returned a non-live-legal choice")
            if update.degraded or not controller.particles:
                raise SystemExit(
                    "ERROR: live public observation collapsed the persistent posterior"
                )
            if update.matched_branches <= 0:
                raise SystemExit("ERROR: no hypothetical branch matched the live observation")

            controller.fallback_selector = lambda choices: (
                AI_TURN_TWO
                if AI_TURN_TWO in choices
                else choices[0]
            )
            controller.decision_budget_seconds = 1e-9
            fallback_ready = controller.lock_ai_action()
            if hasattr(fallback_ready, "choice") or "move " in repr(fallback_ready):
                raise SystemExit("ERROR: sealed fallback payload leaked before human commit")
            if HUMAN_TURN_TWO not in controller.human_legal_choices():
                raise SystemExit("ERROR: controlled human turn-two switch is not legal")

            second_update = controller.resolve_locked_turn(
                token=fallback_ready.token,
                human_choice=HUMAN_TURN_TWO,
            )
            fallback = second_update.decision
            if fallback.mode != "fallback":
                raise SystemExit("ERROR: tiny decision budget did not trigger fallback")
            if fallback.fallback_reason != "belief-search-deadline":
                raise SystemExit(
                    "ERROR: unexpected deadline fallback reason: "
                    f"{fallback.fallback_reason}"
                )
            if fallback.choice != AI_TURN_TWO:
                raise SystemExit("ERROR: controlled deadline fallback did not double-switch")
            if second_update.degraded or not controller.particles:
                raise SystemExit(
                    "ERROR: second live observation collapsed the persistent posterior"
                )
            if second_update.matched_branches <= 0:
                raise SystemExit("ERROR: turn-two observation matched no particle branch")

            controller.decision_budget_seconds = 8.0
            third_decision = controller.choose_ai_action()
            if third_decision.mode != "belief-search":
                raise SystemExit(
                    "ERROR: third decision did not return to persistent belief search: "
                    f"{third_decision.fallback_reason}"
                )
            if third_decision.choice not in controller.ai_legal_choices():
                raise SystemExit("ERROR: third belief-search choice is not live-legal")

            print("Persistent public-belief battle controller")
            print(f"Initial particles: {update.particles_before}")
            print(f"Turn-one belief-search choice: {decision.choice}")
            print(f"Turn-one search candidates: {decision.candidate_count}")
            print(f"Turn-one search branches: {decision.branch_count}")
            print(f"Turn-one search seconds: {decision.elapsed_seconds:.3f}")
            print(f"Turn-one strategic plan: {decision.strategic_plan or 'none'}")
            print(f"Turn-one conditioning matches: {update.matched_branches}")
            print(f"Turn-one posterior particles: {update.particles_after}")
            print(f"Turn-two deadline fallback: {fallback.choice}")
            print(f"Turn-two fallback reason: {fallback.fallback_reason}")
            print(f"Turn-two conditioning matches: {second_update.matched_branches}")
            print(f"Turn-two posterior particles: {second_update.particles_after}")
            print(f"Turn-three belief-search choice: {third_decision.choice}")
            print(f"Turn-three search seconds: {third_decision.elapsed_seconds:.3f}")
            print("Decision engine live-session capability: NO")
            print("Pre-commit AI decision payload exposed: NO")
            print("Live session snapshot read by decision engine: IMPOSSIBLE")
            print("Live hidden RNG seed supplied to particles: NO")
            print("RESULT: persistent posterior drives decisions across multiple live turns")
        finally:
            controller.close()


if __name__ == "__main__":
    main()
