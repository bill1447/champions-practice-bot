import json
from types import SimpleNamespace

import pytest

from champions_practice.present_mechanics import opening_terrain_plan, public_trick_room_plan
from champions_practice.public_lifecycle import public_opponent_mega_plan, public_trace_plan


def fixture(turn_events, *, terrain=None, trick_room=False):
    opening = {"phase": "move", "terrain": terrain,
               "active_species": {"player": ["Gardevoir", "Indeedee-F"],
                                  "opponent": ["Gardevoir", "Rillaboom"]}}
    snapshots = [(1, json.dumps(opening))]
    for turn, events in enumerate(turn_events, 1):
        snapshots.append((turn + 1, json.dumps({**opening, "public_event_delta": {
            "turn": turn, "events": events, "unsupported": [],
        }})))
    view = {"turn": len(turn_events) + 1, "phase": "move",
            "field": {"terrain": terrain, "pseudo_weather": ["trickroom"] if trick_room else []},
            "player": {"active_details": [{"species": "Gardevoir", "fainted": False}]},
            "opponent": {"active": [{"species": "Gardevoir", "fainted": False}]}}
    ledger = SimpleNamespace(current_turn=view["turn"], field_snapshots=tuple(snapshots), records=())
    return view, ledger


TRACE = ["-ability", "p1a", "psychicsurge", "trace", "[from]:ability:trace", "[of]:p2b"]
TERRAIN = ["-fieldstart", "move:psychicterrain", "[from]:ability:psychicsurge", "[of]:p1a"]
ROOM = ["-fieldstart", "move:trickroom", "[of]:p2b"]
UPKEEP = ["upkeep"]


def test_trace_activation_proof_survives_mega_but_current_copy_ends():
    view, ledger = fixture([[TRACE, TERRAIN, UPKEEP],
                            [["-mega", "p1a", "gardevoir", "gardevoirite"], UPKEEP]], terrain="psychicterrain")
    view["opponent"]["active"][0]["species"] = "Gardevoir-Mega"
    assert opening_terrain_plan(view, ledger)["source_origin_ability"] == "trace"
    assert public_trace_plan(view, ledger) == []
    assert public_opponent_mega_plan(view, ledger) == [{"species": "gardevoir", "item": "gardevoirite"}]


def test_switch_discards_copy_and_does_not_lend_origin_to_new_occupant():
    view, ledger = fixture([[TRACE, ["switch", "p1a", "rillaboom"],
                            ["-fieldstart", "move:grassyterrain", "[from]:ability:grassysurge", "[of]:p1a"], UPKEEP]],
                           terrain="grassyterrain")
    view["opponent"]["active"][0]["species"] = "Rillaboom"
    assert public_trace_plan(view, ledger) == []
    assert "source_origin_ability" not in opening_terrain_plan(view, ledger)


@pytest.mark.parametrize("invalid", [
    TRACE[:-1], TRACE[:-1] + ["[of]:p1b"],
    ["-ability", "p1a", "slowstart", "trace", "[from]:ability:trace", "[of]:p2b"],
])
def test_unproven_or_timed_trace_copy_does_not_authorize_state(invalid):
    view, ledger = fixture([[invalid, UPKEEP]])
    assert public_trace_plan(view, ledger) is None


def test_current_trace_copy_is_exact_public_ability():
    view, ledger = fixture([[TRACE, UPKEEP]])
    assert public_trace_plan(view, ledger) == [
        {"side": "opponent", "slot": 0, "species": "Gardevoir", "ability": "psychicsurge"}]


@pytest.mark.parametrize("age", range(1, 5))
def test_trick_room_counts_completed_public_residuals(age):
    view, ledger = fixture([[ROOM, UPKEEP]] + [[UPKEEP]] * (age - 1), trick_room=True)
    assert public_trick_room_plan(view, ledger) == {
        "source_side": "player", "source_species": "Indeedee-F", "residual_turns": age}


def test_trick_room_restart_uses_latest_start_and_keeps_original_source_identity():
    view, ledger = fixture([[ROOM, UPKEEP], [["-fieldend", "move:trickroom"], UPKEEP],
        [ROOM, ["switch", "p2b", "rillaboom"], UPKEEP]], trick_room=True)
    assert public_trick_room_plan(view, ledger)["residual_turns"] == 1
    assert public_trick_room_plan(view, ledger)["source_species"] == "Indeedee-F"


@pytest.mark.parametrize("events", [
    [[UPKEEP]], [[ROOM]], [[ROOM + ["[persistent]"], UPKEEP]],
    [[ROOM[:-1] + ["[of]:p2c"], UPKEEP]],
    [[ROOM, UPKEEP], [["-fieldend", "move:trickroom"], UPKEEP]],
    [[ROOM, UPKEEP]] + [[UPKEEP]] * 4,
])
def test_unknown_extended_ended_or_expired_trick_room_is_not_admitted(events):
    view, ledger = fixture(events, trick_room=True)
    assert public_trick_room_plan(view, ledger) is None


def test_current_replacement_boundary_counts_current_trick_room_residual():
    view, ledger = fixture([[UPKEEP]], trick_room=True)
    delta = {"turn": view["turn"], "events": [ROOM, UPKEEP], "unsupported": []}
    view.update(phase="switch", public_event_delta=delta)
    snapshot = json.loads(ledger.field_snapshots[-1][1])
    snapshot.update(phase="switch", public_event_delta=delta)
    ledger.field_snapshots += ((view["turn"], json.dumps(snapshot)),)
    assert public_trick_room_plan(view, ledger)["residual_turns"] == 1
