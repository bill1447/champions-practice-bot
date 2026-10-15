from dataclasses import replace
from copy import deepcopy
from time import perf_counter

import pytest

from champions_practice.agent_v2.policy import PublicCatalog
from champions_practice.belief_search import ExactBeliefWorldState
from champions_practice.tactical_consequences import TacticalLimits, evaluate_consequences, observation_key


def summary(turn, own=2, foe=2):
    def team(count):
        mons = [{'hp': 100 if i < count else 0, 'maxhp': 100, 'fainted': i >= count} for i in range(2)]
        return {'name': 'P', 'pokemon': mons, 'active': []}
    return {'turn': turn, 'p1': team(own), 'p2': team(foe), 'field': {}, 'ended': False}


class Worker:
    def __init__(self, transition, menu):
        self.transition, self.menu = transition, menu
        self.calls = []

    def state_view(self, *, state, side):
        return {'turn': state['turn'], 'phase': state.get('phase', 'move'), 'ended': False,
            'field': {}, 'request': {}, 'player': {'team': [], 'active_details': []},
            'opponent': {'active': [], 'revealed': []}}

    def legal_choices(self, *, state, side):
        return self.menu(state) if side == 'p1' else ['wait']

    def branch_many(self, *, state, branches):
        result = []
        for branch in branches:
            self.calls.append((state, branch))
            next_state, score = self.transition(state, branch['p1_choice'])
            result.append({'state': next_state, 'summary': score})
        return result


@pytest.fixture
def catalog():
    return PublicCatalog({'moves': {}, 'species': {}, 'types': {}})


def run(worker, catalog, states, menu, **kwargs):
    return evaluate_consequences(worker, worlds=tuple(ExactBeliefWorldState(s, 1, str(i)) for i, s in enumerate(states)),
        side='p1', authoritative_actions=menu, incumbent=menu[0], catalog=catalog,
        deadline=perf_counter()+5, limits=kwargs.pop('limits', TacticalLimits(root_actions=4, next_actions=4)), **kwargs)


def test_sacrifice_wins_after_continuation_despite_worse_first_turn(catalog):
    def transition(state, action):
        if state['turn'] == 1:
            return {'turn': 2, 'first': action}, summary(2, own=1 if action == 'attack' else 2)
        return {'turn': 3}, summary(3, own=1 if state['first'] == 'attack' else 0,
                                   foe=0 if state['first'] == 'attack' else 2)
    worker = Worker(transition, lambda s: ['attack', 'protect'] if s['turn'] == 1 else ['continue'])
    result = run(worker, catalog, [{'turn': 1}], ['attack', 'protect'])
    assert result.status == 'complete' and result.action == 'attack'
    ranked = {r['action']: r for r in result.ranking}
    assert ranked['attack']['worlds'][0]['one_turn_utility'] < ranked['protect']['worlds'][0]['one_turn_utility']
    assert ranked['attack']['worst_world_utility'] > ranked['protect']['worst_world_utility']
    one_turn = run(worker, catalog, [{'turn': 1}], ['attack', 'protect'], horizon_turns=1)
    assert one_turn.action == 'protect'


def test_indistinguishable_hidden_worlds_share_one_continuation(catalog):
    def transition(state, action):
        if state['turn'] == 1:
            return {**state, 'turn': 2}, summary(2)
        value = 1 if action == 'safe' else 2 if action == state['hidden'] else 0
        return {'turn': 3}, summary(3, own=value, foe=1)
    worker = Worker(transition, lambda s: ['start'] if s['turn'] == 1 else ['a', 'b', 'safe'])
    result = run(worker, catalog, [{'turn': 1, 'hidden': 'a'}, {'turn': 1, 'hidden': 'b'}], ['start'])
    assert result.status == 'complete' and result.continuation_groups == 1
    assert result.ranking[0]['coverage']['continuation_actions'] == {'safe': 1}
    assert {v['leaf_utility'] for v in result.ranking[0]['worlds']} == {0}


def test_replacement_request_does_not_count_as_a_full_turn(catalog):
    def transition(state, action):
        if state['turn'] == 1:
            return {'turn': 2, 'phase': 'switch'}, summary(2)
        if state.get('phase') == 'switch':
            return {'turn': 2, 'phase': 'move'}, summary(2)
        return {'turn': 3}, summary(3, own=2, foe=1)
    worker = Worker(transition, lambda s: ['replace' if s.get('phase') == 'switch' else 'attack'])
    result = run(worker, catalog, [{'turn': 1}], ['attack'])
    assert result.status == 'complete' and result.branch_count == 3
    assert result.ranking[0]['worlds'][0]['leaf_utility'] > 0


def test_pivot_and_residual_replacement_can_need_more_than_four_phases(catalog):
    def transition(state, action):
        step = state.get('step', 0)+1
        turn = 1 if step == 1 else 2 if step < 5 else 3
        return {'step': step, 'turn': turn, 'phase': 'switch' if step in (1, 3, 4) else 'move'}, summary(turn)
    worker = Worker(transition, lambda s: ['continue'])
    result = run(worker, catalog, [{'turn': 1}], ['continue'])
    assert result.status == 'complete' and result.branch_count == 5


def test_incomplete_branch_budget_retains_legal_incumbent(catalog):
    worker = Worker(lambda s, a: ({'turn': 2}, summary(2)), lambda s: ['attack', 'protect'])
    result = run(worker, catalog, [{'turn': 1}], ['attack', 'protect'],
                 limits=TacticalLimits(branch_limit=1))
    assert result.status == 'incomplete' and result.action == 'attack' and not result.ranking
    assert result.branch_count == 0


def test_optional_leaf_positions_preserve_decisions_scores_and_branch_counts(catalog):
    def transition(state, action):
        if state['turn'] == 1:
            return {'turn': 1, 'phase': 'switch', 'action': action}, summary(1)
        return {'turn': 2}, summary(2, own=2, foe=1 if state['action'] == 'attack' else 2)
    worker = Worker(transition, lambda s: ['attack', 'protect'] if s['turn'] == 1 and 'phase' not in s else ['replace'])
    plain = run(worker, catalog, [{'turn': 1}], ['attack', 'protect'], horizon_turns=1)
    recorded = run(worker, catalog, [{'turn': 1}], ['attack', 'protect'], horizon_turns=1, include_leaf_positions=True)
    assert recorded.action == plain.action and recorded.branch_count == plain.branch_count
    stripped = deepcopy(recorded.ranking)
    for candidate in stripped:
        for world in candidate['worlds']:
            for sample in world['sampled_responses'].values():
                positions = sample.pop('leaf_positions')
                assert positions and all(p['turn'] == 2 for p in positions)
    assert stripped == plain.ranking


def test_publicly_inconsistent_hypotheses_are_rejected(catalog):
    worker = Worker(None, lambda s: ['attack'])
    result = run(worker, catalog, [{'turn': 1}, {'turn': 2}], ['attack'])
    assert result.status == 'incomplete' and result.branch_count == 0
    assert 'observation' in result.reason


def test_unmodeled_actual_legal_action_rejects_hypothesis(catalog):
    worker = Worker(None, lambda s: ['attack'])
    result = run(worker, catalog, [{'turn': 1}], ['attack', 'switch 3'])
    assert result.status == 'incomplete' and 'menu' in result.reason


def test_unknown_root_keys_do_not_split_information_sets():
    assert observation_key({'turn': 2, 'secret': 1, 'request': {'rqid': 1}}) == observation_key(
        {'turn': 2, 'secret': 9, 'request': {'rqid': 7}})


def test_every_sampled_response_is_extended(catalog):
    worker = Worker(lambda s, a: ({'turn': s['turn']+1}, summary(s['turn']+1)), lambda s: ['attack'])
    result = run(worker, catalog, [{'turn': 1}], ['attack'], limits=replace(TacticalLimits(), rng_seeds=(
        'sodium,'+'11111111'*8, 'sodium,'+'22222222'*8)))
    # Two first-turn futures and two continuation futures from each.
    assert result.status == 'complete' and result.branch_count == 6
