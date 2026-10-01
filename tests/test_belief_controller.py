import copy
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from champions_practice.belief_controller import (
    BeliefCollapseDiagnostic,
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
from champions_practice.recommendations import FINAL_RNG_SEEDS, SCREENING_RNG_SEEDS
from champions_practice.strategy import DesiredBoard, StrategicPlan
from champions_practice.search_worker import (
    FORCED_WAIT_CHOICE,
    HypotheticalSearchWorker,
    ShowdownRequestError,
    ShowdownWorkerTimeout,
)
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


def test_decision_engine_has_no_hidden_state_recovery_install_surface() -> None:
    engine = BeliefDecisionEngine(
        ".",
        battle_format="test",
        ai_team="team",
        opponent_priors={},
    )

    assert not hasattr(engine, "recovery_candidate_generator")
    assert not hasattr(engine, "validate_recovery_candidates")
    assert not hasattr(engine, "install_recovered_particles")


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
        self.aborted = False
        self.public_view = {
            "turn": 1,
            "ended": False,
            "winner": None,
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

    def session_public_choices(self, session_id, *, side):
        if side == "p1":
            return ["move human"]
        return ["move secret-ai"]

    def session_legal_choices(self, session_id, *, side):
        if side == "p1":
            return ["move human"]
        return ["move hidden-oracle"]

    def close_session(self, session_id):
        self.closed.append(session_id)

    def abort(self, *, timeout_seconds=0.25):
        self.aborted = True


class _WaitingCoordinatorWorker(_CoordinatorWorker):
    def session_public_choices(self, session_id, *, side):
        if side == "p2":
            return [FORCED_WAIT_CHOICE]
        return super().session_public_choices(session_id, side=side)


def test_coordinator_seals_explicit_forced_wait_without_search(monkeypatch) -> None:
    worker = _WaitingCoordinatorWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    controller._session_id = "live-1"
    controller._turn_state = SealedTurnState.IDLE

    def fail_search(*, legal_live):
        raise AssertionError(f"forced wait entered decision search: {legal_live}")

    monkeypatch.setattr(controller._engine, "choose_ai_action", fail_search)

    ready = controller.lock_ai_action()

    assert isinstance(ready, SealedDecisionReady)
    assert controller.turn_state is SealedTurnState.LOCKED
    assert controller._sealed_decision is not None
    decision = controller._sealed_decision[1]
    assert decision.choice == FORCED_WAIT_CHOICE
    assert decision.mode == "forced-wait"
    assert decision.candidate_count == 1
    assert decision.branch_count == 0


class _AmbiguousWaitingCoordinatorWorker(_CoordinatorWorker):
    def session_public_choices(self, session_id, *, side):
        if side == "p2":
            return [FORCED_WAIT_CHOICE, "move impossible"]
        return super().session_public_choices(session_id, side=side)


def test_forced_wait_token_cannot_mix_with_action_choices() -> None:
    worker = _AmbiguousWaitingCoordinatorWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    controller._session_id = "live-1"
    controller._turn_state = SealedTurnState.IDLE

    with pytest.raises(RuntimeError, match="only publicly selectable choice"):
        controller.lock_ai_action()

    assert controller.turn_state is SealedTurnState.IDLE


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


def test_ai_sealing_rejects_decision_outside_public_selectable_set(
    monkeypatch,
) -> None:
    worker = _CoordinatorWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    controller._session_id = "live-1"
    controller._turn_state = SealedTurnState.IDLE

    monkeypatch.setattr(
        controller._engine,
        "choose_ai_action",
        lambda *, legal_live: BeliefDecision(
            choice="move structurally-invalid",
            mode="fallback",
            particle_count=0,
            candidate_count=0,
            branch_count=0,
            elapsed_seconds=0.0,
        ),
    )

    with pytest.raises(RuntimeError, match="publicly selectable"):
        controller.lock_ai_action()

    assert controller.turn_state is SealedTurnState.IDLE
    assert controller._sealed_decision is None


def test_ai_sealing_uses_public_choices_not_exact_live_legality(monkeypatch) -> None:
    worker = _CoordinatorWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    controller._session_id = "live-1"
    controller._turn_state = SealedTurnState.IDLE
    seen = []

    def choose(*, legal_live):
        seen.append(tuple(legal_live))
        return BeliefDecision(
            choice=legal_live[0],
            mode="belief-search",
            particle_count=1,
            candidate_count=1,
            branch_count=1,
            elapsed_seconds=0.0,
        )

    monkeypatch.setattr(controller._engine, "choose_ai_action", choose)

    ready = controller.lock_ai_action()

    assert ready.token
    assert seen == [("move secret-ai",)]
    assert controller._sealed_decision is not None
    assert controller._sealed_decision[1].choice == "move secret-ai"


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
        lambda *, decision, view, resolved_opponent_choice=None: SimpleNamespace(
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


def test_successful_conditioning_records_static_recovery_authority_history() -> None:
    engine = BeliefDecisionEngine(
        ".",
        battle_format="test",
        ai_team="team",
        opponent_priors={},
    )
    particle = BeliefParticle(
        {"turn": 1},
        1.0,
        world_id="world-1",
        history_id="rng-1",
    )
    previous = {"turn": 1, "opponent": {}, "player": {}, "request": {}}
    current = {"turn": 2, "opponent": {}, "player": {}, "request": {}}
    engine.previews = {"p1": [], "p2": []}
    engine.particles = (particle,)
    engine.last_public_view = previous
    engine.recovery_authority_root_particles = (particle,)
    engine.recovery_authority_root_public_view = copy.deepcopy(previous)
    engine._run_until_deadline = lambda operation, deadline: (
        ParticleUpdate((particle,), 1, 1, 0),
        False,
    )

    engine.observe_public_turn(
        view=current,
        resolved_opponent_choice="move human",
        decision=BeliefDecision(
            choice="move ai",
            mode="test",
            particle_count=1,
            candidate_count=0,
            branch_count=0,
            elapsed_seconds=0.0,
        ),
    )

    assert engine.recovery_authority_history_complete is True
    assert len(engine.recovery_authority_history) == 1
    observation = engine.recovery_authority_history[0]
    assert observation.ai_choice == "move ai"
    assert observation.resolved_opponent_choice == "move human"
    assert observation.previous_public_view == previous
    assert observation.public_view == current


def test_missing_resolved_command_invalidates_static_recovery_history() -> None:
    engine = BeliefDecisionEngine(
        ".",
        battle_format="test",
        ai_team="team",
        opponent_priors={},
    )
    particle = BeliefParticle(
        {"turn": 1},
        1.0,
        world_id="world-1",
        history_id="rng-1",
    )
    previous = {"turn": 1, "opponent": {}, "player": {}, "request": {}}
    current = {"turn": 2, "opponent": {}, "player": {}, "request": {}}
    engine.previews = {"p1": [], "p2": []}
    engine.particles = (particle,)
    engine.last_public_view = previous
    engine.recovery_authority_root_particles = (particle,)
    engine.recovery_authority_root_public_view = copy.deepcopy(previous)
    engine._run_until_deadline = lambda operation, deadline: (
        ParticleUpdate((particle,), 1, 1, 0),
        False,
    )

    engine.observe_public_turn(
        view=current,
        resolved_opponent_choice=None,
        decision=BeliefDecision(
            choice="move ai",
            mode="test",
            particle_count=1,
            candidate_count=0,
            branch_count=0,
            elapsed_seconds=0.0,
        ),
    )

    assert engine.recovery_authority_history_complete is False
    assert engine.recovery_authority_history == []


def test_observed_action_rng_multiplier_uses_incremental_chunks(
    monkeypatch,
) -> None:
    engine = BeliefDecisionEngine(
        ".",
        battle_format="test",
        ai_team="team",
        opponent_priors={},
        observed_action_rng_multiplier=3,
    )
    engine.previews = {"p1": [], "p2": []}
    particle = BeliefParticle(
        {"turn": 1},
        1.0,
        world_id="world-1",
        history_id="rng-1",
    )
    calls: list[int] = []

    monkeypatch.setattr(
        "champions_practice.belief_controller.public_opponent_moves_fully_observed",
        lambda *args, **kwargs: True,
    )

    def fake_condition(*args, rng_seeds, **kwargs):
        calls.append(len(rng_seeds))
        if len(calls) == 2:
            return ParticleUpdate((particle,), len(rng_seeds), 1, 0)
        return ParticleUpdate((), len(rng_seeds), 0, 0)

    monkeypatch.setattr(
        "champions_practice.belief_controller.condition_particles",
        fake_condition,
    )

    update = engine._condition_adaptive(
        SimpleNamespace(),
        particles=(particle,),
        ai_choice="move protect",
        view={"turn": 2},
        batches=(2,),
    )

    assert calls == [2, 2]
    assert update.particles == (particle,)
    assert update.generated == 4
    assert update.matched == 1


def test_incremental_conditioning_returns_before_hard_deadline(
    monkeypatch,
) -> None:
    engine = BeliefDecisionEngine(
        ".",
        battle_format="test",
        ai_team="team",
        opponent_priors={},
        observed_action_rng_multiplier=4,
    )
    engine.previews = {"p1": [], "p2": []}
    particle = BeliefParticle(
        {"turn": 1},
        1.0,
        world_id="world-1",
        history_id="rng-1",
    )
    calls: list[int] = []

    monkeypatch.setattr(
        "champions_practice.belief_controller.public_opponent_moves_fully_observed",
        lambda *args, **kwargs: True,
    )
    ticks = iter((0.0, 0.6))
    monkeypatch.setattr(
        "champions_practice.belief_controller.perf_counter",
        lambda: next(ticks),
    )

    def fake_condition(*args, rng_seeds, **kwargs):
        calls.append(len(rng_seeds))
        return ParticleUpdate((), len(rng_seeds), 0, 0)

    monkeypatch.setattr(
        "champions_practice.belief_controller.condition_particles",
        fake_condition,
    )

    update = engine._condition_adaptive(
        SimpleNamespace(),
        particles=(particle,),
        ai_choice="move protect",
        view={"turn": 2},
        batches=(2,),
        deadline=1.0,
    )

    assert calls == [2]
    assert update.particles == ()
    assert update.generated == 2
    assert update.matched == 0



def test_pending_rng_retry_reuses_exact_resolved_human_command() -> None:
    engine = BeliefDecisionEngine(
        ".",
        battle_format="test",
        ai_team="team",
        opponent_priors={},
    )
    particle = BeliefParticle(
        {"turn": 1},
        1.0,
        world_id="world-1",
        history_id="rng-1",
    )
    engine.particles = (particle,)
    engine.recovery_authority_root_particles = (particle,)
    engine.recovery_authority_root_public_view = {"turn": 1}
    engine.pending_observations = [
        (
            "move protect",
            "switch 3, pass",
            {"turn": 1},
            {"turn": 2},
        )
    ]
    seen = []

    def fake_condition(worker, **kwargs):
        seen.append(kwargs["resolved_opponent_choice"])
        return ParticleUpdate((particle,), 1, 1, 0)

    engine._condition_adaptive = fake_condition
    engine._run_until_deadline = (
        lambda operation, *, deadline, cleanup_reserve_seconds=0.25:
        (operation(SimpleNamespace()), False)
    )

    assert engine._retry_pending_with_more_rng() is True
    assert seen == ["switch 3, pass"]
    assert engine.pending_observations == []
    assert engine.degraded is False
    assert len(engine.recovery_authority_history) == 1
    assert (
        engine.recovery_authority_history[0].resolved_opponent_choice
        == "switch 3, pass"
    )


class _CollapseDiagnosticWorker:
    def __init__(self, *, human_choice_legal=True, exact_on_second=True) -> None:
        self.human_choice_legal = human_choice_legal
        self.exact_on_second = exact_on_second
        self.calls = 0

    def validate_choices(self, *, state, side, candidates):
        assert side == "p1"
        return list(candidates) if self.human_choice_legal else []

    def legal_choices(self, *, state, side):
        return ["move human"] if self.human_choice_legal else ["move other"]

    def branch_many(self, *, state, branches):
        self.calls += 1
        resolved = []
        for index, _branch in enumerate(branches):
            hp = 49 if self.exact_on_second and index == 1 else 52
            resolved.append(
                {
                    "state": {"turn": 2, "hp": hp},
                    "view": {
                        "turn": 2,
                        "phase": "move",
                        "opponent": {
                            "active": [{"species": "Gardevoir", "hp_percent": hp}],
                        },
                    },
                }
            )
        return resolved

    def state_view(self, *, state, side, previews=None):
        return {
            "turn": 2,
            "phase": "move",
            "opponent": {
                "active": [
                    {"species": "Gardevoir", "hp_percent": state["hp"]},
                ],
            },
        }


def test_collapse_diagnostic_can_confirm_rng_undersampling_without_mutating_rng() -> None:
    engine = BeliefDecisionEngine(
        ".",
        battle_format="test",
        ai_team="team",
        opponent_priors={},
        collapse_debug_budget_seconds=15.0,
        particle_seed=53,
    )
    control = BeliefDecisionEngine(
        ".",
        battle_format="test",
        ai_team="team",
        opponent_priors={},
        collapse_debug_budget_seconds=15.0,
        particle_seed=53,
    )
    worker = _CollapseDiagnosticWorker()
    engine._run_until_deadline = (
        lambda operation, *, deadline, cleanup_reserve_seconds=0.25:
        (operation(worker), False)
    )
    particles = (
        BeliefParticle(
            {"turn": 1},
            1.0,
            world_id="world-1",
            history_id="rng-1",
        ),
    )

    diagnostic = engine.diagnose_collapse(
        particles=particles,
        ai_choice="move ai",
        resolved_opponent_choice="move human",
        previous_view={"turn": 1},
        view={
            "turn": 2,
            "phase": "move",
            "opponent": {
                "active": [{"species": "Gardevoir", "hp_percent": 49}],
            },
        },
    )

    assert isinstance(diagnostic, BeliefCollapseDiagnostic)
    assert diagnostic.summary == "exact-match-found-with-extra-rng"
    assert diagnostic.generated_branches == 2
    assert diagnostic.exact_matches == 1
    assert diagnostic.legal_worlds == 1
    assert diagnostic.illegal_worlds == 0
    assert diagnostic.closest_branches[0].mismatch_count == 0
    assert engine._particle_seed() == control._particle_seed()


def test_collapse_diagnostic_reports_exact_human_choice_illegal_in_particles() -> None:
    engine = BeliefDecisionEngine(
        ".",
        battle_format="test",
        ai_team="team",
        opponent_priors={},
    )
    worker = _CollapseDiagnosticWorker(human_choice_legal=False)
    engine._run_until_deadline = (
        lambda operation, *, deadline, cleanup_reserve_seconds=0.25:
        (operation(worker), False)
    )
    particles = (
        BeliefParticle(
            {"turn": 1},
            1.0,
            world_id="world-1",
            history_id="rng-1",
        ),
    )

    diagnostic = engine.diagnose_collapse(
        particles=particles,
        ai_choice="move ai",
        resolved_opponent_choice="move human",
        previous_view={"turn": 1},
        view={"turn": 2},
    )

    assert diagnostic.summary == "resolved-human-choice-illegal-in-all-particles"
    assert diagnostic.generated_branches == 0
    assert diagnostic.legal_worlds == 0
    assert diagnostic.illegal_worlds == 1
    assert diagnostic.worlds[0].human_choice_legal is False


def _decision_engine() -> BeliefDecisionEngine:
    engine = BeliefDecisionEngine(
        ".",
        battle_format="test",
        ai_team="team",
        opponent_priors={},
        candidate_limit=4,
        response_limit=4,
    )
    engine.last_public_view = {"turn": 2}
    engine.particles = (
        BeliefParticle(
            {"id": "world"},
            1.0,
            world_id="world-1",
            history_id="rng-1",
        ),
    )
    engine._run_until_deadline = lambda operation, deadline: (
        operation(SimpleNamespace()),
        False,
    )
    return engine


def _patch_live_strategy_pipeline(
    monkeypatch,
    *,
    selected,
    baseline_choices=("move safe",),
    guided_choices=("move safe",),
    final_choice="move safe",
    baseline_response="move counter",
    strategic_response="move counter",
):
    plan = StrategicPlan(
        name="preserve-key",
        objective="preserve the key resource",
        desired_board=DesiredBoard(),
        tactical_priorities=("prefer-protect",),
    )
    probe_candidate = SimpleNamespace(
        choice=guided_choices[0],
        evaluation=SimpleNamespace(robust=True),
    )
    probe = SimpleNamespace(
        plan=plan,
        chosen=probe_candidate,
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
        seen["prepared_pruning"] = kwargs.get("prepared_pruning")
        return probe

    monkeypatch.setattr(
        "champions_practice.belief_controller.probe_strategic_plan",
        fake_probe,
    )
    def fake_shared_responses(*args, **kwargs):
        seen["shared_candidate_references"] = kwargs.get(
            "candidate_references"
        )
        seen["shared_response_limit"] = kwargs.get("response_limit")
        seen["shared_rng_seeds"] = kwargs.get("rng_seeds")
        protected = kwargs.get("protected")
        seen["protected_tactical"] = protected
        protected_shortlists = (
            protected.response_shortlists
            if protected is not None
            else ((),)
        )
        response_shortlists = tuple(
            tuple(dict.fromkeys((*responses, strategic_response)))
            for responses in protected_shortlists
        )
        protected_rng = protected.rng_seeds if protected is not None else ()
        rng_seeds = tuple(
            dict.fromkeys((*protected_rng, *kwargs.get("rng_seeds", ())))
        )
        shared_responses = SimpleNamespace(
            response_shortlists=response_shortlists,
            rng_seeds=rng_seeds,
            screening_branch_count=7,
        )
        seen["shared_return_rng_seeds"] = rng_seeds
        seen["shared_return_responses"] = response_shortlists
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
        choices = baseline_choices if guidance_value is None else guided_choices
        pruning = SimpleNamespace(
            candidate_shortlist=tuple(choices),
            screening_branch_count=2,
        )
        if guidance_value is not None:
            seen["guided_pruning"] = pruning
        return pruning

    monkeypatch.setattr(
        "champions_practice.belief_controller.shortlist_belief_candidates",
        fake_pruning,
    )
    def fake_search(*args, **kwargs):
        seen.setdefault("search_rng_seeds", []).append(
            kwargs.get("rng_seeds")
        )
        seen.setdefault("search_choices", []).append(
            tuple(kwargs.get("choices") or ())
        )
        seen.setdefault("search_response_shortlists", []).append(
            kwargs.get("response_shortlists")
        )
        is_final = kwargs.get("response_shortlists") is not None
        choice = final_choice if is_final else baseline_choices[0]
        evaluated = tuple(kwargs.get("choices") or (choice,))
        return SimpleNamespace(
            chosen=SimpleNamespace(choice=choice),
            ranking=tuple(
                SimpleNamespace(choice=candidate)
                for candidate in evaluated
            ),
            evaluated_choices=evaluated,
            response_screening_branch_count=0 if is_final else 3,
            branch_count=4,
            response_shortlists=(
                kwargs.get("response_shortlists")
                if is_final
                else ((baseline_response,),)
            ),
            rng_samples=(
                tuple(kwargs["rng_seeds"])
                if kwargs.get("rng_seeds") is not None
                else (None,)
            ),
        )

    monkeypatch.setattr(
        "champions_practice.belief_controller.search_exact_belief_turn",
        fake_search,
    )
    return plan, probe, guidance, seen


def test_repeated_protect_gets_focused_multi_rng_risk_check(monkeypatch) -> None:
    engine = _decision_engine()
    engine.last_public_view = None
    engine.particles = (
        BeliefParticle(
            {
                "id": "protect-chain",
                "sides": [
                    {"active": [], "pokemon": []},
                    {
                        "active": ["p2a"],
                        "pokemon": [
                            {
                                "position": 0,
                                "volatiles": {"stall": {}},
                            }
                        ],
                    },
                ],
            },
            1.0,
            world_id="world-1",
            history_id="rng-1",
        ),
    )

    protect = "move protect, move psychic +1"
    safe = "switch 4, move psychic +1"
    pruning = SimpleNamespace(
        candidate_shortlist=(protect, safe),
        screening_branch_count=2,
    )
    monkeypatch.setattr(
        "champions_practice.belief_controller.shortlist_belief_candidates",
        lambda *args, **kwargs: pruning,
    )

    calls = []

    def candidate(choice, worst, weighted):
        return SimpleNamespace(
            choice=choice,
            worst_world_score=worst,
            weighted_score=weighted,
            worlds=(),
        )

    def fake_search(*args, **kwargs):
        calls.append(kwargs)
        if kwargs.get("rng_seeds") == FINAL_RNG_SEEDS:
            ranking = (
                candidate(safe, -20.0, -10.0),
                candidate(protect, -900.0, -600.0),
            )
            chosen = ranking[0]
            branch_count = 6
            screening = 0
        else:
            ranking = (
                candidate(protect, -10.0, -5.0),
                candidate(safe, -20.0, -10.0),
            )
            chosen = ranking[0]
            branch_count = 4
            screening = 3
        return SimpleNamespace(
            chosen=chosen,
            ranking=ranking,
            evaluated_choices=tuple(kwargs.get("choices") or ()),
            response_screening_branch_count=screening,
            branch_count=branch_count,
            response_shortlists=(("move counter",),),
            rng_samples=(
                tuple(kwargs["rng_seeds"])
                if kwargs.get("rng_seeds") is not None
                else (None,)
            ),
        )

    monkeypatch.setattr(
        "champions_practice.belief_controller.search_exact_belief_turn",
        fake_search,
    )

    decision = engine.choose_ai_action(legal_live=[protect, safe])

    assert decision.choice == safe
    assert len(calls) == 2
    assert calls[0].get("rng_seeds") is None
    assert calls[1]["rng_seeds"] == FINAL_RNG_SEEDS
    assert calls[1]["response_shortlists"] == (("move counter",),)
    assert calls[1]["choices"] == [protect, safe]


def test_live_controller_uses_no_strategy_guidance_without_supported_plan(monkeypatch) -> None:
    engine = _decision_engine()
    _, probe, guidance, seen = _patch_live_strategy_pipeline(
        monkeypatch,
        selected=False,
    )

    decision = engine.choose_ai_action(legal_live=["move safe"])

    assert decision.choice == "move safe"
    assert decision.mode == "belief-search"
    assert decision.strategic_plan is None
    assert decision.strategic_probe_count == 1
    assert decision.strategic_branch_count == 20
    assert decision.strategic_rng_sample_count == 1 + len(SCREENING_RNG_SEEDS)
    assert seen["rng_seeds"] == SCREENING_RNG_SEEDS
    assert seen["shared_responses"] is not None
    assert seen["shared_candidate_references"] == ("move safe",)
    assert seen["shared_rng_seeds"] == SCREENING_RNG_SEEDS
    assert seen["protected_tactical"].rng_seeds == (None,)
    assert seen["shared_return_rng_seeds"] == (None, *SCREENING_RNG_SEEDS)
    assert seen["guidance"] == guidance
    assert seen["pruning_guidance"] == [None, guidance]
    assert seen["prepared_pruning"] is seen["guided_pruning"]
    assert seen["search_rng_seeds"] == [None]
    assert decision.branch_count == 29


def test_strategy_timeout_never_replaces_completed_tactical_result(monkeypatch) -> None:
    engine = _decision_engine()
    engine.decision_budget_seconds = 8.0
    _patch_live_strategy_pipeline(
        monkeypatch,
        selected=True,
    )
    calls = []

    def staged_deadline(operation, *, deadline):
        calls.append(deadline)
        if len(calls) == 1:
            return operation(SimpleNamespace()), False
        return None, True

    engine._run_until_deadline = staged_deadline

    decision = engine.choose_ai_action(legal_live=["move safe"])

    assert len(calls) == 2
    assert calls[1] == calls[0]
    assert decision.choice == "move safe"
    assert decision.mode == "belief-search"
    assert decision.fallback_reason is None
    assert decision.strategic_plan is None
    assert decision.strategic_probe_count == 0
    assert decision.branch_count == 9


def test_strategy_error_never_replaces_completed_tactical_result(monkeypatch) -> None:
    engine = _decision_engine()
    _patch_live_strategy_pipeline(
        monkeypatch,
        selected=True,
    )
    calls = 0

    def staged_deadline(operation, *, deadline):
        nonlocal calls
        calls += 1
        if calls == 1:
            return operation(SimpleNamespace()), False
        raise RuntimeError("strategy exploded")

    engine._run_until_deadline = staged_deadline

    decision = engine.choose_ai_action(legal_live=["move safe"])

    assert calls == 2
    assert decision.choice == "move safe"
    assert decision.mode == "belief-search"
    assert decision.fallback_reason is None
    assert decision.strategic_plan is None
    assert decision.branch_count == 9


def test_controller_does_not_report_plan_when_final_action_misses_guidance(
    monkeypatch,
) -> None:
    engine = _decision_engine()
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

    decision = engine.choose_ai_action(legal_live=["move safe"])

    assert probe.ranking[0].evaluation.robust is True
    assert decision.choice == "move safe"
    assert decision.strategic_plan is None
    assert decision.mode == "belief-search"
    assert decision.branch_count == 33


def test_controller_does_not_report_plan_without_robust_probe_for_final_action(
    monkeypatch,
) -> None:
    engine = _decision_engine()
    plan, probe, guidance, _ = _patch_live_strategy_pipeline(
        monkeypatch,
        selected=True,
    )
    unproven = SimpleNamespace(
        choice="move safe",
        evaluation=SimpleNamespace(robust=False),
    )
    probe.ranking = (unproven,)

    decision = engine.choose_ai_action(legal_live=["move safe"])

    assert guidance.preferred_move_ids == ("safe",)
    assert decision.choice == "move safe"
    assert decision.strategic_plan is None
    assert decision.mode == "belief-search"
    assert decision.branch_count == 33


def test_live_controller_applies_only_selected_supported_plan_guidance(monkeypatch) -> None:
    engine = _decision_engine()
    plan, _, guidance, seen = _patch_live_strategy_pipeline(
        monkeypatch,
        selected=True,
    )

    decision = engine.choose_ai_action(legal_live=["move safe"])

    assert decision.choice == "move safe"
    assert decision.strategic_plan == plan.name
    assert decision.strategic_probe_count == 1
    assert decision.strategic_rng_sample_count == 1 + len(SCREENING_RNG_SEEDS)
    assert seen["rng_seeds"] == SCREENING_RNG_SEEDS
    assert seen["shared_responses"] is not None
    assert seen["shared_candidate_references"] == ("move safe",)
    assert seen["shared_rng_seeds"] == SCREENING_RNG_SEEDS
    assert seen["protected_tactical"].rng_seeds == (None,)
    assert seen["shared_return_rng_seeds"] == (None, *SCREENING_RNG_SEEDS)
    assert seen["guidance"] == guidance
    assert seen["pruning_guidance"] == [None, guidance]
    assert seen["prepared_pruning"] is seen["guided_pruning"]
    assert seen["search_rng_seeds"] == [
        None,
        (None, *SCREENING_RNG_SEEDS),
    ]
    assert seen["search_response_shortlists"][1] == (("move counter",),)
    assert decision.branch_count == 33



def test_strategy_preserves_known_tactical_response_in_final_union(
    monkeypatch,
) -> None:
    engine = _decision_engine()
    _, _, _, seen = _patch_live_strategy_pipeline(
        monkeypatch,
        selected=True,
        baseline_choices=("move baseline",),
        guided_choices=("move guided",),
        final_choice="move baseline",
        baseline_response="move known-counter",
        strategic_response="move new-counter",
    )

    decision = engine.choose_ai_action(
        legal_live=["move baseline", "move guided"],
    )

    assert seen["protected_tactical"].response_shortlists == (
        ("move known-counter",),
    )
    assert seen["shared_return_responses"] == (
        ("move known-counter", "move new-counter"),
    )
    assert seen["search_response_shortlists"][-1] == (
        ("move known-counter", "move new-counter"),
    )
    assert decision.choice == "move baseline"


def test_strategy_preserves_baseline_native_rng_evidence(monkeypatch) -> None:
    engine = _decision_engine()
    _, _, _, seen = _patch_live_strategy_pipeline(
        monkeypatch,
        selected=True,
        baseline_choices=("move baseline",),
        guided_choices=("move guided",),
        final_choice="move baseline",
    )

    decision = engine.choose_ai_action(
        legal_live=["move baseline", "move guided"],
    )

    assert seen["protected_tactical"].rng_seeds == (None,)
    assert seen["shared_return_rng_seeds"] == (None, *SCREENING_RNG_SEEDS)
    assert seen["search_rng_seeds"] == [
        None,
        (None, *SCREENING_RNG_SEEDS),
    ]
    assert decision.choice == "move baseline"
    assert decision.strategic_rng_sample_count == 1 + len(SCREENING_RNG_SEEDS)


def test_strategy_preserves_repeated_protect_rng_evidence(monkeypatch) -> None:
    engine = _decision_engine()
    engine.particles = (
        BeliefParticle(
            {
                "id": "protect-chain",
                "sides": [
                    {"active": [], "pokemon": []},
                    {
                        "active": ["p2a"],
                        "pokemon": [
                            {
                                "position": 0,
                                "volatiles": {"stall": {}},
                            }
                        ],
                    },
                ],
            },
            1.0,
            world_id="world-1",
            history_id="rng-1",
        ),
    )
    protect = "move protect"
    safe = "move safe"
    _, _, _, seen = _patch_live_strategy_pipeline(
        monkeypatch,
        selected=True,
        baseline_choices=(protect, safe),
        guided_choices=(safe,),
        final_choice=safe,
    )

    decision = engine.choose_ai_action(legal_live=[protect, safe])

    assert seen["protected_tactical"].rng_seeds == (
        None,
        *FINAL_RNG_SEEDS,
    )
    assert seen["shared_return_rng_seeds"] == (
        None,
        *FINAL_RNG_SEEDS,
    )
    assert seen["search_rng_seeds"] == [
        None,
        FINAL_RNG_SEEDS,
        (None, *FINAL_RNG_SEEDS),
    ]
    assert decision.choice == safe
    assert decision.strategic_rng_sample_count == 1 + len(FINAL_RNG_SEEDS)


def test_final_union_keeps_baseline_winner_and_guided_candidate_on_same_evidence(
    monkeypatch,
) -> None:
    engine = _decision_engine()
    _, probe, _, seen = _patch_live_strategy_pipeline(
        monkeypatch,
        selected=True,
        baseline_choices=("move baseline",),
        guided_choices=("move guided",),
        final_choice="move baseline",
    )

    decision = engine.choose_ai_action(
        legal_live=["move baseline", "move guided"],
    )

    assert probe.ranking[0].choice == "move guided"
    assert seen["shared_candidate_references"] == (
        "move baseline",
        "move guided",
    )
    assert seen["shared_response_limit"] == engine.response_limit
    assert seen["shared_response_limit"] > engine.strategic_response_limit
    assert seen["search_choices"] == [
        ("move baseline",),
        ("move baseline", "move guided"),
    ]
    assert seen["search_response_shortlists"][1] == (("move counter",),)
    assert seen["search_rng_seeds"][1] == (None, *SCREENING_RNG_SEEDS)
    assert decision.choice == "move baseline"
    assert decision.strategic_plan is None



def _stub_sealed_engine(
    controller,
    monkeypatch,
    *,
    choice="move secret-ai",
):
    decision = BeliefDecision(
        choice=choice,
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
        lambda *, legal_live: decision,
    )
    monkeypatch.setattr(
        controller._engine,
        "observe_public_turn",
        lambda *, decision, view, resolved_opponent_choice=None: SimpleNamespace(
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
    return decision


class _BlockingStartWorker(_CoordinatorWorker):
    def __init__(self) -> None:
        super().__init__()
        self.start_calls = 0
        self.start_started = Event()
        self.release_start = Event()

    def start_session(self, **kwargs):
        self.start_calls += 1
        self.started_with = kwargs
        self.start_started.set()
        assert self.release_start.wait(timeout=2)
        return {"session_id": "live-1"}


def test_concurrent_start_claims_single_session_owner() -> None:
    worker = _BlockingStartWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            controller.start,
            opponent_team="hidden-team",
        )
        assert worker.start_started.wait(timeout=1)
        assert controller.turn_state is SealedTurnState.STARTING
        assert controller.human_legal_choices() == []

        second = pool.submit(
            controller.start,
            opponent_team="hidden-team",
        )
        with pytest.raises(RuntimeError, match="starting"):
            second.result(timeout=1)

        worker.release_start.set()
        first.result(timeout=2)

    assert worker.start_calls == 1
    assert controller.turn_state is SealedTurnState.PREVIEW
    assert controller._session_id == "live-1"


class _CloseRacingStartWorker(_BlockingStartWorker):
    def __init__(self) -> None:
        super().__init__()
        self.worker_close_calls = 0

    def close(self):
        self.worker_close_calls += 1


def test_close_during_startup_cannot_resurrect_late_session() -> None:
    worker = _CloseRacingStartWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )

    with ThreadPoolExecutor(max_workers=1) as pool:
        starting = pool.submit(
            controller.start,
            opponent_team="hidden-team",
        )
        assert worker.start_started.wait(timeout=1)

        controller.close()
        assert controller.turn_state is SealedTurnState.CLOSED

        worker.release_start.set()
        with pytest.raises(RuntimeError, match="state is closed"):
            starting.result(timeout=2)

    assert controller.turn_state is SealedTurnState.CLOSED
    assert controller._session_id is None
    assert worker.closed == ["live-1"]
    assert worker.worker_close_calls >= 1


class _RejectedStartWorker(_CoordinatorWorker):
    def __init__(self) -> None:
        super().__init__()
        self.start_calls = 0
        self.reject_once = True

    def start_session(self, **kwargs):
        self.start_calls += 1
        if self.reject_once:
            self.reject_once = False
            raise ShowdownRequestError(
                "session_start",
                "injected known startup rejection",
                mutating=True,
                safe_retry=True,
            )
        return super().start_session(**kwargs)


def test_known_start_rejection_returns_to_retryable_new_state() -> None:
    worker = _RejectedStartWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )

    with pytest.raises(ShowdownRequestError, match="known startup rejection"):
        controller.start(opponent_team="hidden-team")

    assert controller.turn_state is SealedTurnState.NEW
    assert controller._session_id is None

    controller.start(opponent_team="hidden-team")

    assert worker.start_calls == 2
    assert controller.turn_state is SealedTurnState.PREVIEW
    assert controller._session_id == "live-1"


class _AmbiguousStartWorker(_CoordinatorWorker):
    def __init__(self) -> None:
        super().__init__()
        self.start_calls = 0
        self.aborted = False

    def start_session(self, **kwargs):
        self.start_calls += 1
        raise RuntimeError("injected ambiguous startup failure")

    def abort(self, *, timeout_seconds=0.25):
        self.aborted = True


def test_ambiguous_start_failure_aborts_and_cannot_resubmit() -> None:
    worker = _AmbiguousStartWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )

    with pytest.raises(RuntimeError, match="ambiguous startup failure"):
        controller.start(opponent_team="hidden-team")

    assert worker.aborted is True
    assert worker.start_calls == 1
    assert controller.turn_state is SealedTurnState.CLOSED
    assert controller._session_id is None

    with pytest.raises(RuntimeError, match="closed"):
        controller.start(opponent_team="hidden-team")
    assert worker.start_calls == 1


class _UnsafeRejectedStartWorker(_CoordinatorWorker):
    def __init__(self) -> None:
        super().__init__()
        self.aborted = False

    def start_session(self, **kwargs):
        raise ShowdownRequestError(
            "session_start",
            "startup failure without rollback proof",
            mutating=True,
        )

    def abort(self, *, timeout_seconds=0.25):
        self.aborted = True


def test_start_request_error_without_rollback_proof_fails_closed() -> None:
    worker = _UnsafeRejectedStartWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )

    with pytest.raises(ShowdownRequestError, match="without rollback proof"):
        controller.start(opponent_team="hidden-team")

    assert worker.aborted is True
    assert controller.turn_state is SealedTurnState.CLOSED
    assert controller._session_id is None


class _BlockingPreviewWorker(_CoordinatorWorker):
    def __init__(self) -> None:
        super().__init__()
        self.preview_started = Event()
        self.release_preview = Event()

    def choose_session(self, session_id, *, p1_choice, p2_choice):
        self.submissions.append((session_id, p1_choice, p2_choice))
        self.preview_started.set()
        assert self.release_preview.wait(timeout=2)
        return {}


def test_concurrent_preview_submission_has_single_mutation_owner(
    monkeypatch,
) -> None:
    worker = _BlockingPreviewWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    controller._session_id = "live-1"
    controller._turn_state = SealedTurnState.PREVIEW
    monkeypatch.setattr(
        controller._engine,
        "initialize_preview",
        lambda *, view, ai_choice: view,
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            controller.submit_preview,
            human_choice="team 4321",
            ai_choice="team 1234",
        )
        assert worker.preview_started.wait(timeout=1)
        assert controller.turn_state is SealedTurnState.PREVIEW_SUBMITTING
        assert controller.human_legal_choices() == []

        second = pool.submit(
            controller.submit_preview,
            human_choice="team 4321",
            ai_choice="team 1234",
        )
        with pytest.raises(RuntimeError, match="preview_submitting"):
            second.result(timeout=1)

        worker.release_preview.set()
        first.result(timeout=2)

    assert worker.submissions == [
        ("live-1", "team 4321", "team 1234"),
    ]
    assert controller.turn_state is SealedTurnState.IDLE


class _PostPreviewViewFailureWorker(_CoordinatorWorker):
    def __init__(self) -> None:
        super().__init__()
        self.preview_submitted = False

    def choose_session(self, session_id, *, p1_choice, p2_choice):
        self.submissions.append((session_id, p1_choice, p2_choice))
        self.preview_submitted = True
        return {}

    def session_view(self, session_id, *, side):
        if self.preview_submitted and side == "p2":
            raise RuntimeError("post-preview public view unavailable")
        return super().session_view(session_id, side=side)


def test_post_preview_observation_failure_requires_restart() -> None:
    worker = _PostPreviewViewFailureWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    controller._session_id = "live-1"
    controller._turn_state = SealedTurnState.PREVIEW

    with pytest.raises(RuntimeError, match="post-submit initialization failed"):
        controller.submit_preview(
            human_choice="team 4321",
            ai_choice="team 1234",
        )

    assert controller.turn_state is SealedTurnState.RESTART_REQUIRED
    assert controller._session_id is None
    assert worker.aborted is True
    assert controller.human_legal_choices() == []
    assert len(worker.submissions) == 1

    with pytest.raises(RuntimeError, match="restart_required"):
        controller.submit_preview(
            human_choice="team 4321",
            ai_choice="team 1234",
        )
    assert len(worker.submissions) == 1


def test_preview_initialization_failure_requires_restart(monkeypatch) -> None:
    worker = _CoordinatorWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    controller._session_id = "live-1"
    controller._turn_state = SealedTurnState.PREVIEW

    def fail_initialize(*, view, ai_choice):
        raise RuntimeError("injected preview initialization failure")

    monkeypatch.setattr(
        controller._engine,
        "initialize_preview",
        fail_initialize,
    )

    with pytest.raises(RuntimeError, match="post-submit initialization failed"):
        controller.submit_preview(
            human_choice="team 4321",
            ai_choice="team 1234",
        )

    assert controller.turn_state is SealedTurnState.RESTART_REQUIRED
    assert controller._session_id is None
    assert worker.aborted is True
    assert worker.submissions == [
        ("live-1", "team 4321", "team 1234"),
    ]

    with pytest.raises(RuntimeError, match="restart_required"):
        controller.submit_preview(
            human_choice="team 4321",
            ai_choice="team 1234",
        )


class _RejectedPreviewWorker(_CoordinatorWorker):
    def __init__(self) -> None:
        super().__init__()
        self.reject_once = True

    def choose_session(self, session_id, *, p1_choice, p2_choice):
        self.submissions.append((session_id, p1_choice, p2_choice))
        if self.reject_once:
            self.reject_once = False
            raise ShowdownRequestError(
                "session_choose",
                "[Invalid choice] injected preview rejection",
                mutating=True,
                safe_retry=True,
            )
        return {}


class _UnsafeRejectedPreviewWorker(_CoordinatorWorker):
    def choose_session(self, session_id, *, p1_choice, p2_choice):
        self.submissions.append((session_id, p1_choice, p2_choice))
        raise ShowdownRequestError(
            "session_choose",
            "preview failure without rollback proof",
            mutating=True,
        )


def test_preview_request_error_without_rollback_proof_requires_restart() -> None:
    worker = _UnsafeRejectedPreviewWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    controller._session_id = "live-1"
    controller._turn_state = SealedTurnState.PREVIEW

    with pytest.raises(ShowdownRequestError, match="without rollback proof"):
        controller.submit_preview(
            human_choice="team 4321",
            ai_choice="team 1234",
        )

    assert controller.turn_state is SealedTurnState.RESTART_REQUIRED
    assert controller._session_id is None
    assert worker.aborted is True
    assert controller.human_legal_choices() == []
    assert len(worker.submissions) == 1


def test_known_preview_rejection_restores_preview_for_safe_retry(
    monkeypatch,
) -> None:
    worker = _RejectedPreviewWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    controller._session_id = "live-1"
    controller._turn_state = SealedTurnState.PREVIEW
    monkeypatch.setattr(
        controller._engine,
        "initialize_preview",
        lambda *, view, ai_choice: view,
    )

    with pytest.raises(ShowdownRequestError, match="preview rejection"):
        controller.submit_preview(
            human_choice="team 4321",
            ai_choice="team 1234",
        )

    assert controller.turn_state is SealedTurnState.PREVIEW

    controller.submit_preview(
        human_choice="team 4321",
        ai_choice="team 1234",
    )

    assert len(worker.submissions) == 2
    assert controller.turn_state is SealedTurnState.IDLE


def test_concurrent_double_lock_allows_only_one_computation(monkeypatch) -> None:
    worker = _CoordinatorWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    controller._session_id = "live-1"
    controller._turn_state = SealedTurnState.IDLE
    started = Event()
    release = Event()
    secret = BeliefDecision(
        choice="move secret-ai",
        mode="belief-search",
        particle_count=1,
        candidate_count=1,
        branch_count=1,
        elapsed_seconds=0.1,
    )

    def slow_choose(*, legal_live):
        started.set()
        assert release.wait(timeout=2)
        return secret

    monkeypatch.setattr(
        controller._engine,
        "choose_ai_action",
        slow_choose,
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(controller.lock_ai_action)
        assert started.wait(timeout=1)
        second = pool.submit(controller.lock_ai_action)
        with pytest.raises(RuntimeError, match="computing"):
            second.result(timeout=1)
        release.set()
        ready = first.result(timeout=2)

    assert ready.token
    assert controller.turn_state is SealedTurnState.LOCKED


class _BlockingCommitWorker(_CoordinatorWorker):
    def __init__(self) -> None:
        super().__init__()
        self.submit_started = Event()
        self.release_submit = Event()

    def choose_session(self, session_id, *, p1_choice, p2_choice):
        self.submissions.append((session_id, p1_choice, p2_choice))
        self.submit_started.set()
        assert self.release_submit.wait(timeout=2)
        self.public_view = {
            **self.public_view,
            "turn": 2,
        }
        return {}


def test_concurrent_repeated_commit_submits_once(monkeypatch) -> None:
    worker = _BlockingCommitWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    controller._session_id = "live-1"
    controller._turn_state = SealedTurnState.IDLE
    _stub_sealed_engine(controller, monkeypatch)
    ready = controller.lock_ai_action()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            controller.commit_human_action,
            token=ready.token,
            human_choice="move human",
        )
        assert worker.submit_started.wait(timeout=1)
        second = pool.submit(
            controller.commit_human_action,
            token=ready.token,
            human_choice="move human",
        )
        with pytest.raises(RuntimeError, match="submitting"):
            second.result(timeout=1)
        worker.release_submit.set()
        result = first.result(timeout=2)

    assert result.decision.choice == "move secret-ai"
    assert worker.submissions == [
        ("live-1", "move human", "move secret-ai"),
    ]
    assert controller.turn_state is SealedTurnState.RESOLVED


class _TimeoutAfterAdvanceWorker(_CoordinatorWorker):
    def choose_session(self, session_id, *, p1_choice, p2_choice):
        self.submissions.append((session_id, p1_choice, p2_choice))
        self.public_view = {
            **self.public_view,
            "turn": 2,
        }
        raise ShowdownWorkerTimeout(
            "session_choose",
            mutating=True,
        )


def test_mutating_timeout_enters_unknown_state_and_reconciles_without_retry(
    monkeypatch,
) -> None:
    worker = _TimeoutAfterAdvanceWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    controller._session_id = "live-1"
    controller._turn_state = SealedTurnState.IDLE
    _stub_sealed_engine(controller, monkeypatch)
    ready = controller.lock_ai_action()

    with pytest.raises(RuntimeError, match="unknown outcome"):
        controller.commit_human_action(
            token=ready.token,
            human_choice="move human",
        )

    assert controller.turn_state is SealedTurnState.UNKNOWN
    assert len(worker.submissions) == 1

    recovered = controller.reconcile_failed_turn(token=ready.token)

    assert recovered.decision.choice == "move secret-ai"
    assert controller.turn_state is SealedTurnState.RESOLVED
    assert len(worker.submissions) == 1


class _TimeoutBeforeAdvanceWorker(_CoordinatorWorker):
    def choose_session(self, session_id, *, p1_choice, p2_choice):
        self.submissions.append((session_id, p1_choice, p2_choice))
        raise ShowdownWorkerTimeout(
            "session_choose",
            mutating=True,
        )


def test_unknown_timeout_reconciliation_requires_proof_before_retry(
    monkeypatch,
) -> None:
    worker = _TimeoutBeforeAdvanceWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    controller._session_id = "live-1"
    controller._turn_state = SealedTurnState.IDLE
    _stub_sealed_engine(controller, monkeypatch)
    ready = controller.lock_ai_action()

    with pytest.raises(RuntimeError, match="unknown outcome"):
        controller.commit_human_action(
            token=ready.token,
            human_choice="move human",
        )

    assert controller.turn_state is SealedTurnState.UNKNOWN
    with pytest.raises(RuntimeError, match="did not advance"):
        controller.reconcile_failed_turn(token=ready.token)

    assert controller.turn_state is SealedTurnState.LOCKED
    assert len(worker.submissions) == 1


class _RejectedSealedChoiceWorker(_CoordinatorWorker):
    def choose_session(self, session_id, *, p1_choice, p2_choice):
        self.submissions.append((session_id, p1_choice, p2_choice))
        raise ShowdownRequestError(
            "session_choose",
            "[Invalid choice] Can't move: Invalid target for Helping Hand",
            mutating=True,
        )


def test_rejected_sealed_choice_fails_closed_instead_of_relocking(
    monkeypatch,
) -> None:
    worker = _RejectedSealedChoiceWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    controller._session_id = "live-1"
    controller._turn_state = SealedTurnState.IDLE
    _stub_sealed_engine(controller, monkeypatch)
    ready = controller.lock_ai_action()

    with pytest.raises(RuntimeError, match="must be restarted"):
        controller.commit_human_action(
            token=ready.token,
            human_choice="move human",
        )

    assert controller.turn_state is SealedTurnState.RESTART_REQUIRED
    assert controller._sealed_decision is None
    assert controller.human_legal_choices() == []
    with pytest.raises(RuntimeError, match="restart_required"):
        controller.lock_ai_action()
    with pytest.raises(RuntimeError, match="cannot reconcile"):
        controller.reconcile_failed_turn(token=ready.token)
    assert len(worker.submissions) == 1


class _FailBeforeAdvanceWorker(_CoordinatorWorker):
    def __init__(self) -> None:
        super().__init__()
        self.fail_once = True

    def choose_session(self, session_id, *, p1_choice, p2_choice):
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("submission failed before advance")
        return super().choose_session(
            session_id,
            p1_choice=p1_choice,
            p2_choice=p2_choice,
        )


def test_submission_failure_before_advance_retains_lock_for_retry(monkeypatch) -> None:
    worker = _FailBeforeAdvanceWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    controller._session_id = "live-1"
    controller._turn_state = SealedTurnState.IDLE
    _stub_sealed_engine(controller, monkeypatch)
    ready = controller.lock_ai_action()

    with pytest.raises(RuntimeError, match="before advance"):
        controller.commit_human_action(
            token=ready.token,
            human_choice="move human",
        )

    assert controller.turn_state is SealedTurnState.LOCKED
    result = controller.commit_human_action(
        token=ready.token,
        human_choice="move human",
    )

    assert result.decision.choice == "move secret-ai"
    assert controller.turn_state is SealedTurnState.RESOLVED


class _CloseFailureWorker(_CoordinatorWorker):
    def __init__(self) -> None:
        super().__init__()
        self.worker_closed = False

    def close_session(self, session_id):
        raise RuntimeError("session close failed")

    def close(self):
        self.worker_closed = True


def test_coordinator_always_closes_worker_when_session_close_fails() -> None:
    worker = _CloseFailureWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    controller._session_id = "live-1"
    controller._turn_state = SealedTurnState.IDLE

    with pytest.raises(RuntimeError, match="session close failed"):
        controller.close()

    assert worker.worker_closed is True
    assert controller.turn_state is SealedTurnState.CLOSED


def test_invalid_facade_configuration_is_rejected_before_worker_spawn(
    monkeypatch,
) -> None:
    constructed = []

    def forbidden_worker(*args, **kwargs):
        constructed.append((args, kwargs))
        raise AssertionError("worker should not be constructed")

    monkeypatch.setattr(
        "champions_practice.belief_controller.ShowdownSearchWorker",
        forbidden_worker,
    )

    with pytest.raises(ValueError, match="max_particles"):
        SealedBattleFacade(
            battle_format="test",
            ai_team="team",
            ai_preview_choice="team 1234",
            opponent_priors={},
            max_particles=0,
        )

    assert constructed == []


class _FailAfterAdvanceWorker(_CoordinatorWorker):
    def choose_session(self, session_id, *, p1_choice, p2_choice):
        self.submissions.append((session_id, p1_choice, p2_choice))
        self.public_view = {
            **self.public_view,
            "turn": 2,
        }
        raise RuntimeError("response lost after live advance")


def test_submission_error_after_advance_is_reconciled_without_resubmit(
    monkeypatch,
) -> None:
    worker = _FailAfterAdvanceWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    controller._session_id = "live-1"
    controller._turn_state = SealedTurnState.IDLE
    _stub_sealed_engine(controller, monkeypatch)
    ready = controller.lock_ai_action()

    result = controller.commit_human_action(
        token=ready.token,
        human_choice="move human",
    )

    assert result.decision.choice == "move secret-ai"
    assert len(worker.submissions) == 1
    assert controller.turn_state is SealedTurnState.RESOLVED


class _ViewFailureAfterAdvanceWorker(_CoordinatorWorker):
    def __init__(self) -> None:
        super().__init__()
        self.after_submit = False
        self.fail_view_once = True

    def choose_session(self, session_id, *, p1_choice, p2_choice):
        self.submissions.append((session_id, p1_choice, p2_choice))
        self.public_view = {
            **self.public_view,
            "turn": 2,
        }
        self.after_submit = True
        return {}

    def session_view(self, session_id, *, side):
        if self.after_submit and side == "p2" and self.fail_view_once:
            self.fail_view_once = False
            raise RuntimeError("post-submit view unavailable")
        return super().session_view(session_id, side=side)


def test_failed_post_submit_view_can_reconcile_without_second_submission(
    monkeypatch,
) -> None:
    worker = _ViewFailureAfterAdvanceWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    controller._session_id = "live-1"
    controller._turn_state = SealedTurnState.IDLE
    _stub_sealed_engine(controller, monkeypatch)
    ready = controller.lock_ai_action()

    with pytest.raises(RuntimeError, match="post-submit view unavailable"):
        controller.commit_human_action(
            token=ready.token,
            human_choice="move human",
        )

    assert controller.turn_state is SealedTurnState.FAILED
    recovered = controller.reconcile_failed_turn(token=ready.token)

    assert recovered.decision.choice == "move secret-ai"
    assert len(worker.submissions) == 1
    assert controller.turn_state is SealedTurnState.RESOLVED


class _BlockingReconcileWorker(_CoordinatorWorker):
    def __init__(self) -> None:
        super().__init__()
        self.after_submit = False
        self.post_submit_reads = 0
        self.reconcile_started = Event()
        self.release_reconcile = Event()

    def choose_session(self, session_id, *, p1_choice, p2_choice):
        self.submissions.append((session_id, p1_choice, p2_choice))
        self.public_view = {
            **self.public_view,
            "turn": 2,
        }
        self.after_submit = True
        return {}

    def session_view(self, session_id, *, side):
        if self.after_submit and side == "p2":
            self.post_submit_reads += 1
            if self.post_submit_reads == 1:
                raise RuntimeError("post-submit view unavailable")
            if self.post_submit_reads == 2:
                self.reconcile_started.set()
                assert self.release_reconcile.wait(timeout=2)
        return super().session_view(session_id, side=side)


def test_concurrent_failed_turn_reconciliation_runs_once(monkeypatch) -> None:
    worker = _BlockingReconcileWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    controller._session_id = "live-1"
    controller._turn_state = SealedTurnState.IDLE
    _stub_sealed_engine(controller, monkeypatch)
    ready = controller.lock_ai_action()

    with pytest.raises(RuntimeError, match="post-submit view unavailable"):
        controller.commit_human_action(
            token=ready.token,
            human_choice="move human",
        )

    assert controller.turn_state is SealedTurnState.FAILED
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            controller.reconcile_failed_turn,
            token=ready.token,
        )
        assert worker.reconcile_started.wait(timeout=1)
        second = pool.submit(
            controller.reconcile_failed_turn,
            token=ready.token,
        )
        with pytest.raises(RuntimeError, match="submitting"):
            second.result(timeout=1)
        worker.release_reconcile.set()
        result = first.result(timeout=2)

    assert result.decision.choice == "move secret-ai"
    assert worker.post_submit_reads == 2
    assert controller.turn_state is SealedTurnState.RESOLVED


class _HumanViewFailureAfterConditioningWorker(_CoordinatorWorker):
    def __init__(self) -> None:
        super().__init__()
        self.after_submit = False
        self.fail_human_view_once = True

    def choose_session(self, session_id, *, p1_choice, p2_choice):
        self.submissions.append((session_id, p1_choice, p2_choice))
        self.public_view = {
            **self.public_view,
            "turn": 2,
        }
        self.after_submit = True
        return {}

    def session_view(self, session_id, *, side):
        if self.after_submit and side == "p1" and self.fail_human_view_once:
            self.fail_human_view_once = False
            raise RuntimeError("human post-submit view unavailable")
        return super().session_view(session_id, side=side)


def test_human_view_failure_does_not_condition_same_turn_twice(monkeypatch) -> None:
    worker = _HumanViewFailureAfterConditioningWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    controller._session_id = "live-1"
    controller._turn_state = SealedTurnState.IDLE
    _stub_sealed_engine(controller, monkeypatch)
    ready = controller.lock_ai_action()
    observed = 0
    observed_human_choices = []

    def count_observation(*, decision, view, resolved_opponent_choice=None):
        nonlocal observed
        observed += 1
        observed_human_choices.append(resolved_opponent_choice)
        return SimpleNamespace(
            decision=decision,
            public_view=view,
            particles_before=3,
            particles_after=3,
            generated_branches=4,
            matched_branches=2,
            conditioning_seconds=0.01,
            conditioning_over_budget=False,
            degraded=False,
        )

    monkeypatch.setattr(
        controller._engine,
        "observe_public_turn",
        count_observation,
    )

    with pytest.raises(RuntimeError, match="human post-submit view unavailable"):
        controller.commit_human_action(
            token=ready.token,
            human_choice="move human",
        )

    assert controller.turn_state is SealedTurnState.FAILED
    assert observed == 0

    result = controller.reconcile_failed_turn(token=ready.token)

    assert result.decision.choice == "move secret-ai"
    assert observed == 1
    assert observed_human_choices == ["move human"]
    assert len(worker.submissions) == 1
    assert controller.turn_state is SealedTurnState.RESOLVED


class _TerminalCommitWorker(_CoordinatorWorker):
    def choose_session(self, session_id, *, p1_choice, p2_choice):
        self.submissions.append((session_id, p1_choice, p2_choice))
        self.public_view = {
            **self.public_view,
            "turn": 2,
            "ended": True,
            "winner": "Human",
        }
        return {}


def test_terminal_resolution_blocks_another_ai_lock(monkeypatch) -> None:
    worker = _TerminalCommitWorker()
    controller = _BeliefBattleCoordinator(
        worker,
        battle_format="test",
        ai_team="own-team",
        opponent_priors={},
    )
    controller._session_id = "live-1"
    controller._turn_state = SealedTurnState.IDLE
    _stub_sealed_engine(controller, monkeypatch)
    ready = controller.lock_ai_action()

    result = controller.commit_human_action(
        token=ready.token,
        human_choice="move human",
    )

    assert result.terminal is True
    assert result.winner == "Human"
    assert controller.turn_state is SealedTurnState.TERMINAL
    with pytest.raises(RuntimeError, match="terminal"):
        controller.lock_ai_action()


def test_demo_facade_exposes_no_direct_decision_or_live_session_handles(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "champions_practice.belief_controller.ShowdownSearchWorker",
        lambda project_root=None, **_kwargs: _CoordinatorWorker(),
    )
    facade = SealedBattleFacade(
        battle_format="test",
        ai_team="own-team",
        ai_preview_choice="team 1234",
        opponent_priors={},
    )

    for forbidden in (
        "choose_ai_action",
        "resolve_turn",
        "engine",
        "worker",
        "session_id",
        "_locked_decision",
    ):
        assert not hasattr(facade, forbidden)
    assert not hasattr(facade, "__dict__")
