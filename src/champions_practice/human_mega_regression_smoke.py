"""Pinned public-only Mega-on-turn-one ledger and production-gate regression.

Seed 7 is an explicit deterministic fixture seed, not an imported replay file.
No opponent private state is supplied to the bot decision engine.
"""

from __future__ import annotations

from champions_practice.belief_controller import SealedBattleFacade
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.present_mechanics import unsupported_present_mechanics
from champions_practice.demo_fixture import (
    DEMO_AI_PREVIEW_CHOICE, DEMO_AI_TEAM, DEMO_HUMAN_TEAM, demo_public_priors,
)
from champions_practice.strength_league import (
    LeagueConfig, _baseline_choice, _particle_seed,
    _sodium_seed,
)


def main() -> None:
    config = LeagueConfig(battles=1, seed=7, max_decisions=8)
    modes: list[str] = []
    failures: list[str] = []
    guarded = 0
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
        particle_seed=_particle_seed(7, 0),
    ) as battle:
        battle.start(
            opponent_team=DEMO_HUMAN_TEAM,
            p1_name="Human Mega regression",
            p2_name="Practice Bot",
            session_seed=_sodium_seed(7, 0),
        )
        # The reviewer's 3164 selection is not legal for this fixed
        # mirror roster (it brings both Mega candidates). Choose a legal
        # Gardevoir lead, and still require actual turn-one Mega.
        legal_previews = battle.legal_human_choices()
        gardevoir_leads = sorted(
            choice for choice in legal_previews
            if choice.startswith("team 3") and "6" not in choice
        )
        if not gardevoir_leads:
            raise SystemExit("ERROR: no legal Gardevoir-led preview")
        preview = gardevoir_leads[0]
        battle.commit_preview(human_choice=preview)
        mega_selected = False
        public_ledger = None
        for turn_index in range(config.max_decisions):
            choices = battle.legal_human_choices()
            if not choices:
                break
            if turn_index == 0:
                mega = [choice for choice in choices
                        if "mega" in choice.lower()
                        and "move " in choice.lower()]
                if not mega:
                    raise SystemExit(
                        "ERROR: human-Mega fixture cannot Mega Evolve on turn one"
                    )
                choice = _baseline_choice(tuple(mega))
                mega_selected = True
            else:
                choice = _baseline_choice(choices)
            public_before = battle.diagnostic_ai_public_checkpoint()
            public_ledger = (
                PublicConstraintLedger.from_public_view(public_before)
                if public_ledger is None else public_ledger.advance(public_before)
            )
            expected_gate = (
                unsupported_present_mechanics(public_before, public_ledger)
                if public_before["turn"] >= 2 else None
            )
            ready = battle.lock_ai_action()
            result = battle.commit_human_action(
                token=ready.token, human_choice=choice,
            )
            modes.append(result.decision.mode)
            if result.decision.fallback_reason:
                failures.append(result.decision.fallback_reason)
            if expected_gate and result.decision.mode != "forced-wait":
                if result.decision.fallback_reason != "fresh-public-world:" + expected_gate:
                    raise SystemExit("ERROR: unsafe Mega checkpoint bypassed production support gate")
                guarded += 1
            if result.terminal:
                break

    search_count = sum(mode in {"belief-search", "strategy"} for mode in modes)
    print(f"Human-Mega seed=7 preview={preview} mega_turn_one={mega_selected}")
    print(f"decisions={len(modes)} search={search_count} modes={modes}")
    print(f"fallback_reasons={failures}")
    if not mega_selected or len(modes) < 3:
        raise SystemExit("ERROR: human-Mega regression did not exercise a midgame")
    if any("public-ledger-unavailable" in reason for reason in failures):
        raise SystemExit("ERROR: opponent Mega quarantined the public ledger")
    # Retain the original coverage regression check for supported states.
    # Exact, independently predicted safety-gate fallbacks are intentional;
    # they must not be relabeled as successful reconstruction or search.
    if search_count < 2 and (not failures or guarded != len(failures)):
        raise SystemExit("ERROR: human Mega disabled tactical search after turn one")
    print(f"RESULT: human Mega public ledger intact; search={search_count}; safety_fallback={guarded}")


if __name__ == "__main__":
    main()
