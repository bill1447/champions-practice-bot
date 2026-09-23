import pytest

from champions_practice.belief_controller import (
    BeliefBattleController,
    BeliefDecision,
    _pin_known_team_genders,
    choose_public_fallback,
)
from champions_practice.observation_beliefs import BeliefParticle, ParticleUpdate


def test_public_fallback_returns_legal_choice_without_friendly_fire() -> None:
    choices = [
        "move psychic -2, move protect",
        "move protect, move wideguard",
        "switch 3, switch 4",
    ]

    chosen = choose_public_fallback(choices)

    assert chosen in choices
    assert chosen != "move psychic -2, move protect"


def test_public_fallback_requires_legal_choices() -> None:
    with pytest.raises(ValueError, match="at least one legal choice"):
        choose_public_fallback([])


def test_pin_known_team_genders_uses_own_public_request() -> None:
    team = """Armarouge @ Life Orb
Ability: Flash Fire
Level: 50
- Protect

Sneasler @ Psychic Seed
Ability: Unburden
Level: 50
- Protect
"""
    request = {
        "side": {
            "pokemon": [
                {"details": "Armarouge, L50, F"},
                {"details": "Sneasler, L50, M"},
            ]
        }
    }

    pinned = _pin_known_team_genders(team, request)

    assert "Armarouge (F) @ Life Orb" in pinned
    assert "Sneasler (M) @ Psychic Seed" in pinned
    assert "Gender:" not in pinned


class _ZeroMatchWorker:
    project_root = "."

    def choose_session(self, session_id, *, p1_choice, p2_choice):
        return None

    def session_view(self, session_id, *, side):
        return {"view": {"turn": 2, "opponent": {}, "player": {}, "request": {}}}


def test_zero_match_conditioning_keeps_last_good_posterior_for_recovery() -> None:
    worker = _ZeroMatchWorker()
    controller = BeliefBattleController(
        worker,
        battle_format="test",
        ai_team="team",
        opponent_priors={},
    )
    controller.session_id = "session-1"
    controller.previews = {"p1": [], "p2": []}
    original = (
        BeliefParticle({"turn": 1}, 1.0, world_id="world-1", history_id="rng-1"),
    )
    controller.particles = original
    controller._run_with_deadline = lambda operation, timeout_seconds: (
        ParticleUpdate((), 12, 0, 0),
        False,
    )

    update = controller.resolve_turn(
        human_choice="move a",
        decision=BeliefDecision(
            choice="move b",
            mode="test",
            particle_count=1,
            candidate_count=0,
            branch_count=0,
            elapsed_seconds=0.0,
        ),
    )

    assert controller.particles == original
    assert controller.degraded is True
    assert len(controller.pending_observations) == 1
    assert update.particles_after == 1
    assert update.matched_branches == 0
