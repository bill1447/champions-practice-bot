"""Pinned-runtime regression for public structural target legality."""

from __future__ import annotations

from champions_practice.belief_controller import (
    SealedTurnState,
    _BeliefBattleCoordinator,
)
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import (
    ShowdownRequestError,
    ShowdownSearchWorker,
)

SEED = "sodium,10800001108000021080000310800004"
PREVIEW = "team 1234"
HUMAN_TURN = "move protect, move protect"
EXPECTED_AI = "move helpinghand -2, move helpinghand -1"

HUMAN_TEAM = """Snorlax
Ability: Thick Fat
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

Rillaboom
Ability: Grassy Surge
Level: 50
- Protect
"""

AI_TEAM = """Indeedee-F
Ability: Psychic Surge
Level: 50
- Helping Hand

Clefairy
Ability: Friend Guard
Level: 50
- Helping Hand

Armarouge
Ability: Flash Fire
Level: 50
- Protect

Rillaboom
Ability: Grassy Surge
Level: 50
- Protect
"""


def _helping_hand_commands(choices: list[str]) -> list[str]:
    return [
        choice
        for choice in choices
        if "move helpinghand" in choice
    ]


def main() -> None:
    with ShowdownSearchWorker() as worker:
        coordinator = _BeliefBattleCoordinator(
            worker,
            battle_format=CHAMPIONS_FORMAT,
            ai_team=AI_TEAM,
            opponent_priors={},
        )
        try:
            coordinator.start(
                opponent_team=HUMAN_TEAM,
                p1_name="Human",
                p2_name="Belief AI",
                session_seed=SEED,
            )
            coordinator.submit_preview(
                human_choice=PREVIEW,
                ai_choice=PREVIEW,
            )

            public_choices = coordinator._ai_preseal_choices()
            exact_choices = worker.session_legal_choices(
                coordinator._session_id,
                side="p2",
            )

            if EXPECTED_AI not in public_choices:
                raise SystemExit(
                    "ERROR: public generator omitted the legal Helping Hand geometry: "
                    f"{_helping_hand_commands(public_choices)!r}"
                )
            if EXPECTED_AI not in exact_choices:
                raise SystemExit(
                    "ERROR: Showdown exact validation rejected the expected fixture"
                )

            impossible = [
                choice
                for choice in public_choices
                if "move helpinghand +1" in choice
                or "move helpinghand +2" in choice
                or "move helpinghand -1, move helpinghand -1" in choice
                or "move helpinghand -2, move helpinghand -2" in choice
            ]
            if impossible:
                raise SystemExit(
                    "ERROR: public generator emitted structurally invalid Helping "
                    f"Hand targets: {impossible[:8]!r}"
                )

            before_rejection = worker.session_view(
                coordinator._session_id,
                side="p2",
            )["view"]
            try:
                worker.choose_session(
                    coordinator._session_id,
                    p1_choice=HUMAN_TURN,
                    p2_choice=(
                        "move helpinghand +2, "
                        "move helpinghand +2"
                    ),
                )
            except ShowdownRequestError as error:
                if not error.choice_rejected:
                    raise SystemExit(
                        "ERROR: invalid Helping Hand fixture was not classified "
                        "as a choice rejection"
                    ) from error
            else:
                raise SystemExit(
                    "ERROR: exact Showdown unexpectedly accepted invalid "
                    "Helping Hand targets"
                )

            after_rejection = worker.session_view(
                coordinator._session_id,
                side="p2",
            )["view"]
            if after_rejection != before_rejection:
                raise SystemExit(
                    "ERROR: rejected joint submission mutated the live session"
                )
            if HUMAN_TURN not in coordinator.human_legal_choices():
                raise SystemExit(
                    "ERROR: rejected AI choice left the human choice partially queued"
                )

            # Force the same degraded path that exposed the review bug. The fallback
            # may only choose from the already public-structurally-selectable set.
            coordinator._engine.particles = ()
            coordinator._engine.degraded = True
            ready = coordinator.lock_ai_action()
            sealed = coordinator._sealed_decision
            if sealed is None:
                raise SystemExit("ERROR: degraded fallback did not seal a decision")
            decision = sealed[1]
            if decision.mode != "fallback":
                raise SystemExit(
                    f"ERROR: fixture did not exercise fallback: {decision.mode}"
                )
            if decision.choice != EXPECTED_AI:
                raise SystemExit(
                    "ERROR: degraded fallback did not choose the expected legal "
                    f"Helping Hand command: {decision.choice}"
                )
            if decision.choice not in exact_choices:
                raise SystemExit(
                    "ERROR: degraded fallback sealed a command Showdown rejects"
                )

            result = coordinator.commit_human_action(
                token=ready.token,
                human_choice=HUMAN_TURN,
            )
            if coordinator.turn_state not in {
                SealedTurnState.RESOLVED,
                SealedTurnState.TERMINAL,
            }:
                raise SystemExit(
                    "ERROR: structurally valid fallback did not resolve the turn"
                )

            print("Public structural target legality")
            print(f"Helping Hand public choices: {_helping_hand_commands(public_choices)}")
            print(f"Degraded fallback: {decision.choice}")
            print(f"Matched conditioning branches: {result.matched_branches}")
            print("Invalid foe/self Helping Hand targets exposed pre-seal: NO")
            print("RESULT: degraded fallback seals only public-selectable target geometry")
        finally:
            coordinator.close()


if __name__ == "__main__":
    main()
