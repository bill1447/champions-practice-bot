from types import SimpleNamespace

import pytest

from champions_practice.belief_controller import (
    BeliefBattleController,
    BeliefDecision,
    _pin_known_team_genders,
    choose_public_fallback,
)
from champions_practice.observation_beliefs import BeliefParticle, ParticleUpdate
from champions_practice.strategy import DesiredBoard, StrategicPlan
from champions_practice.strategy_tactics import StrategicCandidateGuidance


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



class _DecisionWorker:
    project_root = "."

    def session_legal_choices(self, session_id, *, side):
        return ["move safe"]


def _decision_controller() -> BeliefBattleController:
    controller = BeliefBattleController(
        _DecisionWorker(),
        battle_format="test",
        ai_team="team",
        opponent_priors={},
        candidate_limit=4,
        response_limit=4,
    )
    controller.session_id = "session-1"
    controller.last_public_view = {"turn": 2}
    controller.particles = (
        BeliefParticle(
            {"id": "world"},
            1.0,
            world_id="world-1",
            history_id="rng-1",
        ),
    )
    controller._run_with_deadline = lambda operation, timeout_seconds: (
        operation(SimpleNamespace()),
        False,
    )
    return controller


def _patch_live_strategy_pipeline(monkeypatch, *, selected):
    plan = StrategicPlan(
        name="preserve-key",
        objective="preserve the key resource",
        desired_board=DesiredBoard(),
        tactical_priorities=("prefer-protect",),
    )
    probe = SimpleNamespace(
        plan=plan,
        proven_robust=True,
        pruning=SimpleNamespace(screening_branch_count=5),
        response_screening_branch_count=7,
        branch_count=11,
    )
    guidance = StrategicCandidateGuidance(
        plan_name=plan.name,
        preferred_move_ids=("protect",),
    )
    seen = {}

    monkeypatch.setattr(
        "champions_practice.belief_controller.assess_strategic_position",
        lambda view, particles: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "champions_practice.belief_controller.generate_strategic_plans",
        lambda assessment, limit: (plan,),
    )
    monkeypatch.setattr(
        "champions_practice.belief_controller.probe_strategic_plan",
        lambda *args, **kwargs: probe,
    )
    monkeypatch.setattr(
        "champions_practice.belief_controller.select_supported_plan",
        lambda probes: probe if selected else None,
    )
    monkeypatch.setattr(
        "champions_practice.belief_controller.guidance_from_plan",
        lambda selected_plan, view: guidance,
    )

    def fake_pruning(*args, **kwargs):
        seen["guidance"] = kwargs.get("guidance")
        return SimpleNamespace(
            candidate_shortlist=("move safe",),
            screening_branch_count=2,
        )

    monkeypatch.setattr(
        "champions_practice.belief_controller.shortlist_belief_candidates",
        fake_pruning,
    )
    monkeypatch.setattr(
        "champions_practice.belief_controller.search_exact_belief_turn",
        lambda *args, **kwargs: SimpleNamespace(
            chosen=SimpleNamespace(choice="move safe"),
            evaluated_choices=("move safe",),
            response_screening_branch_count=3,
            branch_count=4,
        ),
    )
    return plan, probe, guidance, seen


def test_live_controller_uses_no_strategy_guidance_without_supported_plan(monkeypatch) -> None:
    controller = _decision_controller()
    _, probe, _, seen = _patch_live_strategy_pipeline(
        monkeypatch,
        selected=False,
    )

    decision = controller.choose_ai_action()

    assert decision.choice == "move safe"
    assert decision.mode == "belief-search"
    assert decision.strategic_plan is None
    assert decision.strategic_probe_count == 1
    assert decision.strategic_branch_count == 23
    assert seen["guidance"] is None
    assert decision.branch_count == 32


def test_live_controller_applies_only_selected_supported_plan_guidance(monkeypatch) -> None:
    controller = _decision_controller()
    plan, _, guidance, seen = _patch_live_strategy_pipeline(
        monkeypatch,
        selected=True,
    )

    decision = controller.choose_ai_action()

    assert decision.choice == "move safe"
    assert decision.strategic_plan == plan.name
    assert decision.strategic_probe_count == 1
    assert seen["guidance"] == guidance
