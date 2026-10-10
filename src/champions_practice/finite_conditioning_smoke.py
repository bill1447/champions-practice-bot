"""Regression smoke for the frozen league stochastic-collapse trajectory."""

from __future__ import annotations

from champions_practice.belief_controller import SealedBattleFacade
from champions_practice.search_worker import FORCED_WAIT_CHOICE
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
        # PR #197: the live controller intentionally does not condition a
        # historical particle ancestry at the turn boundary. The pinned-native
        # finite RNG reachability tests exercise that engine separately.
        if result.particles_after or result.generated_branches or result.matched_branches:
            raise SystemExit(
                "ERROR: a resolved live turn retained historical particle "
                "conditioning state"
            )
        if result.recovery_retry_diagnostic is not None:
            raise SystemExit(
                "ERROR: live stochastic turn attempted historical recovery"
            )

        # A new decision must use fresh current-state hypotheses, or explain
        # why that construction is unsupported. It must never retry history.
        next_choices = battle.legal_human_choices()
        if not next_choices:
            raise SystemExit(
                "ERROR: stochastic fixture has no next live choice"
            )
        ready = battle.lock_ai_action()
        next_turn = battle.commit_human_action(
            token=ready.token,
            human_choice=_baseline_choice(next_choices),
        )
        mode = next_turn.decision.mode
        reason = next_turn.decision.fallback_reason
        if mode == "fallback":
            if not (
                (reason or "").startswith("fresh-public-world:")
                or reason == "belief-search-deadline"
                or (reason or "").startswith("search-error:")
            ):
                raise SystemExit(
                    "ERROR: current decision fell back without a fresh-world "
                    f"reason: {next_turn.decision!r}"
                )
        elif mode == "forced-wait":
            # A forced-wait turn has no AI choice to search. Do not confuse
            # it with a failed fresh-world materialization or a fallback.
            if next_turn.decision.choice != FORCED_WAIT_CHOICE:
                raise SystemExit(
                    "ERROR: forced-wait mode selected an executable action"
                )
        elif mode not in ("belief-search", "strategy"):
            raise SystemExit(
                f"ERROR: unexpected fresh-world decision mode: {mode}"
            )
        if (next_turn.particles_after or next_turn.matched_branches
                or next_turn.recovery_retry_diagnostic is not None):
            raise SystemExit(
                "ERROR: next live turn kept historical particles or retried RNG"
            )

        print("Frozen league stochastic-boundary public-world regression")
        print(f"Decision 1 human command: {human_choice}")
        print(f"Decision 1 AI command: {result.decision.choice}")
        print(f"Decision 1 particles after public update: {result.particles_after}")
        print(f"Fresh-world decision mode: {mode}")
        print(f"Fresh-world failure reason: {reason or 'none'}")
        print("Live historical RNG retry: NO")
        print("RESULT: public turn advances without old-world conditioning")


if __name__ == "__main__":
    main()
