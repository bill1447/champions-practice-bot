from copy import deepcopy

from champions_practice.plan_feasibility import compare_routes


class Catalog:
    moves = {'expandingforce': {'power': 80, 'type': 'Psychic'},
             'hypervoice': {'power': 90, 'type': 'Normal'},
             'psychicfangs': {'power': 85, 'type': 'Psychic'}}

    def effectiveness(self, *_):
        return 1


def inputs():
    view = {'turn': 2, 'phase': 'move',
        'field': {'weather': None, 'terrain': 'psychicterrain', 'pseudo_weather': []},
        'player': {'side_conditions': [], 'team': [
            {'species': 'Gardevoir', 'hp_percent': 100, 'moves': ['Expanding Force', 'Hyper Voice'], 'item': 'gardevoirite', 'fainted': False},
            {'species': 'Metagross', 'hp_percent': 100, 'moves': ['Psychic Fangs'], 'fainted': False}]},
        'opponent': {'name': 'Foe', 'preview_species': ['Excadrill'], 'active': [], 'revealed': [], 'side_conditions': []}}
    gardevoir = {'species': 'Gardevoir', 'hp': 100, 'maxhp': 100, 'fainted': False, 'grounded': True}
    metagross = {**gardevoir, 'species': 'Metagross'}
    board = {'p2': {'name': 'Us', 'pokemon': [gardevoir, metagross], 'active': [metagross]},
        'p1': {'name': 'Foe', 'pokemon': [], 'active': []}, 'field': {'terrain': 'grassyterrain'},
        'ended': False, 'winner': None}
    board['ownMegaAvailability'] = {'gardevoir': False, 'metagross': False}
    ranking = [{'action': 'test', 'worst_world_utility': 37,
                'worlds': [{'sampled_responses': {'reply': {'leaf_positions': [board]}}}]}]
    return view, ranking


def test_living_centerpiece_is_not_certified_as_an_attacking_window():
    view, ranking = inputs()
    saved = deepcopy(ranking)
    report = compare_routes(ranking, view, Catalog(), side='p2')
    assert ranking == saved
    comparison = report['comparisons'][0]
    assert comparison['existing_utility'] == 37
    gardevoir = next(p for p in comparison['routes'] if p['resource'] == 'Gardevoir')
    assert gardevoir['living_samples'] == 1 and gardevoir['active_samples'] == 0
    assert gardevoir['terrain_ready_samples'] == 0
    assert gardevoir['mega_fairy_available_or_evolved_samples'] == 0
    assert gardevoir['assessment'].startswith('route unresolved')
    assert 'chosen_plan' not in report


def test_failed_original_resource_does_not_discard_alternative_or_material_route():
    view, ranking = inputs()
    ranking[0]['worlds'][0]['sampled_responses']['reply']['leaf_positions'][0]['p2']['pokemon'][0].update(hp=0, fainted=True)
    report = compare_routes(ranking, view, Catalog(), side='p2')
    routes = report['comparisons'][0]['routes']
    assert next(p for p in routes if p['resource'] == 'Gardevoir')['living_samples'] == 0
    assert next(p for p in routes if p['resource'] == 'Metagross')['active_samples'] == 1
    assert any(p['resource'] is None for p in routes)
