from __future__ import annotations

import json

from champions_practice.belief_controller import (
    BeliefDecision,
    SealedDecisionReady,
    SealedTurnResult,
    SealedTurnState,
)
from champions_practice.demo_server import DemoBattleSession


class FakeFacade:
    def __init__(self) -> None:
        self.turn_state = SealedTurnState.NEW
        self.closed = False
        self.submissions: list[tuple[str, str]] = []
        self.view = {
            "turn": 0,
            "ended": False,
            "winner": None,
            "opponent": {"preview_species": ["FoeA", "FoeB"]},
            "player": {"team": [{"species": "OwnA"}, {"species": "OwnB"}]},
        }

    def start(self, **kwargs):
        self.turn_state = SealedTurnState.PREVIEW
        return self.view

    def commit_preview(self, *, human_choice: str):
        assert human_choice == "team 1234"
        self.turn_state = SealedTurnState.IDLE
        self.view = {**self.view, "turn": 1}
        return self.view

    def public_state(self):
        return self.view

    def legal_human_choices(self):
        if self.turn_state is SealedTurnState.PREVIEW:
            return ("team 1234",)
        if self.turn_state in {SealedTurnState.IDLE, SealedTurnState.LOCKED}:
            return ("move human",)
        return ()

    def lock_ai_action(self):
        self.turn_state = SealedTurnState.LOCKED
        return SealedDecisionReady(token="opaque-server-token")

    def commit_human_action(self, *, token: str, human_choice: str):
        assert token == "opaque-server-token"
        assert human_choice == "move human"
        self.submissions.append((token, human_choice))
        self.turn_state = SealedTurnState.RESOLVED
        self.view = {**self.view, "turn": 2}
        return SealedTurnResult(
            decision=BeliefDecision(
                choice="move secret-ai",
                mode="belief-search",
                particle_count=4,
                candidate_count=3,
                branch_count=24,
                elapsed_seconds=0.25,
                strategic_plan="preserve-resource",
            ),
            public_view=self.view,
            particles_before=4,
            particles_after=4,
            generated_branches=8,
            matched_branches=2,
            conditioning_seconds=0.1,
            conditioning_over_budget=False,
            degraded=False,
            terminal=False,
            winner=None,
        )

    def reconcile_failed_turn(self, *, token: str):
        raise AssertionError("reconciliation was not expected")

    def close(self):
        self.closed = True
        self.turn_state = SealedTurnState.CLOSED


def test_demo_session_does_not_expose_locked_ai_decision_or_token() -> None:
    facade = FakeFacade()
    session = DemoBattleSession(facade_factory=lambda: facade)

    preview = session.start()
    assert preview["turn_state"] == "preview"
    session.commit_preview("team 1234")

    locked = session.lock_ai_action()
    encoded = json.dumps(locked)

    assert locked["turn_state"] == "locked"
    assert locked["ai_ready"] is True
    assert "opaque-server-token" not in encoded
    assert "move secret-ai" not in encoded
    assert locked["history"] == []

    resolved = session.commit_human_action("move human")

    assert resolved["turn_state"] == "resolved"
    assert resolved["ai_ready"] is False
    assert resolved["history"][0]["decision"]["choice"] == "move secret-ai"
    assert resolved["history"][0]["decision"]["strategic_plan"] == "preserve-resource"
    assert facade.submissions == [("opaque-server-token", "move human")]


def test_starting_new_demo_battle_closes_old_session_and_clears_trace() -> None:
    facades: list[FakeFacade] = []

    def factory() -> FakeFacade:
        facade = FakeFacade()
        facades.append(facade)
        return facade

    session = DemoBattleSession(facade_factory=factory)
    session.start()
    session.commit_preview("team 1234")
    session.lock_ai_action()
    session.commit_human_action("move human")

    restarted = session.start()

    assert len(facades) == 2
    assert facades[0].closed is True
    assert restarted["turn_state"] == "preview"
    assert restarted["history"] == []
    assert restarted["ai_ready"] is False


def test_demo_snapshot_before_start_contains_no_live_handles() -> None:
    session = DemoBattleSession(facade_factory=FakeFacade)

    snapshot = session.snapshot()
    encoded = json.dumps(snapshot)

    assert snapshot["started"] is False
    assert snapshot["turn_state"] == "new"
    assert snapshot["legal_choices"] == []
    assert "token" not in encoded.lower()
    assert "decision" not in encoded.lower()
