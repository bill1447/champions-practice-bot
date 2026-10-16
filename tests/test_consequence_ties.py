from copy import deepcopy

from champions_practice.consequence_ties import order_exact_ties


def candidate(action, values, score=0):
    return {'action': action, 'worst_world_utility': score, 'weighted_utility': score,
            'worlds': [{'world': 'same-label', 'weight': 1,
                        'sampled_responses': {str(i): {'leaf_utility': v}
                                              for i, v in enumerate(values)}}]}


def test_exact_tie_prefers_dominator_without_mutating_evidence():
    rows = [candidate('protect', [0, 0, 1]), candidate('attack', [0, 2, 3])]
    before = deepcopy(rows)
    assert [r['action'] for r in order_exact_ties(rows)] == ['attack', 'protect']
    assert rows == before


def test_protect_is_retained_when_it_has_a_counterplay_advantage():
    rows = [candidate('protect', [0, 3, 1]), candidate('attack', [0, 2, 3])]
    assert order_exact_ties(rows) == rows


def test_primary_objective_even_a_tiny_difference_is_preserved():
    rows = [candidate('incumbent', [0, 0], 1e-12), candidate('other', [0, 9])]
    assert order_exact_ties(rows) == rows


def test_incomplete_or_nonfinite_vectors_do_not_establish_dominance():
    for values in ([0], [0, float('nan')], []):
        rows = [candidate('first', [0, 0]), candidate('other', values)]
        assert order_exact_ties(rows) == rows


def test_stable_frontiers_handle_chains_and_incomparable_choices():
    rows = [candidate('weak', [0, 0, 0]), candidate('middle', [0, 1, 1]),
            candidate('tradeoff', [0, 3, 0]), candidate('strong', [0, 2, 2])]
    assert [r['action'] for r in order_exact_ties(rows)] == ['tradeoff', 'strong', 'middle', 'weak']


def test_duplicate_world_labels_do_not_collapse_worlds():
    first, second = candidate('first', [0, 1]), candidate('second', [0, 2])
    first['worlds'].append(deepcopy(second['worlds'][0]))
    second['worlds'].append(deepcopy(candidate('third', [0, 0])['worlds'][0]))
    assert order_exact_ties([first, second]) == [first, second]
