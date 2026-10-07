"""Regression smoke for the league stochastic-collapse conditioning case."""

from __future__ import annotations

from champions_practice.belief_controller import (
    BeliefDecision,
    _BeliefBattleCoordinator,
)
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.demo_fixture import (
    DEMO_AI_PREVIEW_CHOICE,
    DEMO_AI_TEAM,
    DEMO_HUMAN_TEAM,
    demo_public_priors,
)
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.strength_league import _particle_seed, _sodium_seed


LEAGUE_SEED = 15601
GAME_INDEX = 0
HUMAN_CHOICE = "move protect, move trickroom"
AI_CHOICE = "move direclaw +1, move imprison"


def main() -> None:
    with ShowdownSearchWorker() as worker:
        coordinator = _BeliefBattleCoordinator(
            worker,
            battle_format=CHAMPIONS_FORMAT,
            ai_team=DEMO_AI_TEAM,
            opponent_priors=demo_public_priors(),
            world_limit=8,
            particles_per_world=1,
            max_particles=8,
            candidate_limit=4,
            response_limit=4,
            decision_budget_seconds=8.0,
            conditioning_budget_seconds=8.0,
            particle_seed=_particle_seed(LEAGUE_SEED, GAME_INDEX),
        )
        try:
            coordinator.start(
                opponent_team=DEMO_HUMAN_TEAM,
                p1_name="Finite Human",
                p2_name="Finite AI",
                session_seed=_sodium_seed(LEAGUE_SEED, GAME_INDEX),
            )
            coordinator.submit_preview(
                human_choice=DEMO_AI_PREVIEW_CHOICE,
                ai_choice=DEMO_AI_PREVIEW_CHOICE,
            )
            if HUMAN_CHOICE not in coordinator.human_legal_choices():
                raise SystemExit(
                    "ERROR: finite-conditioning human regression choice is not legal"
                )
            if AI_CHOICE not in coordinator._ai_preseal_choices():
                raise SystemExit(
                    "ERROR: finite-conditioning AI regression choice is not legal"
                )

            forced = BeliefDecision(
                choice=AI_CHOICE,
                mode="controlled-finite-smoke",
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

            result = coordinator.commit_human_action(
                token=ready.token,
                human_choice=HUMAN_CHOICE,
            )

            if result.degraded:
                raise SystemExit(
                    "ERROR: finite stochastic reachability did not rescue the "
                    f"known league collapse: {result.recovery_diagnostic!r}"
                )
            if result.finite_reachability_witnesses <= 0:
                raise SystemExit(
                    "ERROR: known league collapse recovered without a finite "
                    "reachability witness"
                )
            if result.finite_reachability_unresolved:
                raise SystemExit(
                    "ERROR: known league collapse left finite worlds unresolved"
                )
            if not coordinator._engine.particles:
                raise SystemExit(
                    "ERROR: finite stochastic conditioning retained no particles"
                )

            print("Finite stochastic belief-conditioning regression")
            print(f"Human public command: {HUMAN_CHOICE}")
            print(f"AI command: {AI_CHOICE}")
            print(
                "Finite witnesses: "
                f"{result.finite_reachability_witnesses}"
            )
            print(
                "Finite exhaustive disproofs: "
                f"{result.finite_reachability_disproofs}"
            )
            print(
                "Finite leaves examined: "
                f"{result.finite_reachability_leaves}"
            )
            print(f"Posterior particles: {result.particles_after}")
            print(f"Conditioning time: {result.conditioning_seconds:.3f} seconds")
            print(
                "RESULT: public command evidence plus finite Showdown stochastic "
                "reachability prevents the league collapse"
            )
        finally:
            coordinator.close()


if __name__ == "__main__":
    main()
