"""Public constraint-ledger regressions, independent of simulated ancestry."""

from __future__ import annotations

from copy import deepcopy

import pytest

from champions_practice.current_state_constraints import (
    PublicConstraintLedger,
)


@pytest.fixture(autouse=True)
def minimal_public_fixture(monkeypatch):
    # Unit fixtures exercise the ledger logic with reduced public shapes.
    # The pinned-runtime integration smoke below exercises the real full
    # v9 public-observation validator (no monkeypatch).
    monkeypatch.setattr(
        "champions_practice.current_state_constraints."
        "public_reachability_observation_issue",
        lambda _view: None,
    )


def view(*, turn=1, hp=76, revealed_moves=None, event_hp="76/100"):
    return {
        "turn": turn,
        "phase": "move",
        "ended": False,
        "winner": None,
        "field": {"weather": None, "terrain": None, "pseudo_weather": []},
        "request": {"own_hp": hp, "choices": ["move protect"]},
        "player": {"name": "AI", "own_hp": hp},
        "opponent": {
            "name": "Human",
            "preview_species": ["Rillaboom", "Sneasler"],
            "active": [
                {
                    "species": "Rillaboom",
                    "base_species": "Rillaboom",
                    "hp_percent": 70,
                    "fainted": False,
                    "status": None,
                    "boosts": {},
                }
            ],
            "revealed": [
                {
                    "species": "Rillaboom",
                    "moves": list(revealed_moves or ()),
                    "items": ["sitrusberry"],
                    "abilities": ["grassysurge"],
                    "hp_percent": 70,
                    "status": None,
                    "fainted": False,
                    "seen": True,
                }
            ],
            "side_conditions": [],
        },
        "public_event_delta": {
            "turn": 1,
            "events": [["-damage", "p1a", event_hp], ["-enditem", "p1a", "sitrusberry"]],
            "unsupported": [],
        },
        "public_execution_delta": {
            "turn": 1,
            "actions": [
                {
                    "side": "opponent",
                    "slot": 1,
                    "move": "woodhammer",
                    "outcome": "executed",
                }
            ],
        },
        "opponent_last_actions": [{"turn": 1, "slot": 1, "move": "woodhammer"}],
    }


def test_history_survives_new_snapshot_without_revealed_move():
    opening = view(revealed_moves=["woodhammer"])
    ledger = PublicConstraintLedger.from_public_view(opening)
    later = view(turn=2, hp=40, revealed_moves=[], event_hp="33/100")
    result = ledger.advance(later)
    assert result.known_sets[0].moves == ("woodhammer",)
    assert result.known_sets[0].items == ("sitrusberry",)
    assert result.known_sets[0].abilities == ("grassysurge",)
    assert result.current_turn == 2
    assert result.own_request != ledger.own_request
    assert ledger.known_sets[0].moves == ("woodhammer",)
    assert result.matches_current_public_projection(later)


def test_quantitative_evidence_remains_exact_not_hp_or_speed_inference():
    ledger = PublicConstraintLedger.from_public_view(view())
    assert set(record.kind for record in ledger.records) == {
        "public_event_delta",
        "public_execution_delta",
        "opponent_last_actions",
    }
    event = next(x for x in ledger.records if x.kind == "public_event_delta")
    assert '"76/100"' in event.payload
    assert '"-enditem"' in event.payload
    assert event.source_turn == 1
    assert not hasattr(ledger, "speed_bounds")
    assert not hasattr(ledger, "damage_stat_bounds")


def test_repeated_last_turn_evidence_is_not_fabricated_as_new_evidence():
    ledger = PublicConstraintLedger.from_public_view(view())
    repeated = view(turn=2)
    assert ledger.advance(repeated).records == ledger.records
    assert ledger.advance(repeated).advance(repeated).records == ledger.records
    changed = view(turn=2, event_hp="75/100")
    assert len(ledger.advance(changed).records) == len(ledger.records) + 1


def test_no_change_can_silently_relax_exact_own_request_or_public_projection():
    current = view()
    ledger = PublicConstraintLedger.from_public_view(current)
    changed = deepcopy(current)
    changed["request"]["own_hp"] -= 1
    assert not ledger.matches_current_public_projection(changed)
    changed = deepcopy(current)
    changed["opponent"]["active"][0]["hp_percent"] = 69
    assert not ledger.matches_current_public_projection(changed)


def test_roster_change_or_turn_rewind_is_rejected_without_mutation():
    ledger = PublicConstraintLedger.from_public_view(view(turn=3))
    with pytest.raises(ValueError, match="rewind"):
        ledger.advance(view(turn=2))
    reordered = view(turn=4)
    reordered["opponent"]["preview_species"] = ["Sneasler", "Rillaboom"]
    with pytest.raises(ValueError, match="preview roster"):
        ledger.advance(reordered)
    assert ledger.current_turn == 3


def test_unsupported_public_mechanics_evidence_is_retained():
    current = view()
    current["public_event_delta"] = {
        "turn": 1, "events": [], "unsupported": ["-futuremove"],
    }
    ledger = PublicConstraintLedger.from_public_view(current)
    evidence = [record for record in ledger.records if record.kind == "public_event_delta"]
    assert len(evidence) == 1
    assert '"-futuremove"' in evidence[0].payload


def test_history_capacity_fails_closed(monkeypatch):
    from champions_practice import current_state_constraints as module

    ledger = PublicConstraintLedger.from_public_view(view())
    later = view(turn=2, event_hp="75/100")
    monkeypatch.setattr(module, "MAX_PUBLIC_EVIDENCE_RECORDS", len(ledger.records))
    with pytest.raises(ValueError, match="capacity exceeded"):
        ledger.advance(later)
    assert len(ledger.records) == 3


def test_invalid_public_view_rejected_by_producer_authority(monkeypatch):
    monkeypatch.setattr(
        "champions_practice.current_state_constraints."
        "public_reachability_observation_issue",
        lambda _view: "$.opponent.private: unexpected field",
    )
    with pytest.raises(ValueError, match="non-public view"):
        PublicConstraintLedger.from_public_view(view())
