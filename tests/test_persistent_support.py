"""Closed-contract adversarial inputs; native outcomes run separately in CI."""

from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from champions_practice.persistent_support import (
    public_support_contract,
    public_active_tenure_plan,
    static_support_issue,
    current_capability_issue,
)
from champions_practice.persistent_admission_smoke import fixture, SPECIES
from champions_practice.present_rebase import _positive_mechanics_rejection


def evidence(events=()):
    events = list(events)
    if ["upkeep"] not in events:
        events.append(["upkeep"])
    own = {"species": "Incineroar", "base_species": "Incineroar", "fainted": False, "status": None}
    foe = {**own, "hp_percent": 100, "boosts": {}}
    view = {
        "turn": 2,
        "phase": "move",
        "field": {"weather": None, "terrain": None, "pseudo_weather": []},
        "player": {"team": [own], "active_details": [own], "side_conditions": []},
        "opponent": {
            "active": [foe],
            "revealed": [],
            "side_conditions": [],
            "preview_species": ["Incineroar"],
            "name": "Human",
        },
    }
    snapshots = (
        (
            1,
            json.dumps(
                {
                    "phase": "move",
                    "active_species": {"player": ["Incineroar"], "opponent": ["Incineroar"]},
                    "public_event_delta": {"turn": None, "events": [], "unsupported": []},
                }
            ),
        ),
        (
            2,
            json.dumps(
                {
                    "phase": "move",
                    "public_event_delta": {"turn": 1, "events": events, "unsupported": []},
                }
            ),
        ),
    )
    return view, SimpleNamespace(current_turn=2, field_snapshots=snapshots)


@pytest.mark.parametrize(
    "effect",
    [
        "encore",
        "taunt",
        "imprison",
        "substitute",
        "confusion",
        "saltcure",
        "perishsong",
        "ability:flashfire",
        "futurecounter",
    ],
)
def test_unrestored_and_unknown_public_volatiles_are_unresolved(effect):
    view, ledger = evidence([["-start", "p1a", effect]])
    contract = public_support_contract(view, ledger)
    assert contract.unresolved_reason == "unsupported-persistent:volatile:" + effect.removeprefix(
        "ability:"
    )
    assert any(entry.classification == "unresolved" for entry in contract.mechanics)


@pytest.mark.parametrize("status", ["slp", "tox", "futurestatus"])
def test_status_counters_are_unresolved_on_either_side_and_bench(status):
    view, ledger = evidence()
    view["player"]["team"].append({"species": "Metagross", "status": status})
    assert (
        public_support_contract(view, ledger).unresolved_reason
        == "unsupported-persistent:status:" + status
    )


def test_no_history_is_not_absence_evidence():
    view, _ = evidence()
    contract = public_support_contract(view, None)
    assert contract.unresolved_reason == "unsupported-persistent:history"
    assert not any(entry.classification == "absent" for entry in contract.mechanics)


def test_tenure_tracks_prevention_switch_and_post_upkeep_entry():
    view, ledger = evidence([["cant", "p1a", "flinch"], ["move", "p2a", "protect"]])
    plan = public_active_tenure_plan(view, ledger)
    assert all(entry["move_actions"] == 1 and entry["active_turns"] == 2 for entry in plan)
    view, ledger = evidence(
        [["move", "p1a", "protect"], ["upkeep"], ["switch", "p1a", "incineroar"]]
    )
    assert public_active_tenure_plan(view, ledger)[1]["move_actions"] == 0
    assert public_active_tenure_plan(view, ledger)[1]["active_turns"] == 1


def test_missing_upkeep_and_called_moves_do_not_authorize_counts():
    view, ledger = evidence([["move", "p1a", "protect", "[from]:move:metronome"]])
    assert public_active_tenure_plan(view, ledger) is None
    view, ledger = evidence()
    turn, payload = ledger.field_snapshots[-1]
    payload = json.loads(payload)
    payload["public_event_delta"]["events"] = []
    ledger.field_snapshots = (*ledger.field_snapshots[:-1], (turn, json.dumps(payload)))
    assert public_active_tenure_plan(view, ledger) is None


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"item": "Choice Band"}, "item:choiceband"),
        ({"item": "Choice Scarf"}, "item:choicescarf"),
        ({"item": "Choice Specs"}, "item:choicespecs"),
        ({"item": "Metronome"}, "item:metronome"),
        ({"ability": "Truant"}, "ability:truant"),
        ({"ability": "Unburden"}, "owned-unburden"),
        ({"ability": "Future Ability"}, "ability:futureability"),
        ({"moves": ["Stomping Tantrum"]}, "move:stompingtantrum"),
        ({"moves": ["Rage Fist"]}, "move:ragefist"),
        ({"moves": ["Last Resort"]}, "move:lastresort"),
        ({"moves": ["Encore"]}, "move:encore"),
        ({"moves": ["Future Move"]}, "move:futuremove"),
    ],
)
def test_unclassified_static_capabilities_fail_closed(changes, reason):
    facts = {"ability": "Inner Focus", "item": "", "moves": ["Protect"]}
    assert static_support_issue(**{**facts, **changes}) == "unsupported-persistent:" + reason


def test_unrevealed_choice_prior_cannot_be_dropped_by_bounded_sampling():
    _, priors = fixture()
    view, _ = evidence()
    mon = priors["Incineroar"][0]
    view["opponent"]["preview_species"] = list(SPECIES)
    view["player"]["team"] = [
        {
            "species": mon.species,
            "ability": mon.ability,
            "item": mon.item,
            "move_pp": [{"id": move} for move in mon.moves],
        }
    ]
    assert current_capability_issue(view, priors) is None
    mixed = {**priors, "Incineroar": (mon, replace(mon, item="Choice Band"))}
    assert current_capability_issue(view, mixed) == "unsupported-persistent:item:choiceband"
    assert (
        current_capability_issue(
            view, {**mixed, "Incineroar": tuple(reversed(mixed["Incineroar"]))}
        )
        == "unsupported-persistent:item:choiceband"
    )


def test_inventory_and_damaged_foe_bench_are_explicitly_unresolved():
    view, ledger = evidence([["-enditem", "p1a", "shucaberry", "[weaken]"]])
    assert (
        public_support_contract(view, ledger).unresolved_reason
        == "unsupported-persistent:opponent-inventory"
    )
    view, ledger = evidence()
    view["opponent"]["revealed"] = [
        {"species": "Metagross", "seen": True, "fainted": False, "status": None, "hp_percent": 50}
    ]
    assert (
        public_support_contract(view, ledger).unresolved_reason
        == "unsupported-persistent:opponent-bench"
    )


def test_projection_equality_cannot_bypass_contract():
    view, ledger = evidence([["-start", "p1a", "ability:flashfire"]])
    view["public_execution_delta"] = {
        "turn": 1,
        "actions": [{"outcome": "executed", "move": "psychic"}],
    }
    # Deliberately pass identical observations and menu; no native access is
    # necessary for the gate to reject a positively observed unsupported state.
    assert (
        _positive_mechanics_rejection(
            {},
            deepcopy(view),
            current_view=view,
            ledger=ledger,
            legal_live=("move protect",),
            hypothetical_legal=["move protect"],
        )
        == "unsupported-persistent:volatile:flashfire"
    )
