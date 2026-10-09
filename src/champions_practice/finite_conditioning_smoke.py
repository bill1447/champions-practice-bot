"""Regression smoke for the frozen league stochastic-collapse trajectory."""

from __future__ import annotations

from champions_practice.belief_controller import SealedBattleFacade
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.demo_fixture import (
    DEMO_AI_PREVIEW_CHOICE,
    DEMO_AI_TEAM,
    DEMO_HUMAN_TEAM,
    demo_public_priors,
)
from champions_practice.strength_league import (
    LeagueConfig,
    _baseline_choice,
    _particle_seed,
    _resolve_preview_choice,
    _sodium_seed,
)


LEAGUE_SEED = 15601
GAME_INDEX = 0


def main() -> None:
    config = LeagueConfig(battles=1, max_decisions=4, seed=LEAGUE_SEED)
    session_seed = _sodium_seed(config.seed, GAME_INDEX)
    particle_seed = _particle_seed(config.seed, GAME_INDEX)

    with SealedBattleFacade(
        battle_format=CHAMPIONS_FORMAT,
        ai_team=DEMO_AI_TEAM,
        ai_preview_choice=DEMO_AI_PREVIEW_CHOICE,
        opponent_priors=demo_public_priors(),
        world_limit=config.world_limit,
        particles_per_world=config.particles_per_world,
        max_particles=config.max_particles,
        candidate_limit=config.candidate_limit,
        response_limit=config.response_limit,
        strategic_plan_limit=config.strategic_plan_limit,
        strategic_candidate_limit=config.strategic_candidate_limit,
        strategic_response_limit=config.strategic_response_limit,
        decision_budget_seconds=config.decision_budget_seconds,
        conditioning_budget_seconds=config.conditioning_budget_seconds,
        worker_startup_timeout_seconds=config.worker_startup_timeout_seconds,
        particle_seed=particle_seed,
    ) as battle:
        battle.start(
            opponent_team=DEMO_HUMAN_TEAM,
            p1_name="Finite Human",
            p2_name="Finite AI",
            session_seed=session_seed,
        )
        preview = _resolve_preview_choice(
            battle.legal_human_choices(),
            DEMO_AI_PREVIEW_CHOICE,
        )
        battle.commit_preview(human_choice=preview)

        results = []
        for decision_index in range(2):
            choices = battle.legal_human_choices()
            if not choices:
                raise SystemExit(
                    "ERROR: frozen finite-conditioning trajectory exposed no "
                    f"human choices at decision {decision_index}"
                )
            human_choice = _baseline_choice(choices)
            ready = battle.lock_ai_action()
            result = battle.commit_human_action(
                token=ready.token,
                human_choice=human_choice,
            )
            results.append((human_choice, result))
            if result.terminal:
                raise SystemExit(
                    "ERROR: frozen finite-conditioning trajectory terminated "
                    "before the historical collapse boundary"
                )

        human_choice, result = results[1]
        # This fixture crosses a genuine stochastic Protect/status boundary.
        # Sampled finite witnesses can cover only some worlds under the 8 s
        # conditioning cap. Such a miss is UNRESOLVED, not a negative proof.
        # PR #195 deliberately stops replaying that history on live decisions.
        # Both outcomes are legitimate, but they have different invariants.
        if result.degraded:
            diagnosis = result.recovery_diagnostic
            if diagnosis is None or not diagnosis.sampled_unresolved_worlds:
                raise SystemExit(
                    "ERROR: degraded conditioning did not retain unresolved "
                    "worlds as public uncertainty"
                )
            if diagnosis.exhaustively_excluded_worlds > diagnosis.worlds_before:
                raise SystemExit(
                    "ERROR: recovered exclusions exceed original belief worlds"
                )
            # Exercise the actual sealed live path, not an internal controller
            # method: an unresolved midgame rebase must promptly yield a legal
            # fallback instead of continuing historical RNG witness retries.
            next_choices = battle.legal_human_choices()
            if not next_choices:
                raise SystemExit(
                    "ERROR: stochastic-collapse fixture has no next live choice"
                )
            ready = battle.lock_ai_action()
            next_turn = battle.commit_human_action(
                token=ready.token,
                human_choice=_baseline_choice(next_choices),
            )
            if (
                next_turn.decision.mode != "fallback"
                or next_turn.decision.fallback_reason != "public-rebase-unresolved"
                or next_turn.recovery_retry_diagnostic is not None
            ):
                raise SystemExit(
                    "ERROR: unresolved stochastic collapse attempted old "
                    f"history recovery: {next_turn.decision!r}"
                )
            print("Unresolved stochastic boundary: correctly entered fresh-public fallback")
            print(f"Worlds still unresolved: {diagnosis.sampled_unresolved_worlds}")
        elif not result.matched_branches:
            raise SystemExit(
                "ERROR: non-degraded frozen league boundary had no "
                "mechanics witness"
            )

        print("Frozen league stochastic-conditioning regression")
        print(f"Decision 1 human command: {human_choice}")
        print(f"Decision 1 AI command: {result.decision.choice}")
        print(f"Matched branches: {result.matched_branches}")
        print(
            "Finite witnesses: "
            f"{result.finite_reachability_witnesses}"
        )
        print(
            "Finite exhaustive disproofs: "
            f"{result.finite_reachability_disproofs}"
        )
        print(
            "Finite unresolved: "
            f"{result.finite_reachability_unresolved}"
        )
        print(
            "Finite leaves examined: "
            f"{result.finite_reachability_leaves}"
        )
        print(f"Posterior particles: {result.particles_after}")
        print(f"Conditioning time: {result.conditioning_seconds:.3f} seconds")
        if result.degraded:
            print(
                "RESULT: partial stochastic witnesses remained unresolved; "
                "next live turn used legal no-history-retry fallback"
            )
        else:
            print(
                "RESULT: exact frozen trajectory advanced the posterior "
                "without entering degraded recovery"
            )


if __name__ == "__main__":
    main()
