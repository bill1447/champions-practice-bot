from copy import deepcopy

import pytest

from champions_practice.beliefs import PublicInformationLeak
from champions_practice.strategic_diagnostic import diagnose_match


class Catalog:
    moves = {'expandingforce': {'type': 'Psychic', 'power': 80},
             'hypervoice': {'type': 'Normal', 'power': 90},
             'mysticalfire': {'type': 'Fire', 'power': 75},
             'psychic': {'type': 'Psychic', 'power': 90}}

    def effectiveness(self, attack, species):
        if species == 'Excadrill':
            return {'Psychic': 0.5, 'Fairy': 0.5, 'Fire': 2}.get(attack, 1)
        if species == 'Tyranitar':
            return {'Psychic': 0, 'Fairy': 2}.get(attack, 1)
        return 1


def view():
    return {'turn': 1, 'phase': 'move',
        'field': {'terrain': 'psychicterrain', 'weather': 'sandstorm', 'pseudo_weather': []},
        'player': {'side_conditions': [], 'team': [
            {'species': 'Gardevoir', 'moves': ['Expanding Force', 'Hyper Voice', 'Mystical Fire', 'Protect'],
             'item': 'gardevoirite', 'hp_percent': 100, 'active': True, 'fainted': False},
            {'species': 'Indeedee-F', 'moves': ['Psychic', 'Follow Me', 'Trick Room'],
             'ability': 'psychicsurge', 'hp_percent': 100, 'active': True, 'fainted': False}]},
        'opponent': {'preview_species': ['Tyranitar', 'Excadrill'], 'side_conditions': [],
            'active': [{'species': 'Excadrill', 'base_species': 'Excadrill',
                        'hp_percent': 100, 'fainted': False, 'boosts': {}}], 'revealed': []}}


def test_conditions_counterplan_and_answers_stay_conditional():
    current = view()
    saved = deepcopy(current)
    report = diagnose_match(current, Catalog())
    assert current == saved
    assert report['anchor'] == 'Gardevoir'
    blocker = next(b for b in report['blockers'] if b['species'] == 'Excadrill')
    assert blocker['resisted_attack_types'] == ['Fairy', 'Psychic']
    assert 'Gardevoir: mysticalfire' in blocker['possible_answers']
    dark = next(b for b in report['blockers'] if b['species'] == 'Tyranitar')
    assert dark['typing_multipliers']['Psychic'] == 0
    assert 'Gardevoir: hypervoice' in dark['possible_answers']
    assert report['opponent_plans'][0]['status'] == 'hypothesis'
    assert 'unverified' in report['opponent_plans'][0]['unknowns']
    assert next(r for r in report['requirements'] if r['name'] == 'favorable speed order')['state'] == 'unverified'
    assert report['plan']['acceptable_losses'] == ()


def test_reassessment_preserves_identity_through_mega_and_replans_after_faint():
    current = view()
    first = diagnose_match(current, Catalog())
    current['player']['team'][0].update(species='Gardevoir-Mega', hp_percent=10)
    second = diagnose_match(current, Catalog(), previous=first)
    assert second['anchor'] == 'Gardevoir-Mega'
    assert second['update'] == 'retained living anchor'
    current['player']['team'][0].update(fainted=True, hp_percent=0)
    third = diagnose_match(current, Catalog(), previous=second)
    assert third['anchor'] == 'Indeedee-F'
    assert third['update'].startswith('replan:')


def test_terrain_loss_changes_objective_without_inventing_an_action():
    current = view()
    current['field']['terrain'] = 'grassyterrain'
    report = diagnose_match(current, Catalog())
    assert next(r for r in report['requirements'] if r['name'].startswith('Psychic Terrain'))['state'] == 'missing'
    assert 'Compare restoring Psychic Terrain' in report['current_objective']
    assert 'action' not in report
    assert 'named payoff' in report['defense_rule']


def test_rejects_private_opponent_data_and_does_not_claim_preview_selection():
    current = view()
    current['opponent']['active'][0]['item'] = 'lifeorb'
    with pytest.raises(PublicInformationLeak):
        diagnose_match(current, Catalog())
    current = view()
    current['opponent']['active'] = []
    report = diagnose_match(current, Catalog())
    assert report['blockers'][0]['presence'] == 'preview possibility'


def test_all_attackers_lost_yields_no_unsupported_win_condition():
    current = view()
    for mon in current['player']['team']:
        mon.update(fainted=True, hp_percent=0)
    report = diagnose_match(current, Catalog())
    assert report['anchor'] is None
    assert report['requirements'][0]['state'] == 'failed'
    assert report['plan']['required_resources'] == ()
