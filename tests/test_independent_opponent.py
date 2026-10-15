from copy import deepcopy
import random

import pytest

from champions_practice.independent_opponent import IndependentOpponent, make_battle


@pytest.fixture
def sample():
    stats = {s: 80 for s in ('hp', 'atk', 'def', 'spa', 'spd', 'spe')}
    species = {name: {'name': name, 'baseSpecies': name, 'baseStats': stats,
        'types': [kind], 'abilities': {'0': 'None'}, 'heightm': 1, 'weightkg': 10}
        for name, kind in [('charmander', 'Fire'), ('squirtle', 'Water'),
                           ('bulbasaur', 'Grass'), ('pikachu', 'Electric')]}
    moves = {name: {'name': name, 'basePower': 40, 'type': kind, 'category': 'Special',
        'accuracy': 100, 'pp': 10, 'priority': 0, 'target': 'normal', 'flags': {}}
        for name, kind in [('ember', 'Fire'), ('watergun', 'Water')]}
    dex = {'species': species, 'moves': moves}
    own = []
    for name, move in [('charmander', 'ember'), ('squirtle', 'watergun')]:
        own.append({'ident': 'p1: '+name, 'details': name+', L50', 'condition': '100/100',
            'active': True, 'baseAbility': 'none', 'ability': 'none', 'item': '',
            'moves': [move], 'stats': {s: 100 for s in ('atk', 'def', 'spa', 'spd', 'spe')}})
    view = {'turn': 1, 'phase': 'move', 'player': {'name': 'P1',
        'active_details': [{'species': m['ident'][4:], 'boosts': {}} for m in own], 'side_conditions': []},
        'opponent': {'active': [{'species': 'bulbasaur', 'hp_percent': 57.5},
                                {'species': 'pikachu', 'hp_percent': 100}], 'revealed': []},
        'request': {'side': {'id': 'p1', 'pokemon': own}, 'active': [
            {'moves': [{'id': 'ember', 'target': 'normal'}]},
            {'moves': [{'id': 'watergun', 'target': 'normal'}]}]}, 'field': {}}
    choices = [f'move ember +{a}, move watergun +{b}' for a in (1, 2) for b in (1, 2)]
    return dex, view, choices


def test_external_policy_private_input_invariance_and_rng_isolation(sample):
    dex, view, choices = sample
    expected = IndependentOpponent(dex, 123).choose(view, choices)
    poisoned = deepcopy(view)
    poisoned.update({'state': {'secret': True}, 'rng': 'secret', 'enemy_action': 'secret'})
    poisoned['request']['secret'] = {'hidden': True}
    for mon in poisoned['opponent']['active']:
        mon.update(stats={'atk': 99999}, hp=1, maxhp=99999, item='secret',
                   ability='secret', moves=['secret'], speed=99999, locked_move='secret')
    saved = random.getstate()
    assert IndependentOpponent(dex, 123).choose(poisoned, choices) == expected
    assert random.getstate() == saved
    assert expected[0] in choices and not expected[1]['fallback']
    battle, _ = make_battle(poisoned, choices, dex)
    assert not battle._last_request
    assert all(all(v is None for v in mon.stats.values()) for mon in battle.opponent_active_pokemon)
    assert battle.opponent_active_pokemon[0].current_hp_fraction == pytest.approx(.575)


def test_adapter_side_symmetry(sample):
    dex, view, choices = sample
    flipped = deepcopy(view)
    flipped['request']['side']['id'] = 'p2'
    for entry in flipped['request']['side']['pokemon']:
        entry['ident'] = entry['ident'].replace('p1:', 'p2:')
    assert IndependentOpponent(dex, 8).choose(view, choices) == IndependentOpponent(dex, 8).choose(flipped, choices)


def test_champions_public_base_stats_override_vanilla(sample):
    dex, view, choices = sample
    dex['species']['charmander']['baseStats'] = {'hp': 100, 'atk': 130, 'def': 140,
                                               'spa': 150, 'spd': 160, 'spe': 170}
    battle, _ = make_battle(view, choices, dex)
    assert battle.active_pokemon[0].base_stats['spa'] == 150
    assert battle.active_pokemon[0].stats['spa'] == 100  # Own request stats stay authoritative.


def test_invalid_upstream_proposal_is_explicit_legal_fallback(sample, monkeypatch):
    dex, view, choices = sample
    bot = IndependentOpponent(dex, 5)
    monkeypatch.setattr(type(bot.policy), 'choose_move', lambda *_: None)
    action, trace = bot.choose(view, choices)
    assert action in choices and trace['fallback'] and trace['fallback_reason']


def test_public_trick_room_maps_to_upstream_field(sample):
    from poke_env.battle.field import Field
    dex, view, choices = sample
    view['field'] = {'pseudo_weather': ['trickroom'], 'terrain': 'psychicterrain'}
    battle, _ = make_battle(view, choices, dex)
    assert Field.TRICK_ROOM in battle.fields and Field.PSYCHIC_TERRAIN in battle.fields
    assert Field.UNKNOWN not in battle.fields
