from __future__ import annotations

import json

from champions_practice.belief_controller import (
    BeliefDecision,
    SealedDecisionReady,
    SealedTurnResult,
    SealedTurnState,
)
from champions_practice.demo_server import DemoBattleSession, _choice_label


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
                worst_response="move followme, move hypervoice mega",
                worst_world_score=-321.5,
                weighted_score=-120.0,
                searched_responses=(
                    "move followme, move hypervoice mega",
                    "move followme, move expandingforce +1 mega",
                ),
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
    decision = resolved["history"][0]["decision"]
    assert decision["strategic_plan"] == "preserve-resource"
    assert decision["worst_response"] == "move followme, move hypervoice mega"
    assert decision["worst_world_score"] == -321.5
    assert decision["weighted_score"] == -120.0
    assert decision["searched_responses"] == [
        "move followme, move hypervoice mega",
        "move followme, move expandingforce +1 mega",
    ]
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

def test_demo_snapshot_uses_last_good_view_when_live_view_read_fails() -> None:
    class ViewFailFacade(FakeFacade):
        def __init__(self) -> None:
            super().__init__()
            self.fail_reads = False

        def public_state(self):
            if self.fail_reads:
                raise RuntimeError("temporary view read failure")
            return super().public_state()

    facade = ViewFailFacade()
    session = DemoBattleSession(facade_factory=lambda: facade)
    started = session.start()
    assert started["public_view"] is not None

    facade.fail_reads = True
    snapshot = session.snapshot()

    assert snapshot["public_view"] == started["public_view"]
    assert "temporary view read failure" in snapshot["public_view_error"]

def test_preview_choice_label_names_leads_and_back_pokemon() -> None:
    view = {
        "player": {
            "team": [
                {"species": "Indeedee-F"},
                {"species": "Sneasler"},
                {"species": "Gardevoir"},
                {"species": "Armarouge"},
                {"species": "Rillaboom"},
                {"species": "Metagross"},
            ]
        }
    }

    label = _choice_label("team 2, 1, 3, 5", view)

    assert label == (
        "Lead: Sneasler + Indeedee-F | Back: Gardevoir + Rillaboom"
    )


def test_turn_choice_label_names_moves_targets_mega_and_switches() -> None:
    view = {
        "opponent": {
            "active": [
                {"species": "Rillaboom"},
                {"species": "Sneasler"},
            ]
        },
        "player": {
            "active": ["Sneasler", "Indeedee-F"],
            "team": [
                {"species": "Indeedee-F"},
                {"species": "Sneasler"},
                {"species": "Gardevoir"},
                {"species": "Armarouge"},
            ],
        },
        "request": {
            "active": [
                {
                    "moves": [
                        {"id": "closecombat", "move": "Close Combat"},
                        {"id": "protect", "move": "Protect"},
                    ]
                },
                {
                    "moves": [
                        {"id": "followme", "move": "Follow Me"},
                        {"id": "trickroom", "move": "Trick Room"},
                    ]
                },
            ]
        },
    }

    attack = _choice_label(
        "move closecombat 1 mega, move followme",
        view,
    )
    switch = _choice_label(
        "switch 3, move trickroom",
        view,
    )

    assert attack == (
        "Sneasler: Close Combat → foe Rillaboom [Mega] | Indeedee-F: Follow Me"
    )
    assert switch == (
        "Sneasler: switch → Gardevoir | Indeedee-F: Trick Room"
    )

def test_end_battle_closes_facade_and_preserves_committed_history() -> None:
    facade = FakeFacade()
    session = DemoBattleSession(facade_factory=lambda: facade)
    session.start()
    session.commit_preview("team 1234")
    session.lock_ai_action()
    session.commit_human_action("move human")

    ended = session.end_battle()

    assert facade.closed is True
    assert ended["started"] is False
    assert ended["turn_state"] == "ended"
    assert ended["ai_ready"] is False
    assert ended["legal_choices"] == []
    assert ended["history"][0]["decision"]["choice"] == "move secret-ai"

def test_turn_choice_label_names_ally_targets_by_pokemon() -> None:
    view = {
        "opponent": {"active": [{"species": "FoeA"}, {"species": "FoeB"}]},
        "player": {
            "active": ["Indeedee-F", "Gardevoir-Mega"],
            "team": [
                {"species": "Indeedee-F"},
                {"species": "Gardevoir-Mega"},
            ],
        },
        "request": {
            "active": [
                {"moves": [{"id": "helpinghand", "move": "Helping Hand"}]},
                {"moves": [{"id": "protect", "move": "Protect"}]},
            ]
        },
    }

    label = _choice_label("move helpinghand -2, move protect", view)

    assert label == (
        "Indeedee-F: Helping Hand → ally Gardevoir-Mega | Gardevoir-Mega: Protect"
    )

def test_demo_snapshot_surfaces_public_field_conditions() -> None:
    facade = FakeFacade()
    facade.view["field"] = {
        "terrain": "grassyterrain",
        "weather": "raindance",
        "pseudo_weather": ["trickroom"],
    }
    session = DemoBattleSession(facade_factory=lambda: facade)

    snapshot = session.start()

    assert snapshot["field_status"] == "Field: Grassy Terrain · Rain · Trick Room"

