from types import SimpleNamespace

import pytest

from champions_practice.belief_controller import (
    BeliefDecision,
    BeliefDecisionEngine,
    SealedBattleFacade,
    SealedDecisionReady,
    SealedTurnState,
    _BeliefBattleCoordinator,
    _pin_known_team_genders,
    choose_public_fallback,
)
from champions_practice.observation_beliefs import BeliefParticle, ParticleUpdate
from champions_practice.recommendations import SCREENING_RNG_SEEDS
from champions_practice.strategy import DesiredBoard, StrategicPlan
from champions_practice.search_worker import HypotheticalSearchWorker
from champions_practice.strategy_tactics import StrategicCandidateGuidance


def test_hypothetical_worker_exposes_no_live_session_capabilities() -> None:
    forbidden = {
        "start_session",
        "session_view",
        "session_legal_choices",
        "session_snapshot",
        "choose_session",
        "close_session",
    }

    for name in forbidden:
        assert not hasattr(HypotheticalSearchWorker, name)


def test_decision_engine_owns_no_live_worker_or_session_identifier() -> None:
    engine = BeliefDecisionEngine(
        ".",
        battle_format="test",
        ai_team="team",
        opponent_priors={},
    )

    assert not hasattr(engine, "worker")
    assert not hasattr(engine, "session_id")
    assert not hasattr(engine, "start")
    assert not hasattr(engine, "human_legal_choices")
    assert not hasattr(engine, "resolve_turn")


class _CoordinatorWorker:
    project_root = "."

    def __init__(self) -> None:
        self.started_with = None
        self.submissions = []
        self.closed = []
        self.public_view = {
            "turn": 1,
            "opponent": {"preview_species": ["FoeA", "FoeB"]},
            "player": {
                "team": [{"species": "OwnA"}, {"species": "OwnB"}],
            },
            "request": {},
        }

    def start_session(self, **kwargs):
        self.started_with = kwargs
        return {"session_id": "live-1"}

    def choose_session(self, session_id, *, p1_choice, p2_choice):
        self.submissions.append((session_id, p1_choice, p2_choice))
        return {}

    def session_view(self, session_id, *, side):
        view = {
            **self.public_view,
            "ended": self.public_view.get("ended", False),
            "winner": self.public_view.get("winner"),
        }
        return {"view": view}

    def session_legal_choices(self, session_id, *, side):
        if side == "p1":
            return ["move human"]
        return ["move secret-ai"]

    def close_session(self, session_id):
        self.closed.append(session_id)


def test_coordinator_keeps_human_preview_out_of_decision_engine(monkeypatch) -> None:
    worker = _CoordinatorWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    seen = {}

    def initialize_preview(*, view, ai_choice):
        seen["view"] = view
        seen["ai_choice"] = ai_choice
        return view

    monkeypatch.setattr(
        controller._engine,
        "initialize_preview",
        initialize_preview,
    )

    controller.start(opponent_team="HIDDEN HUMAN TEAM")
    controller.submit_preview(
        human_choice="team 4321",
        ai_choice="team 1234",
    )

    assert worker.started_with["p1_team"] == "HIDDEN HUMAN TEAM"
    assert worker.submissions[-1] == ("live-1", "team 4321", "team 1234")
    assert seen == {
        "view": worker.public_view,
        "ai_choice": "team 1234",
    }
    assert "HIDDEN HUMAN TEAM" not in repr(seen)
    assert "team 4321" not in repr(seen)


def test_sealed_choice_reveals_nothing_before_human_commit(monkeypatch) -> None:
    worker = _CoordinatorWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    controller._session_id = "live-1"
    controller._turn_state = SealedTurnState.IDLE
    secret = BeliefDecision(
        choice="move secret-ai",
        mode="belief-search",
        particle_count=3,
        candidate_count=2,
        branch_count=10,
        elapsed_seconds=0.1,
        strategic_plan="secret-plan",
    )
    monkeypatch.setattr(
        controller._engine,
        "choose_ai_action",
        lambda *, legal_live: secret,
    )
    monkeypatch.setattr(
        controller._engine,
        "observe_public_turn",
        lambda *, decision, view: SimpleNamespace(
            decision=decision,
            public_view=view,
            particles_before=3,
            particles_after=3,
            generated_branches=4,
            matched_branches=2,
            conditioning_seconds=0.01,
            conditioning_over_budget=False,
            degraded=False,
        ),
    )

    ready = controller.lock_ai_action()

    assert isinstance(ready, SealedDecisionReady)
    assert ready.token
    assert not hasattr(ready, "choice")
    assert "secret-ai" not in repr(ready)
    assert "secret-plan" not in repr(ready)
    assert worker.submissions == []

    with pytest.raises(ValueError, match="live-session legal"):
        controller.commit_human_action(
            token=ready.token,
            human_choice="move illegal",
        )
    assert worker.submissions == []

    update = controller.commit_human_action(
        token=ready.token,
        human_choice="move human",
    )

    assert worker.submissions == [
        ("live-1", "move human", "move secret-ai"),
    ]
    assert update.decision is secret
    assert update.decision.choice == "move secret-ai"


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


def test_zero_match_conditioning_keeps_last_good_posterior_for_recovery() -> None:
    engine = BeliefDecisionEngine(
        ".",
        battle_format="test",
        ai_team="team",
        opponent_priors={},
    )
    engine.previews = {"p1": [], "p2": []}
    original = (
        BeliefParticle({"turn": 1}, 1.0, world_id="world-1", history_id="rng-1"),
    )
    engine.particles = original
    engine._run_until_deadline = lambda operation, deadline: (
        ParticleUpdate((), 12, 0, 0),
        False,
    )

    update = engine.observe_public_turn(
        view={"turn": 2, "opponent": {}, "player": {}, "request": {}},
        decision=BeliefDecision(
            choice="move b",
            mode="test",
            particle_count=1,
            candidate_count=0,
            branch_count=0,
            elapsed_seconds=0.0,
        ),
    )

    assert engine.particles == original
    assert engine.degraded is True
    assert len(engine.pending_observations) == 1
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
    probe_candidate = SimpleNamespace(
        choice="move safe",
        evaluation=SimpleNamespace(robust=True),
    )
    probe = SimpleNamespace(
        plan=plan,
        sampled_robust=True,
        pruning=SimpleNamespace(screening_branch_count=5),
        response_screening_branch_count=0,
        branch_count=11,
        ranking=(probe_candidate,),
    )
    guidance = StrategicCandidateGuidance(
        plan_name=plan.name,
        preferred_move_ids=("safe",),
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
    def fake_probe(*args, **kwargs):
        seen["rng_seeds"] = kwargs.get("rng_seeds")
        seen["shared_responses"] = kwargs.get("shared_responses")
        return probe

    monkeypatch.setattr(
        "champions_practice.belief_controller.probe_strategic_plan",
        fake_probe,
    )
    shared_responses = SimpleNamespace(
        response_shortlists=(("move counter",),),
        rng_seeds=SCREENING_RNG_SEEDS,
        screening_branch_count=7,
    )

    def fake_shared_responses(*args, **kwargs):
        seen["shared_candidate_references"] = kwargs.get(
            "candidate_references"
        )
        seen["shared_rng_seeds"] = kwargs.get("rng_seeds")
        return shared_responses

    monkeypatch.setattr(
        "champions_practice.belief_controller.prepare_shared_strategic_responses",
        fake_shared_responses,
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
        guidance_value = kwargs.get("guidance")
        seen["guidance"] = guidance_value
        seen.setdefault("pruning_guidance", []).append(guidance_value)
        return SimpleNamespace(
            candidate_shortlist=("move safe",),
            screening_branch_count=2,
        )

    monkeypatch.setattr(
        "champions_practice.belief_controller.shortlist_belief_candidates",
        fake_pruning,
    )
    def fake_search(*args, **kwargs):
        seen.setdefault("search_rng_seeds", []).append(
            kwargs.get("rng_seeds")
        )
        return SimpleNamespace(
            chosen=SimpleNamespace(choice="move safe"),
            evaluated_choices=("move safe",),
            response_screening_branch_count=3,
            branch_count=4,
        )

    monkeypatch.setattr(
        "champions_practice.belief_controller.search_exact_belief_turn",
        fake_search,
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
    assert decision.strategic_rng_sample_count == len(SCREENING_RNG_SEEDS)
    assert seen["rng_seeds"] == SCREENING_RNG_SEEDS
    assert seen["shared_responses"] is not None
    assert seen["shared_candidate_references"] == ("move safe",)
    assert seen["shared_rng_seeds"] == SCREENING_RNG_SEEDS
    assert seen["guidance"] is None
    assert seen["pruning_guidance"] == [None]
    assert seen["search_rng_seeds"] == [None]
    assert decision.branch_count == 32


def test_strategy_timeout_never_replaces_completed_tactical_result(monkeypatch) -> None:
    controller = _decision_controller()
    controller.decision_budget_seconds = 8.0
    _patch_live_strategy_pipeline(
        monkeypatch,
        selected=True,
    )
    calls = []

    def staged_deadline(operation, *, timeout_seconds):
        calls.append(timeout_seconds)
        if len(calls) == 1:
            return operation(SimpleNamespace()), False
        return None, True

    controller._run_with_deadline = staged_deadline

    decision = controller.choose_ai_action()

    assert len(calls) == 2
    assert 0 < calls[1] <= calls[0] <= 8.0
    assert decision.choice == "move safe"
    assert decision.mode == "belief-search"
    assert decision.fallback_reason is None
    assert decision.strategic_plan is None
    assert decision.strategic_probe_count == 0
    assert decision.branch_count == 9


def test_strategy_error_never_replaces_completed_tactical_result(monkeypatch) -> None:
    controller = _decision_controller()
    _patch_live_strategy_pipeline(
        monkeypatch,
        selected=True,
    )
    calls = 0

    def staged_deadline(operation, *, timeout_seconds):
        nonlocal calls
        calls += 1
        if calls == 1:
            return operation(SimpleNamespace()), False
        raise RuntimeError("strategy exploded")

    controller._run_with_deadline = staged_deadline

    decision = controller.choose_ai_action()

    assert calls == 2
    assert decision.choice == "move safe"
    assert decision.mode == "belief-search"
    assert decision.fallback_reason is None
    assert decision.strategic_plan is None
    assert decision.branch_count == 9


def test_controller_does_not_report_plan_when_final_action_misses_guidance(
    monkeypatch,
) -> None:
    controller = _decision_controller()
    plan, probe, _, _ = _patch_live_strategy_pipeline(
        monkeypatch,
        selected=True,
    )
    mismatched = StrategicCandidateGuidance(
        plan_name=plan.name,
        preferred_move_ids=("protect",),
    )
    monkeypatch.setattr(
        "champions_practice.belief_controller.guidance_from_plan",
        lambda selected_plan, view: mismatched,
    )

    decision = controller.choose_ai_action()

    assert probe.ranking[0].evaluation.robust is True
    assert decision.choice == "move safe"
    assert decision.strategic_plan is None
    assert decision.mode == "belief-search"
    assert decision.branch_count == 41


def test_controller_does_not_report_plan_without_robust_probe_for_final_action(
    monkeypatch,
) -> None:
    controller = _decision_controller()
    plan, probe, guidance, _ = _patch_live_strategy_pipeline(
        monkeypatch,
        selected=True,
    )
    unproven = SimpleNamespace(
        choice="move safe",
        evaluation=SimpleNamespace(robust=False),
    )
    probe.ranking = (unproven,)

    decision = controller.choose_ai_action()

    assert guidance.preferred_move_ids == ("safe",)
    assert decision.choice == "move safe"
    assert decision.strategic_plan is None
    assert decision.mode == "belief-search"
    assert decision.branch_count == 41


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
    assert decision.strategic_rng_sample_count == len(SCREENING_RNG_SEEDS)
    assert seen["rng_seeds"] == SCREENING_RNG_SEEDS
    assert seen["shared_responses"] is not None
    assert seen["shared_candidate_references"] == ("move safe",)
    assert seen["shared_rng_seeds"] == SCREENING_RNG_SEEDS
    assert seen["guidance"] == guidance
    assert seen["pruning_guidance"] == [None, guidance]
    assert seen["search_rng_seeds"] == [None, SCREENING_RNG_SEEDS]
    assert decision.branch_count == 41
