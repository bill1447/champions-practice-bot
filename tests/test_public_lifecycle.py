import json
from types import SimpleNamespace

import pytest

from champions_practice.present_mechanics import opening_terrain_plan
from champions_practice.public_lifecycle import public_post_residual_switch, public_protection_plan


def fixture(events_by_turn, terrain=None):
    current = {"turn": len(events_by_turn) + 1, "field": {"terrain": terrain},
               "player": {"active_details": [{"species": "Sneasler", "fainted": False}]},
               "opponent": {"active": []}}
    opening = {"phase": "move", "terrain": terrain,
               "active_species": {"player": ["Sneasler"], "opponent": ["Rillaboom"]}}
    snapshots = [(1, json.dumps(opening))]
    for turn, events in enumerate(events_by_turn, 1):
        snapshots.append((turn + 1, json.dumps({**opening, "public_event_delta": {
            "turn": turn, "events": events, "unsupported": [],
        }})))
    return current, SimpleNamespace(current_turn=current["turn"], field_snapshots=tuple(snapshots), records=())


SUCCESS = [["move", "p2a", "protect"], ["-singleturn", "p2a", "protect"]]


@pytest.mark.parametrize("count", range(1, 9))
def test_consecutive_successes_cap_at_pinned_native_maximum(count):
    view, ledger = fixture([SUCCESS] * count)
    assert public_protection_plan(view, ledger)[0]["successes"] == min(count, 6)


@pytest.mark.parametrize("reset", [
    [["move", "p2a", "protect"], ["-fail", "p2a"]],
    [["cant", "p2a", "flinch"]], [["move", "p2a", "rockslide"]],
    [["switch", "p2a", "gardevoir"], ["switch", "p2a", "sneasler"]],
])
def test_failure_interruption_or_out_and_back_reset_chain(reset):
    view, ledger = fixture([SUCCESS, reset, SUCCESS])
    assert public_protection_plan(view, ledger)[0]["successes"] == 1


def test_called_protect_success_and_mixed_guard_family_share_stall():
    view, ledger = fixture([
        [["move", "p2a", "metronome"], *SUCCESS],
        [["move", "p2a", "wideguard"], ["-singleturn", "p2a", "wideguard"]],
    ])
    assert public_protection_plan(view, ledger)[0]["successes"] == 2


@pytest.mark.parametrize("events", [
    [["move", "p2a", "protect"]], [*SUCCESS, *SUCCESS],
    [["-singleturn", "p2a", "protect"]],
])
def test_unresolved_or_multiple_attempts_remain_unknown(events):
    view, ledger = fixture([events])
    assert public_protection_plan(view, ledger) is None


def test_partial_turn_cannot_certify_final_protection_or_source():
    view, ledger = fixture([SUCCESS])
    ledger.field_snapshots = ((1, ledger.field_snapshots[0][1]),
                             (1, ledger.field_snapshots[1][1]))
    assert public_protection_plan(view, ledger) is None


def test_terrain_source_identity_survives_later_slot_replacement():
    view, ledger = fixture([[
        ["-fieldstart", "move:grassyterrain", "[from]:ability:grassysurge", "[of]:p1a"],
        ["switch", "p1a", "sneasler"],
    ]], terrain="grassyterrain")
    assert opening_terrain_plan(view, ledger)["source_species"] == "Rillaboom"


def test_terrain_reactivation_keeps_ordered_identical_start_occurrences():
    grass = ["-fieldstart", "move:grassyterrain", "[from]:ability:grassysurge", "[of]:p1a"]
    view, ledger = fixture([[
        grass, ["switch", "p1a", "indeedeef"],
        ["-fieldstart", "move:psychicterrain", "[from]:ability:psychicsurge", "[of]:p1a"],
        ["switch", "p1a", "rillaboom"], grass,
    ]], terrain="grassyterrain")
    assert opening_terrain_plan(view, ledger)["source_species"] == "rillaboom"


def test_public_extender_loss_does_not_authorize_static_item_timer():
    view, ledger = fixture([[
        ["-enditem", "p1a", "terrainextender"],
        ["-fieldstart", "move:grassyterrain", "[from]:ability:grassysurge", "[of]:p1a"],
    ]], terrain="grassyterrain")
    assert opening_terrain_plan(view, ledger) is None


@pytest.mark.parametrize("end", [
    ["-fieldend", "move:grassyterrain"],
    ["-fieldstart", "move:psychicterrain", "[from]:ability:psychicsurge", "[of]:p1a"],
])
def test_final_projection_cannot_resurrect_ended_or_overwritten_terrain(end):
    view, ledger = fixture([[
        ["-fieldstart", "move:grassyterrain", "[from]:ability:grassysurge", "[of]:p1a"], end,
    ]], terrain="grassyterrain")
    assert opening_terrain_plan(view, ledger) is None


@pytest.mark.parametrize("after_upkeep,age", [(False, 1), (True, 0)])
def test_terrain_age_counts_residuals_after_activation_not_turn_labels(after_upkeep, age):
    start = ["-fieldstart", "move:grassyterrain", "[from]:ability:grassysurge", "[of]:p1a"]
    events = [["upkeep"], start] if after_upkeep else [start, ["upkeep"]]
    view, ledger = fixture([events], terrain="grassyterrain")
    assert opening_terrain_plan(view, ledger)["residual_turns"] == age


def test_post_residual_replacement_requires_explicit_current_boundary():
    view, ledger = fixture([SUCCESS + [["upkeep"]]])
    delta = {"turn": view["turn"], "events": SUCCESS + [["upkeep"]], "unsupported": []}
    view.update(phase="switch", public_event_delta=delta)
    snapshot = json.loads(ledger.field_snapshots[-1][1])
    snapshot.update(phase="switch", public_event_delta=delta)
    ledger.field_snapshots += ((view["turn"], json.dumps(snapshot)),)
    assert public_post_residual_switch(view)
    assert public_protection_plan(view, ledger)[0]["successes"] == 2
    delta["events"] = SUCCESS
    assert not public_post_residual_switch(view)
    assert public_protection_plan(view, ledger) is None
