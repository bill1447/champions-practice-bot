from copy import deepcopy

import pytest

from champions_practice.tactical_objective import Objective, rerank


def candidate(action, scores, *, second=None):
    def world(name, values):
        return {'world': name, 'weight': 1, 'sampled_responses': {
            str(i): {'leaf_utility': v, 'leaf_breakdown': {'total': v, 'terminal': 0,
                'material': v-10, 'position': 8, 'speed': 2, 'hp': 5, 'living': v-15}}
            for i, v in enumerate(values)}}
    return {'action': action, 'worlds': [world('a', scores), world('b', second if second is not None else scores)]}


def test_minimum_and_moderate_downside_have_different_risk_preferences():
    matrix = [candidate('safe', [0, 0, 0]), candidate('risk', [-80, 100, 100])]
    assert rerank(matrix, Objective('min'))[0]['action'] == 'safe'
    assert rerank(matrix, Objective('mean', 0))[0]['action'] == 'risk'
    assert rerank(matrix, Objective('mixed', .25))[0]['action'] == 'risk'
    assert rerank(matrix, Objective('mixed', .75))[0]['action'] == 'safe'


def test_world_aggregation_is_independent_of_response_aggregation():
    matrix = [candidate('safe', [0]), candidate('uncertain', [-10], second=[100])]
    assert rerank(matrix, Objective('min'))[0]['action'] == 'safe'
    assert rerank(matrix, Objective('world_mean', world_downside=0))[0]['action'] == 'uncertain'


def test_leaf_ablations_do_not_mutate_native_matrix():
    matrix = [candidate('a', [40])]
    saved = deepcopy(matrix)
    assert rerank(matrix, Objective('base'))[0]['utility'] == 40
    assert rerank(matrix, Objective('position', leaf='no_position'))[0]['utility'] == 32
    assert rerank(matrix, Objective('material', leaf='material_only'))[0]['utility'] == 30
    assert matrix == saved


def test_invalid_or_incomplete_objectives_are_rejected():
    with pytest.raises(ValueError):
        Objective('bad', -1)
    with pytest.raises(ValueError):
        Objective('bad', float('nan'))
    with pytest.raises(ValueError):
        rerank([], Objective('min'))


def test_existing_tie_order_is_preserved():
    assert rerank([candidate('b', [0]), candidate('a', [0])], Objective('min'))[0]['action'] == 'b'
