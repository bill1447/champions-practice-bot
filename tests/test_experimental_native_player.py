"""Decision boundary regressions: shared deadline, legal fallback, diagnostics."""

from types import SimpleNamespace
from threading import Event
from time import perf_counter

import pytest

from champions_practice import experimental_native_player as module
from champions_practice.tactical_consequences import TacticalResult


@pytest.fixture
def setup(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(module, 'perf_counter', lambda: clock[0])
    monkeypatch.setattr(module, 'observe', lambda view, legal, deadline: None)
    ledger = SimpleNamespace(advance=lambda view: ledger)
    monkeypatch.setattr(module, 'PublicConstraintLedger', SimpleNamespace(from_public_view=lambda view: ledger))
    monkeypatch.setattr(module, 'diagnose_match', lambda *args, **kwargs: {'anchor': 'test', 'competing_plans': []})
    player = module.ExperimentalNativePlayer('.', own_team='own', opening_prior='prior', priors={},
        catalog=None, incumbent_policy=lambda *args: SimpleNamespace(action='v2'))
    return clock, player


def test_preparation_and_search_share_original_deadline(setup, monkeypatch):
    clock, player = setup
    seen = []
    def prepare(worker, view, deadline):
        seen.append(('prepare', deadline))
        clock[0] += 6
        return worker, ('world',), ''
    player._opening = prepare
    player._bounded = lambda operation, deadline: (operation(object()), False)
    def search(worker, **kwargs):
        seen.append(('search', kwargs['deadline']))
        assert kwargs['deadline']-clock[0] == 2
        assert kwargs['horizon_turns'] == 1
        assert (kwargs['limits'].root_actions, kwargs['limits'].responses) == (8, 3)
        clock[0] += 1
    def complete(worker, **kwargs):
        search(worker, **kwargs)
        return TacticalResult('native', 'complete', (), 0, 0, 1)
    monkeypatch.setattr(module, 'evaluate_consequences', complete)
    monkeypatch.setattr(module, 'compare_routes', lambda *a, **k: {'diagnostic': 'cannot select'})
    action, trace = player.decide({'turn': 1, 'phase': 'move'}, ['v2', 'native'])
    assert seen == [('prepare', 108), ('search', 108)]
    assert action == 'native' and trace['elapsed_seconds'] == 7
    assert trace['position_assessment'] == {'diagnostic': 'cannot select'}


def test_timeout_discards_native_action_and_retains_legal_incumbent(setup):
    clock, player = setup
    def timeout(operation, deadline):
        clock[0] += 7.8
        return None, True
    player._bounded = timeout
    action, trace = player.decide({'turn': 1, 'phase': 'move'}, ['v2', 'native'])
    assert action == 'v2' and trace['reason'] == 'shared-decision-deadline'
    assert trace['admission_attempted'] and not trace['disagreement']


def test_rejected_admission_never_runs_search(setup, monkeypatch):
    _, player = setup
    player._opening = lambda *args: (None, (), 'public-hypothesis-rejected')
    player._bounded = lambda operation, deadline: (operation(object()), False)
    monkeypatch.setattr(module, 'evaluate_consequences', lambda *a, **k: pytest.fail('unadmitted search'))
    action, trace = player.decide({'turn': 1, 'phase': 'move'}, ['v2', 'native'])
    assert action == 'v2' and trace['reason'] == 'public-hypothesis-rejected'


def test_late_completed_result_is_discarded(setup):
    clock, player = setup
    def late(operation, deadline):
        clock[0] += 8.01
        return ('native', {'status': 'search', 'reason': ''}), False
    player._bounded = late
    action, trace = player.decide({'turn': 1, 'phase': 'move'}, ['v2', 'native'])
    assert action == 'v2' and trace['status'] == 'fallback'


def test_forced_wait_updates_ledger_without_starting_native_worker(setup):
    _, player = setup
    player.incumbent_policy = lambda *args: SimpleNamespace(action='wait')
    player._bounded = lambda *a, **k: pytest.fail('nonactionable native startup')
    action, trace = player.decide({'turn': 2, 'phase': 'wait'}, ['wait'])
    assert action == 'wait' and trace['status'] == 'nonactionable'
    assert not trace['admission_attempted']


def test_public_ledger_rejection_falls_back_without_native_work(setup, monkeypatch):
    _, player = setup
    def reject(view):
        raise ValueError('source mismatch')
    monkeypatch.setattr(module, 'PublicConstraintLedger', SimpleNamespace(from_public_view=reject))
    player._bounded = lambda *a, **k: pytest.fail('untrusted admission')
    action, trace = player.decide({'turn': 2, 'phase': 'move'}, ['v2', 'native'])
    assert action == 'v2' and trace['reason'] == 'public-ledger-rejected'


def test_shared_deadline_aborts_inflight_preparation_and_returns_v2(setup, monkeypatch):
    _, player = setup
    monkeypatch.setattr(module, 'perf_counter', perf_counter)
    player.budget_seconds = .5
    aborted, exited = Event(), Event()
    class BlockingWorker:
        def __init__(self, *args, **kwargs):
            assert kwargs['startup_deadline'] > perf_counter()
        def abort(self, **kwargs):
            aborted.set()
    monkeypatch.setattr('champions_practice.belief_controller.HypotheticalSearchWorker', BlockingWorker)
    def prepare(*args):
        try:
            assert aborted.wait(2), 'watchdog did not abort preparation'
            return None, (), 'aborted'
        finally:
            exited.set()
    player._opening = prepare
    start = perf_counter()
    action, trace = player.decide({'turn': 1, 'phase': 'move'}, ['v2', 'native'])
    assert perf_counter()-start < .65
    assert action == 'v2' and trace['reason'] == 'shared-decision-deadline'
    assert aborted.is_set() and exited.wait(.2)
