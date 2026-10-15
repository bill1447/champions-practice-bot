from copy import deepcopy

import pytest

from champions_practice.public_inventory import public_inventory_plan, native_inventory_rejection
from test_persistent_support import evidence


@pytest.mark.parametrize('item,tags', [('sitrusberry', ['[eat]']), ('focussash', [])])
def test_ordinary_consumption(item, tags):
    view, ledger = evidence([['-enditem', 'p1a', item, *tags]])
    assert public_inventory_plan(view, ledger) == [{'species': 'Incineroar', 'item': item,
        'ate_berry': item != 'focussash', 'used_this_turn': False}]


@pytest.mark.parametrize('item', ['shucaberry', 'colburberry'])
def test_eat_weaken_pair_is_one_consumption(item):
    events = [['-enditem', 'p1a', item, tag] for tag in ('[eat]', '[weaken]')]
    view, ledger = evidence(events)
    assert len(public_inventory_plan(view, ledger)) == 1
    view, ledger = evidence(events+events)
    assert public_inventory_plan(view, ledger) is None


@pytest.mark.parametrize('events', [
    [['-enditem', 'p1a', 'sitrusberry', '[eat]']]*2,
    [['-enditem', 'p1a', 'shucaberry', '[weaken]']],
    [['-enditem', 'p1a', 'shucaberry', '[eat]']],
    [['-enditem', 'p1a', 'focussash', '[from]move:knockoff']],
    [['-item', 'p1a', 'sitrusberry']],
    [['-enditem', 'p1a', 'lumberry', '[eat]']],
    [['-enditem', 'p1b', 'sitrusberry', '[eat]']],
])
def test_ambiguous_unsupported_or_missing_identity_is_closed(events):
    view, ledger = evidence(events)
    assert public_inventory_plan(view, ledger) is None


def test_current_turn_flag_then_native_switch_out_boundary():
    import json
    from types import SimpleNamespace
    view, ledger = evidence([['-enditem', 'p1a', 'focussash']])
    view['turn'] = 1
    view['phase'] = 'switch'
    snapshot = json.loads(ledger.field_snapshots[-1][1])
    snapshot.update(phase='switch', active_species={'player': ['Incineroar'], 'opponent': ['Incineroar']})
    ledger = SimpleNamespace(current_turn=1, field_snapshots=((1, ledger.field_snapshots[0][1]), (1, json.dumps(snapshot))))
    assert public_inventory_plan(view, ledger)[0]['used_this_turn']
    snapshot['public_event_delta']['events'].insert(-1, ['switch', 'p1a', 'Metagross'])
    ledger.field_snapshots = (*ledger.field_snapshots[:1], (1, json.dumps(snapshot)))
    assert not public_inventory_plan(view, ledger)[0]['used_this_turn']


def test_positive_check_rejects_hidden_inventory_corruption():
    entry = {'species': 'Incineroar', 'item': 'shucaberry', 'ate_berry': True, 'used_this_turn': False}
    mon = {'set': {'species': 'Incineroar', 'item': 'Shuca Berry'}, 'item': '', 'lastItem': 'shucaberry',
           'ateBerry': True, 'usedItemThisTurn': False, 'itemState': {'id': '', 'target': '[Pokemon:p1a]'}}
    state = {'sides': [{'pokemon': [mon]}]}
    assert native_inventory_rejection(state, [entry]) is None
    assert native_inventory_rejection(state, []) == 'unsupported-persistent:unobserved-inventory-change'
    for field, value in [('lastItem', ''), ('item', 'shucaberry'), ('ateBerry', False), ('usedItemThisTurn', True)]:
        bad = deepcopy(state)
        bad['sides'][0]['pokemon'][0][field] = value
        assert native_inventory_rejection(bad, [entry]) is not None
    bad = deepcopy(state)
    bad['sides'][0]['pokemon'][0]['itemState']['started'] = True
    assert native_inventory_rejection(bad, [entry]) is not None
    bad = deepcopy(state)
    bad['sides'][0]['pokemon'][0]['itemState']['target'] = '[Pokemon:p1b]'
    assert native_inventory_rejection(bad, [entry]) is not None
