"""PR #196: public-only midgame hypothesis and negative-authority gates."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from champions_practice.current_state_proposals import CurrentStateProposalBatch
from champions_practice.present_rebase import (
    _positive_mechanics_match,
    _positive_mechanics_rejection,
    build_present_rebase,
)


def sample(turn=8):
    a = {
        "species": "Sneasler", "base_species": "Sneasler",
        "hp_percent": 60, "fainted": False,
        "status": "par", "boosts": {"atk": -1},
    }
    b = {
        "species": "Indeedee-F", "base_species": "Indeedee-F",
        "hp_percent": 100, "fainted": False,
        "status": None, "boosts": {"atk": 0},
    }
    view = {
        "turn": turn, "phase": "move",
        "ended": False, "winner": None,
        "request": {"side": {"id": "p2"}, "active": []},
        "field": {"weather": None, "terrain": None, "pseudo_weather": []},
        "player": {"name": "Bot", "team": [{"species": "Gardevoir"}]},
        "opponent": {
            "name": "Human",
            "preview_species": ["Sneasler", "Indeedee-F"],
            "active": [a, b],
            "side_conditions": [],
            "revealed": [
                {"species": "Sneasler", "moves": ["direclaw"],
                 "items": [], "abilities": [], "hp_percent": 60,
                 "status": "par", "fainted": False, "seen": True},
                {"species": "Indeedee-F", "moves": [], "items": [],
                 "abilities": [], "hp_percent": 100, "status": None,
                 "fainted": False, "seen": True},
            ],
        },
    }
    sides = [{
        "pokemon": [
            {"set": {"species": "Sneasler"}, "hp": 90, "maxhp": 150,
             "fainted": False, "isActive": True, "status": "par",
             "boosts": {"atk": -1}},
            {"set": {"species": "Indeedee-F"}, "hp": 150, "maxhp": 150,
             "fainted": False, "isActive": True, "status": "",
             "boosts": {"atk": 0}},
        ],
    }, {"pokemon": [{}]}]
    state = {"turn": turn, "sides": sides}
    ledger = SimpleNamespace(
        current_turn=turn,
        current_signature="public-current-turn-8",
        own_request=json.dumps(view["request"], sort_keys=True, separators=(",", ":")),
        preview_species=("Sneasler", "Indeedee-F"),
    )
    return view, state, ledger


def test_native_positive_mechanics_gate_rejects_contradictory_public_hp_and_status():
    view, state, ledger = sample()
    assert _positive_mechanics_match(
        state, view, current_view=view, ledger=ledger,
        legal_live=("move protect",), hypothetical_legal=["move protect"],
    )
    state["sides"][0]["pokemon"][0]["hp"] = 95
    assert not _positive_mechanics_match(
        state, view, current_view=view, ledger=ledger,
        legal_live=(), hypothetical_legal=[],
    )
    state["sides"][0]["pokemon"][0]["hp"] = 90
    state["sides"][0]["pokemon"][0]["status"] = ""
    assert not _positive_mechanics_match(
        state, view, current_view=view, ledger=ledger,
        legal_live=(), hypothetical_legal=[],
    )


def test_fainted_opponent_slot_is_not_a_living_active_pokemon():
    view, state, ledger = sample()
    observed = view["opponent"]["active"][0]
    native = state["sides"][0]["pokemon"][0]
    observed.update(hp_percent=0, fainted=True, status=None, boosts={})
    native.update(hp=0, fainted=True, isActive=False, status="", boosts={})
    assert _positive_mechanics_rejection(
        state, view, current_view=view, ledger=ledger,
        legal_live=("move protect",), hypothetical_legal=["move protect"],
    ) is None

    # No false authorization for a still-living or active native member.
    native["isActive"] = True
    assert _positive_mechanics_rejection(
        state, view, current_view=view, ledger=ledger,
        legal_live=(), hypothetical_legal=[],
    ) == "$.opponent.active[0].native_fainted"
    native["isActive"] = False
    native["fainted"] = False
    assert _positive_mechanics_rejection(
        state, view, current_view=view, ledger=ledger,
        legal_live=(), hypothetical_legal=[],
    ) == "$.opponent.active[0].native_fainted"
    native["fainted"] = True
    native["hp"] = 1
    assert _positive_mechanics_rejection(
        state, view, current_view=view, ledger=ledger,
        legal_live=(), hypothetical_legal=[],
    ) == "$.opponent.active[0].native_fainted"


def test_midgame_turn_eight_uses_only_fresh_public_set_and_native_state(monkeypatch):
    view, state, ledger = sample()
    proposal = SimpleNamespace(
        proposal_id="public-prior:known", weight=1.0,
        team_text="public team", world=SimpleNamespace(sets=()),
    )
    batch = CurrentStateProposalBatch(
        proposals=(proposal,), source_turn=8, source_signature=ledger.current_signature,
        candidates_considered=1, rejected_missing_public_moves=0,
    )
    monkeypatch.setattr(
        "champions_practice.present_rebase._require_current_public_input",
        lambda _ledger, _view: None,
    )
    monkeypatch.setattr(
        "champions_practice.present_rebase.build_current_state_set_proposals",
        lambda **_kwargs: batch,
    )
    monkeypatch.setattr(
        "champions_practice.present_rebase._matches_approved_prior",
        lambda _state, _proposal: True,
    )
    monkeypatch.setattr(
        "champions_practice.present_rebase.preview_choice_for_world",
        lambda _belief, _world: "team 12",
    )

    class Worker:
        def __init__(self):
            self.created = []
            self.built = []

        def create_state(self, **kwargs):
            assert set(kwargs) == {
                "battle_format", "p1_team", "p2_team", "p1_preview", "p2_preview",
                "p1_name", "p2_name", "seed",
            }
            assert kwargs["p1_team"] == "public team"
            assert kwargs["p2_team"] == "own team"
            self.created.append(kwargs)
            return {"fresh": True, "turn": 1}

        def materialize_present_hypotheses(self, *, state, current_view, limit):
            assert state == {"fresh": True, "turn": 1}
            assert current_view is view
            assert limit <= 4
            self.built.append(state)
            return {"outcomes": [{"state": state_target, "hp": [90, 150]}],
                    "reason": None}

        def state_view(self, *, state, side, previews):
            assert side == "p2"
            assert previews["p1"] == list(ledger.preview_species)
            return view

        def legal_choices(self, *, state, side):
            return ["move protect"]

    state_target = state
    worker = Worker()
    report = build_present_rebase(
        worker, ledger=ledger, current_view=view,
        priors={}, battle_format="test", ai_team="own team",
        ai_preview_choice="team 12",
        legal_live=("move protect",),
    )
    assert report.positive_matches == 1
    assert report.particles[0].state is state
    assert report.particles[0].history_id == "native-present-hypothesis"
    assert report.exhaustively_excluded_worlds == 0
    assert report.historical_witnesses == 0
    assert worker.created and worker.built
    # Same current public observation, but conflicting native status: no
    # admission, no negative exclusion, and no historical retry.
    state["sides"][0]["pokemon"][0]["status"] = ""
    rejected = build_present_rebase(
        worker, ledger=ledger, current_view=view,
        priors={}, battle_format="test", ai_team="own team",
        ai_preview_choice="team 12",
        legal_live=("move protect",),
    )
    assert rejected.particles == ()
    assert rejected.exhaustively_excluded_worlds == 0
    assert rejected.native_candidates == 1
    assert rejected.unresolved_reason == (
        "positive-current-mismatch:$.opponent.active[0].status"
    )
    assert rejected.rejection_reasons == (
        ("positive-current-mismatch:$.opponent.active[0].status", 1),
    )


def test_positive_gate_reports_exact_own_field_without_values():
    view, state, ledger = sample()
    projected = json.loads(json.dumps(view))
    projected["player"]["team"][0]["speed"] = 122
    view["player"]["team"][0]["speed"] = 121
    assert _positive_mechanics_rejection(
        state, projected, current_view=view, ledger=ledger,
        legal_live=("move protect",), hypothetical_legal=["move protect"],
    ) == "$.player.team[0].speed"
    assert not _positive_mechanics_match(
        state, projected, current_view=view, ledger=ledger,
        legal_live=("move protect",), hypothetical_legal=["move protect"],
    )


def test_native_roster_active_slots_follow_pinned_switch_order():
    view, state, ledger = sample()
    # The pinned simulator moves switched-in Pokemon to the first two roster
    # slots. A previously active member on the bench is not checked as active.
    bench = {
        "set": {"species": "Metagross"}, "hp": 150, "maxhp": 150,
        "fainted": False, "isActive": False, "status": "",
        "boosts": {"atk": 0},
    }
    state["sides"][0]["pokemon"].append(bench)
    assert _positive_mechanics_match(
        state, view, current_view=view, ledger=ledger,
        legal_live=(), hypothetical_legal=[],
    )
    # A broken serializer that left the bench mon in slot one must not pass.
    state["sides"][0]["pokemon"][0], state["sides"][0]["pokemon"][2] = (
        state["sides"][0]["pokemon"][2], state["sides"][0]["pokemon"][0]
    )
    assert _positive_mechanics_rejection(
        state, view, current_view=view, ledger=ledger,
        legal_live=(), hypothetical_legal=[],
    ) == "$.opponent.active[0].native_active"


def test_native_constructor_rejection_keeps_first_mismatched_request_path(monkeypatch):
    view, _, ledger = sample()
    proposal = SimpleNamespace(
        proposal_id="public-prior:snapshot", weight=1.0,
        team_text="public team", world=SimpleNamespace(sets=()),
    )
    batch = CurrentStateProposalBatch(
        proposals=(proposal,), source_turn=8,
        source_signature=ledger.current_signature,
        candidates_considered=1, rejected_missing_public_moves=0,
    )
    monkeypatch.setattr(
        "champions_practice.present_rebase._require_current_public_input",
        lambda _ledger, _view: None,
    )
    monkeypatch.setattr(
        "champions_practice.present_rebase.build_current_state_set_proposals",
        lambda **_kw: batch,
    )
    monkeypatch.setattr(
        "champions_practice.present_rebase.preview_choice_for_world",
        lambda *_a: "team 12",
    )

    class Worker:
        def create_state(self, **kwargs):
            return {"turn": 1}

        def materialize_present_hypotheses(self, *, state, current_view, limit):
            return {
                "outcomes": [], "reason": "exact-own-request-mismatch",
                "mismatch_path": "$.request.active[0].moves[0].pp",
            }

    report = build_present_rebase(
        Worker(), ledger=ledger, current_view=view,
        priors={}, battle_format="test", ai_team="own team",
        ai_preview_choice="team 12",
    )
    assert report.roots_tried == 1
    assert report.native_candidates == 0
    assert report.unresolved_reason == (
        "exact-own-request-mismatch:$.request.active[0].moves[0].pp"
    )
    assert report.rejection_reasons == ((report.unresolved_reason, 1),)
    assert report.exhaustively_excluded_worlds == 0


@pytest.mark.parametrize("limit", [0, -1, 9, True])
def test_present_rebase_rejects_unbounded_particle_search(limit):
    view, _, ledger = sample()
    with pytest.raises(ValueError):
        build_present_rebase(
            SimpleNamespace(), ledger=ledger, current_view=view,
            priors={}, battle_format="test", ai_team="team",
            ai_preview_choice="team 12", max_particles=limit,
        )
