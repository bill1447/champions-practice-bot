"""Real Showdown coverage for sealed forced-switch and terminal transitions."""

from types import SimpleNamespace

from champions_practice.belief_controller import (
    BeliefDecision,
    SealedTurnState,
    _BeliefBattleCoordinator,
)
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import ShowdownSearchWorker

SELF_KO_TEAM = """Indeedee-F
Ability: Synchronize
Level: 50
- Explosion
- Protect

Sneasler
Ability: Unburden
Level: 50
- Explosion
- Protect

Gardevoir
Ability: Trace
Level: 50
- Explosion
- Protect

Armarouge
Ability: Flash Fire
Level: 50
- Explosion
- Protect
"""

HUMAN_TEAM = """Indeedee-F
Ability: Synchronize
Level: 50
- Protect

Sneasler
Ability: Unburden
Level: 50
- Protect

Gardevoir
Ability: Trace
Level: 50
- Protect

Armarouge
Ability: Flash Fire
Level: 50
- Protect
"""

PREVIEW = "team 1234"
PROTECT = "move protect, move protect"


def _decision(choice: str) -> BeliefDecision:
    return BeliefDecision(
        choice=choice,
        mode="transition-smoke",
        particle_count=1,
        candidate_count=1,
        branch_count=1,
        elapsed_seconds=0.0,
    )


def _pick_ai_choice(legal: list[str]) -> str:
    double_explosion = next(
        (
            choice
            for choice in legal
            if choice.count("move explosion") == 2
        ),
        None,
    )
    if double_explosion is not None:
        return double_explosion

    forced_switch = next(
        (
            choice
            for choice in legal
            if choice.count("switch ") == 2
        ),
        None,
    )
    if forced_switch is not None:
        return forced_switch
    raise SystemExit(f"ERROR: unexpected AI transition choices: {legal}")


def main() -> None:
    with ShowdownSearchWorker() as worker:
        coordinator = _BeliefBattleCoordinator(
            worker,
            battle_format=CHAMPIONS_FORMAT,
            ai_team=SELF_KO_TEAM,
            opponent_priors={},
        )
        try:
            coordinator._engine.initialize_preview = lambda **kwargs: kwargs["view"]
            coordinator._engine.observe_public_turn = (
                lambda *, decision, view: SimpleNamespace(
                    decision=decision,
                    public_view=view,
                    particles_before=1,
                    particles_after=1,
                    generated_branches=1,
                    matched_branches=1,
                    conditioning_seconds=0.0,
                    conditioning_over_budget=False,
                    degraded=False,
                )
            )
            coordinator._engine.choose_ai_action = (
                lambda *, legal_live: _decision(_pick_ai_choice(legal_live))
            )

            coordinator.start(
                opponent_team=HUMAN_TEAM,
                p1_name="Transition Human",
                p2_name="Transition AI",
            )
            coordinator.submit_preview(
                human_choice=PREVIEW,
                ai_choice=PREVIEW,
            )

            first = coordinator.lock_ai_action()
            first_result = coordinator.commit_human_action(
                token=first.token,
                human_choice=PROTECT,
            )
            if first_result.terminal:
                raise SystemExit("ERROR: first self-KO turn ended battle too early")

            if coordinator.turn_state is not SealedTurnState.RESOLVED:
                raise SystemExit("ERROR: first self-KO turn did not resolve cleanly")

            ai_force = coordinator._ai_legal_choices()
            if not any(choice.count("switch ") == 2 for choice in ai_force):
                raise SystemExit("ERROR: real session did not enter AI forced-switch phase")
            human_wait = coordinator.human_legal_choices()
            wait_choice = "" if "" in human_wait else human_wait[0]

            forced = coordinator.lock_ai_action()
            forced_result = coordinator.commit_human_action(
                token=forced.token,
                human_choice=wait_choice,
            )
            if forced_result.terminal:
                raise SystemExit("ERROR: forced replacement incorrectly ended battle")

            final = coordinator.lock_ai_action()
            final_result = coordinator.commit_human_action(
                token=final.token,
                human_choice=PROTECT,
            )
            if not final_result.terminal:
                raise SystemExit("ERROR: second self-KO turn did not end real battle")
            if coordinator.turn_state is not SealedTurnState.TERMINAL:
                raise SystemExit("ERROR: terminal result did not enter TERMINAL state")

            try:
                coordinator.lock_ai_action()
            except RuntimeError:
                pass
            else:
                raise SystemExit("ERROR: terminal battle accepted another AI lock")

            print("Real sealed-session transition smoke")
            print(f"Forced-switch AI choice: {forced_result.decision.choice}")
            print(f"Terminal winner: {final_result.winner or 'draw'}")
            print("RESULT: forced switch and terminal sealing transitions passed")
        finally:
            coordinator.close()


if __name__ == "__main__":
    main()
