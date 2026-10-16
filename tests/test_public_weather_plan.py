from copy import deepcopy
from types import SimpleNamespace
import json

from champions_practice.present_mechanics import public_weather_plan


def fixture(events, weather="raindance", turn=2):
    view = {"turn": turn, "phase": "move", "field": {"weather": weather}}
    opening = {"weather": weather, "phase": "move",
               "active_species": {"opponent": ["Pelipper", "Dragonite"]}}
    current = {"weather": weather, "phase": "move", "public_event_delta": {
        "turn": turn-1, "events": events, "unsupported": []}}
    ledger = SimpleNamespace(current_turn=turn, field_snapshots=(
        (1, json.dumps(opening)), (turn, json.dumps(current))))
    return view, ledger


def test_continuous_opening_weather_uses_complete_public_boundaries():
    view, ledger = fixture([["-weather", "raindance", "[upkeep]"], ["upkeep"]])
    before = deepcopy(view)
    assert public_weather_plan(view, ledger) == {"weather": "raindance", "residual_turns": 1}
    assert view == before
    view, ledger = fixture([["-weather", "raindance", "[upkeep]"]])
    assert public_weather_plan(view, ledger) is None


def test_public_weather_restart_resets_age_after_upkeep():
    view, ledger = fixture([["upkeep"], ["switch", "p1a", "pelipper"],
        ["-weather", "raindance", "[from]:ability:drizzle", "[of]:p1a"]])
    assert public_weather_plan(view, ledger) == {"weather": "raindance", "residual_turns": 0,
        "source_side": "opponent", "source_species": "pelipper", "source_ability": "drizzle"}


def test_unknown_source_end_or_extension_change_stays_unsupported():
    for events in (
        [["-weather", "raindance"], ["upkeep"]],
        [["-weather", "none"], ["upkeep"]],
        [["-enditem", "p1a", "damprock"], ["upkeep"]],
    ):
        view, ledger = fixture(events)
        assert public_weather_plan(view, ledger) is None


def test_partial_history_or_unknown_weather_cannot_guess_timer():
    view, ledger = fixture([["upkeep"]], turn=3)
    assert public_weather_plan(view, ledger) is None
    view, ledger = fixture([["upkeep"]], weather="sunnyday")
    assert public_weather_plan(view, ledger) is None


def test_opening_candidates_are_public_identities_not_an_inferred_setter():
    view, ledger = fixture([['upkeep']])
    initial = json.loads(ledger.field_snapshots[0][1])
    initial['active_species']['player'] = ['Rotom-Wash', 'Metagross']
    ledger.field_snapshots = ((1, json.dumps(initial)), ledger.field_snapshots[1])
    plan = public_weather_plan(view, ledger)
    assert plan['opening_sources'] == [
        {'source_side': 'player', 'source_species': 'Rotom-Wash'},
        {'source_side': 'player', 'source_species': 'Metagross'},
        {'source_side': 'opponent', 'source_species': 'Pelipper'},
        {'source_side': 'opponent', 'source_species': 'Dragonite'}]
    assert 'source_species' not in plan
    # A first observation after a turn-one action is not an opening witness.
    initial['public_event_delta'] = {'turn': 1, 'events': [['move', 'p1a', 'protect']], 'unsupported': []}
    ledger.field_snapshots = ((1, json.dumps(initial)), ledger.field_snapshots[1])
    partial = public_weather_plan(view, ledger)
    assert partial is None or 'opening_sources' not in partial
    view, ledger = fixture([['upkeep'], ['upkeep']])
    assert public_weather_plan(view, ledger) is None
