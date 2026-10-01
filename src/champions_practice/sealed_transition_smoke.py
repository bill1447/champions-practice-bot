"""Real Showdown coverage for sealed forced-switch and terminal transitions."""

from types import SimpleNamespace

from champions_practice.belief_controller import (
    BeliefDecision,
    SealedTurnState,
    _BeliefBattleCoordinator,
)
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import (
    FORCED_WAIT_CHOICE,
    ShowdownSearchWorker,
)

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


def _run_human_forced_switch_ai_wait(worker: ShowdownSearchWorker) -> None:
    coordinator = _BeliefBattleCoordinator(
        worker,
        battle_format=CHAMPIONS_FORMAT,
        ai_team=HUMAN_TEAM,
        opponent_priors={},
    )
    try:
        coordinator._engine.initialize_preview = lambda **kwargs: kwargs["view"]
        coordinator._engine.observe_public_turn = (
            lambda *, decision, view, resolved_opponent_choice=None: SimpleNamespace(
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
            lambda *, legal_live: _decision(PROTECT)
        )

        coordinator.start(
            opponent_team=SELF_KO_TEAM,
            p1_name="Forced Human",
            p2_name="Waiting AI",
        )
        coordinator.submit_preview(
            human_choice=PREVIEW,
            ai_choice=PREVIEW,
        )

        human_legal = coordinator.human_legal_choices()
        human_explosion = next(
            (
                choice
                for choice in human_legal
                if choice.count("move explosion") == 2
            ),
            None,
        )
        if human_explosion is None:
            raise SystemExit(
                f"ERROR: human self-KO setup lacks double Explosion: {human_legal}"
            )

        first = coordinator.lock_ai_action()
        first_result = coordinator.commit_human_action(
            token=first.token,
            human_choice=human_explosion,
        )
        if first_result.terminal:
            raise SystemExit(
                "ERROR: human self-KO turn ended battle before replacements"
            )

        human_force = coordinator.human_legal_choices()
        replacement = next(
            (
                choice
                for choice in human_force
                if choice.count("switch ") == 2
            ),
            None,
        )
        if replacement is None:
            raise SystemExit(
                f"ERROR: human side did not enter forced-switch phase: {human_force}"
            )

        ai_wait = coordinator._ai_preseal_choices()
        if ai_wait != [FORCED_WAIT_CHOICE]:
            raise SystemExit(
                f"ERROR: waiting AI did not expose explicit wait: {ai_wait}"
            )

        forced = coordinator.lock_ai_action()
        sealed = coordinator._sealed_decision
        if sealed is None or sealed[1].mode != "forced-wait":
            raise SystemExit(
                "ERROR: human forced switch did not seal immediate AI wait"
            )

        forced_result = coordinator.commit_human_action(
            token=forced.token,
            human_choice=replacement,
        )
        if forced_result.terminal:
            raise SystemExit(
                "ERROR: human forced replacement incorrectly ended battle"
            )
        if coordinator.turn_state is not SealedTurnState.RESOLVED:
            raise SystemExit(
                "ERROR: human forced replacement did not resolve cleanly"
            )
        if forced_result.decision.choice != FORCED_WAIT_CHOICE:
            raise SystemExit(
                "ERROR: waiting AI did not seal the explicit forced-wait token"
            )

        print(f"Human forced-switch / AI-wait choice: {FORCED_WAIT_CHOICE}")
    finally:
        coordinator.close()


def _run_partial_double_replacement(worker: ShowdownSearchWorker) -> None:
    coordinator = _BeliefBattleCoordinator(
        worker,
        battle_format=CHAMPIONS_FORMAT,
        ai_team=SELF_KO_TEAM,
        opponent_priors={},
    )
    try:
        coordinator._engine.initialize_preview = lambda **kwargs: kwargs["view"]
        coordinator._engine.observe_public_turn = (
            lambda *, decision, view, resolved_opponent_choice=None: SimpleNamespace(
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

        coordinator.start(
            opponent_team=HUMAN_TEAM,
            p1_name="Partial Replacement Human",
            p2_name="Partial Replacement AI",
        )
        coordinator.submit_preview(
            human_choice=PREVIEW,
            ai_choice=PREVIEW,
        )

        first_legal = coordinator._ai_preseal_choices()
        first_choice = next(
            (
                choice
                for choice in first_legal
                if choice == "move explosion, move protect"
            ),
            None,
        )
        if first_choice is None:
            raise SystemExit(
                "ERROR: partial-replacement setup lacks Explosion + Protect: "
                f"{first_legal}"
            )
        coordinator._engine.choose_ai_action = (
            lambda *, legal_live: _decision(first_choice)
        )
        first = coordinator.lock_ai_action()
        first_result = coordinator.commit_human_action(
            token=first.token,
            human_choice=PROTECT,
        )
        if first_result.terminal:
            raise SystemExit(
                "ERROR: first partial-replacement setup turn ended battle"
            )

        single_force = coordinator._ai_preseal_choices()
        first_replacement = next(
            (
                choice
                for choice in single_force
                if choice.count("switch ") == 1 and "pass" in choice
            ),
            None,
        )
        if first_replacement is None:
            raise SystemExit(
                "ERROR: single AI replacement was not represented as switch/pass: "
                f"{single_force}"
            )
        human_wait = coordinator.human_legal_choices()
        if human_wait != [FORCED_WAIT_CHOICE]:
            raise SystemExit(
                f"ERROR: human did not wait for AI replacement: {human_wait}"
            )
        coordinator._engine.choose_ai_action = (
            lambda *, legal_live: _decision(first_replacement)
        )
        replacement = coordinator.lock_ai_action()
        coordinator.commit_human_action(
            token=replacement.token,
            human_choice=FORCED_WAIT_CHOICE,
        )

        second_legal = coordinator._ai_preseal_choices()
        double_explosion = next(
            (
                choice
                for choice in second_legal
                if choice.count("move explosion") == 2
            ),
            None,
        )
        if double_explosion is None:
            raise SystemExit(
                "ERROR: partial-replacement setup lacks double Explosion: "
                f"{second_legal}"
            )
        coordinator._engine.choose_ai_action = (
            lambda *, legal_live: _decision(double_explosion)
        )
        second = coordinator.lock_ai_action()
        second_result = coordinator.commit_human_action(
            token=second.token,
            human_choice=PROTECT,
        )
        if second_result.terminal:
            raise SystemExit(
                "ERROR: double KO with one reserve incorrectly ended battle"
            )

        partial_force = coordinator._ai_preseal_choices()
        partial_choices = [
            choice
            for choice in partial_force
            if choice.count("switch ") == 1
            and choice.count("pass") == 1
        ]
        if not partial_choices:
            raise SystemExit(
                "ERROR: double KO with one reserve exposed no switch/pass choice: "
                f"{partial_force}"
            )
        if any(choice.count("switch ") > 1 for choice in partial_force):
            raise SystemExit(
                "ERROR: partial replacement exposed duplicate two-switch choice: "
                f"{partial_force}"
            )

        human_force = coordinator.human_legal_choices()
        if not human_force:
            raise SystemExit(
                "ERROR: partial AI replacement exposed no legal human response"
            )
        human_choice = (
            FORCED_WAIT_CHOICE
            if FORCED_WAIT_CHOICE in human_force
            else human_force[0]
        )

        selected = partial_choices[0]
        coordinator._engine.choose_ai_action = (
            lambda *, legal_live: _decision(selected)
        )
        forced = coordinator.lock_ai_action()
        forced_result = coordinator.commit_human_action(
            token=forced.token,
            human_choice=human_choice,
        )
        if forced_result.terminal:
            raise SystemExit(
                "ERROR: legal partial replacement incorrectly ended battle"
            )
        if coordinator.turn_state is not SealedTurnState.RESOLVED:
            raise SystemExit(
                "ERROR: partial double replacement did not resolve cleanly"
            )

        print(f"Partial double-replacement choice: {selected}")
    finally:
        coordinator.close()


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
                lambda *, decision, view, resolved_opponent_choice=None: SimpleNamespace(
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

            ai_force = coordinator._ai_preseal_choices()
            if not any(choice.count("switch ") == 2 for choice in ai_force):
                raise SystemExit("ERROR: real session did not enter AI forced-switch phase")
            for choice in ai_force:
                switch_slots = [
                    command.strip().split()[1]
                    for command in choice.split(",")
                    if command.strip().startswith("switch ")
                ]
                if len(switch_slots) != len(set(switch_slots)):
                    raise SystemExit(
                        "ERROR: public pre-seal choices reused one bench slot twice: "
                        f"{choice}"
                    )
            human_wait = coordinator.human_legal_choices()
            wait_choice = (
                FORCED_WAIT_CHOICE
                if FORCED_WAIT_CHOICE in human_wait
                else human_wait[0]
            )

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

    with ShowdownSearchWorker() as worker:
        _run_human_forced_switch_ai_wait(worker)

    with ShowdownSearchWorker() as worker:
        _run_partial_double_replacement(worker)


if __name__ == "__main__":
    main()
