from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from champions_practice.belief_controller import BeliefDecisionEngine
from champions_practice.present_mechanics import (
    PROTECTION_CHAIN_MOVES,
    unsupported_present_mechanics,
    opening_terrain_plan,
)


def test_continuous_opening_terrain_recovers_gate_without_counter_input():
    current = view()
    current["turn"] = 3
    current["public_execution_delta"]["turn"] = 2
    current["field"]["terrain"] = "psychicterrain"
    payload = json.dumps(current["field"])
    ledger = SimpleNamespace(current_turn=3, records=(), field_snapshots=(
        (1, payload), (2, payload), (3, payload),
    ))
    assert opening_terrain_plan(current, ledger) == {
        "opening_terrain": "psychicterrain", "residual_turns": 2,
    }
    assert unsupported_present_mechanics(current, ledger) is None
    ledger.field_snapshots = ((1, payload), (3, payload))
    assert unsupported_present_mechanics(current, ledger) == "unsupported-public-effect-duration"


def test_terrain_restart_or_unsupported_events_do_not_authorize_age():
    current = view()
    current["turn"] = 2
    current["field"]["terrain"] = "psychicterrain"
    payload = json.dumps(current["field"])
    ledger = SimpleNamespace(current_turn=2, field_snapshots=((1, payload), (2, payload)),
        records=(SimpleNamespace(kind="public_event_delta", payload=json.dumps({
            "events": [["-fieldstart", "move:psychicterrain"]], "unsupported": [],
        })),))
    assert opening_terrain_plan(current, ledger) is None


def test_public_ability_start_restores_changed_terrain_age():
    current = view()
    current["turn"] = 2
    current["public_execution_delta"]["turn"] = 1
    current["field"]["terrain"] = "grassyterrain"
    snapshot = {**current["field"], "phase": "move", "active_species": {"opponent": ["Rillaboom", None]},
        "public_event_delta": {"turn": 1, "events": [["switch", "p1a", "rillaboom"], ["-fieldstart", "move:grassyterrain",
            "[from]:ability:grassysurge", "[of]:p1a"]], "unsupported": []}}
    ledger = SimpleNamespace(current_turn=2, records=(), field_snapshots=(
        (1, json.dumps({"terrain": "psychicterrain"})), (2, json.dumps(snapshot)),
    ))
    assert opening_terrain_plan(current, ledger) == {
        "opening_terrain": "grassyterrain", "residual_turns": 1,
        "source_side": "opponent", "source_species": "rillaboom",
        "source_ability": "grassysurge",
    }
    assert unsupported_present_mechanics(current, ledger) is None


def test_native_cant_does_not_refresh_protection_chain():
    current = view()
    current["public_execution_delta"]["actions"] = [{
        "outcome": "prevented", "reason": "flinch", "attempted_move": None,
    }]
    assert unsupported_present_mechanics(current) is None


def view():
    return {
        "turn": 8,
        "field": {"weather": None, "terrain": None, "pseudo_weather": []},
        "player": {"side_conditions": []}, "opponent": {"side_conditions": []},
        "public_execution_delta": {
            "turn": 7, "actions": [{"outcome": "executed", "move": "psychic"}],
        },
    }


@pytest.mark.parametrize("field,effect", [
    ("weather", "raindance"), ("terrain", "psychicterrain"),
    ("pseudo_weather", ["trickroom"]),
])
def test_current_projection_does_not_authorize_timer(field, effect):
    current = view()
    current["field"][field] = effect
    before = deepcopy(current)
    assert unsupported_present_mechanics(current) == "unsupported-public-effect-duration"
    assert current == before


@pytest.mark.parametrize("side", ["player", "opponent"])
@pytest.mark.parametrize("effect", ["tailwind", "reflect", "unknown"])
def test_side_conditions_need_independent_native_support(side, effect):
    current = view()
    current[side]["side_conditions"] = [effect]
    assert unsupported_present_mechanics(current) == "unsupported-public-effect-duration"


@pytest.mark.parametrize("move", sorted(PROTECTION_CHAIN_MOVES))
@pytest.mark.parametrize("outcome", ["executed", "prevented"])
def test_protection_family_is_not_reset_by_fresh_opening(move, outcome):
    current = view()
    current["public_execution_delta"]["actions"] = [{
        "outcome": outcome,
        "move" if outcome == "executed" else "attempted_move": move,
        "source": "called", "effects": ["-fail"],
    }]
    assert unsupported_present_mechanics(current) == "unsupported-public-protection-chain"


@pytest.mark.parametrize("delta", [
    None, {}, {"turn": 6, "actions": [{"outcome": "executed", "move": "psychic"}]},
    {"turn": True, "actions": []}, {"turn": 7, "actions": []},
    {"turn": 7, "actions": [{"outcome": "prevented", "attempted_move": None}]},
])
def test_missing_or_retained_execution_is_not_negative_evidence(delta):
    current = view()
    current["public_execution_delta"] = delta
    assert unsupported_present_mechanics(current) == "unsupported-public-protection-history"


def test_supported_projection_keeps_search_eligible_without_mutation():
    current = view()
    before = deepcopy(current)
    assert unsupported_present_mechanics(current) is None
    assert before == current


@pytest.mark.parametrize("issue", ["terrain", "protect", "history"])
def test_live_decision_gate_discards_stale_particles_and_never_spawns_worker(issue):
    current = view()
    if issue == "terrain":
        current["field"]["terrain"] = "psychicterrain"
    elif issue == "protect":
        current["public_execution_delta"]["actions"][0]["move"] = "protect"
    else:
        current["public_execution_delta"]["turn"] = 6
    bot = BeliefDecisionEngine(".", battle_format="test", ai_team="own", opponent_priors={})
    bot._public_ai_preview_choice = "team 1234"
    bot.last_public_view = current
    bot.public_constraint_ledger = SimpleNamespace(current_turn=8, current_signature="view")
    bot.particles = (SimpleNamespace(world_id="stale"),)

    def no_worker(*args, **kwargs):
        raise AssertionError("unsafe fresh worlds must be rejected before worker startup")

    bot._run_until_deadline = no_worker
    choices = ["move psychic +1", "move protect"]
    decision = bot.choose_ai_action(legal_live=choices)
    assert decision.mode == "fallback"
    assert decision.choice in choices
    assert decision.fallback_reason == "fresh-public-world:" + unsupported_present_mechanics(
        current
    )
    assert bot.particles == ()
