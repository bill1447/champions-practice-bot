"""Public-result certificates, native damage controls and closed negatives."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from time import perf_counter

import pytest

from champions_practice.belief_controller import _pin_known_team_genders
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.diversity_league import catalog
from champions_practice.persistent_support import current_capability_issue
from champions_practice.present_rebase import build_present_rebase, _positive_mechanics_rejection
from champions_practice.public_move_result import public_move_result_plan
from champions_practice.public_origin import PublicOriginWorker
from champions_practice.search_worker import HypotheticalSearchWorker, TeamValidationWorker
from champions_practice.tactical_consequences import observation_key


ROOT = Path(__file__).resolve().parents[1]
ROSTER = ('Garchomp', 'Rotom-Wash', 'Dragonite', 'Metagross', 'Venusaur', 'Rillaboom')
SEED = 'sodium,'+'12345678'*8
PREVIEWS = {side: list(ROSTER) for side in ('p1', 'p2')}


def fixture():
    pool = {s: (replace(catalog()[s][0], item=''),) for s in ROSTER}
    text = '\n\n'.join(pool[s][0].team_text for s in ROSTER)+'\n'
    return text, pool


def begin(worker):
    text, priors = fixture()
    state = worker.create_state(battle_format=CHAMPIONS_FORMAT, p1_team=text, p2_team=text,
        p1_preview='team 1234', p2_preview='team 1234', seed=SEED)
    view = worker.state_view(state=state, side='p2', previews=PREVIEWS)
    return state, view, PublicConstraintLedger.from_public_view(view), text, priors


def step(worker, state, ledger, own, enemy):
    result = worker.branch_many(state=state, branches=[{'p1_choice': enemy, 'p2_choice': own,
        'rng_seed': SEED, 'include_state': True}])[0]
    view = worker.state_view(state=result['state'], side='p2', previews=PREVIEWS)
    return result['state'], view, ledger.advance(view)


def admit(worker, state, view, ledger, text, priors, preview='team 1234'):
    menu = worker.legal_choices(state=state, side='p2')
    report = build_present_rebase(worker, ledger=ledger, current_view=view, priors=priors,
        battle_format=CHAMPIONS_FORMAT, ai_team=_pin_known_team_genders(text, view['request']),
        ai_preview_choice=preview, legal_live=tuple(menu), max_roots=2, max_particles=2)
    assert report.particles, report.unresolved_reason
    scoped = PublicOriginWorker(worker, states=[p.state for p in report.particles], current_view=view,
        ledger=ledger, previews=PREVIEWS, legal_actions=menu)
    for particle in report.particles:
        assert observation_key(scoped.state_view(state=particle.state, side='p2')) == observation_key(view)
        assert set(scoped.legal_choices(state=particle.state, side='p2')) == set(menu)
        projected = worker.state_view(state=particle.state, side='p2', previews=PREVIEWS)
        hypothetical_menu = worker.legal_choices(state=particle.state, side='p2')
        assert _positive_mechanics_rejection(particle.state, projected, current_view=view, ledger=ledger,
            legal_live=tuple(menu), hypothetical_legal=hypothetical_menu) is None
    return report


@pytest.mark.parametrize(('own', 'enemy', 'expected'), [
    ('move dragonclaw +1, move protect', 'move dragonclaw +1, move protect', 'true'),
    ('move stompingtantrum +2, move protect', 'move dragonclaw +1, move thunderbolt +2', 'false'),
    ('move dragonclaw +1, move protect', 'move protect, move protect', 'null'),
    ('move rockslide, move protect', 'move protect, move thunderbolt +2', 'true'),
    ('switch 3, move protect', 'move protect, move protect', 'undefined'),
])
def test_exact_public_result_and_native_materialization(own, enemy, expected):
    with HypotheticalSearchWorker(ROOT, startup_deadline=perf_counter()+30) as worker:
        state, _, ledger, text, priors = begin(worker)
        state, view, ledger = step(worker, state, ledger, own, enemy)
        plan = public_move_result_plan(view, ledger)
        entry = next(e for e in plan if e['side'] == 'player' and e['slot'] == 0)
        assert entry['result'] == expected
        native = state['sides'][1]['pokemon'][0]
        actual = 'undefined' if 'moveLastTurnResult' not in native else json.dumps(native['moveLastTurnResult'])
        assert actual == expected
        report = admit(worker, state, view, ledger, text, priors)
        # Exact public projection and legal menus cannot catch a corrupt latent
        # result. The independent positive native-state check must reject it.
        for particle in report.particles:
            bad = deepcopy(particle.state)
            bad['sides'][1]['pokemon'][0]['moveLastTurnResult'] = expected != 'true'
            projected = worker.state_view(state=bad, side='p2', previews=PREVIEWS)
            menu = worker.legal_choices(state=bad, side='p2')
            assert projected['request'] == view['request']
            assert projected['player'] == view['player']
            assert _positive_mechanics_rejection(bad, projected, current_view=view, ledger=ledger,
                legal_live=tuple(menu), hypothetical_legal=menu) == 'unsupported-persistent:last-move-result-mismatch'


def test_native_failure_doubles_damage_but_protect_block_does_not():
    text, _ = fixture()
    with TeamValidationWorker(ROOT, startup_deadline=perf_counter()+30) as validator:
        assert validator.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=text)['valid']
    damages = {}
    with HypotheticalSearchWorker(ROOT, startup_deadline=perf_counter()+30) as worker:
        for result, own, enemy in (
            ('true', 'move protect, move protect', 'move dragonclaw +1, move protect'),
            ('false', 'move stompingtantrum +2, move protect', 'move protect, move thunderbolt +2'),
            ('null', 'move dragonclaw +1, move protect', 'move protect, move protect')):
            state, _, ledger, _, _ = begin(worker)
            state, _, _ = step(worker, state, ledger, own, enemy)
            before = state['sides'][0]['pokemon'][0]['hp']
            outcome = worker.branch_many(state=state, branches=[{
                'p1_choice': 'move dragonclaw +1, move protect',
                'p2_choice': 'move stompingtantrum +1, move protect',
                'rng_seed': SEED, 'include_state': True}])[0]
            damages[result] = before-outcome['state']['sides'][0]['pokemon'][0]['hp']
        assert damages['false'] > damages['true'] == damages['null'] > 0


def test_flinch_is_explicit_failure_and_native_mega_keeps_the_result():
    own, priors = fixture()
    incin = replace(catalog()['Incineroar'][0], item='')
    enemy_roster = ('Incineroar', *ROSTER[1:])
    enemy = '\n\n'.join((incin if s == 'Incineroar' else priors[s][0]).team_text for s in enemy_roster)+'\n'
    previews = {'p1': list(enemy_roster), 'p2': list(ROSTER)}
    with HypotheticalSearchWorker(ROOT, startup_deadline=perf_counter()+30) as worker:
        state = worker.create_state(battle_format=CHAMPIONS_FORMAT, p1_team=enemy, p2_team=own,
            p1_preview='team 1234', p2_preview='team 1234', seed=SEED)
        public = worker.state_view(state=state, side='p2', previews=previews)
        ledger = PublicConstraintLedger.from_public_view(public)
        result = worker.branch_many(state=state, branches=[{'p1_choice': 'move fakeout +1, move protect',
            'p2_choice': 'move dragonclaw +1, move protect', 'rng_seed': SEED, 'include_state': True}])[0]
        public = worker.state_view(state=result['state'], side='p2', previews=previews)
        plan = public_move_result_plan(public, ledger.advance(public))
        assert next(e for e in plan if e['side'] == 'player' and e['slot'] == 0)['result'] == 'false'
        assert result['state']['sides'][1]['pokemon'][0]['moveLastTurnResult'] is False

        # Use the ordinary mirror fixture to exercise a native Mega holder's
        # successful and failed Stomping history under public reconstruction.
        mega = own.replace('Metagross\n', 'Metagross @ Metagrossite\n')
        state = worker.create_state(battle_format=CHAMPIONS_FORMAT, p1_team=mega, p2_team=mega,
            p1_preview='team 4213', p2_preview='team 4213', seed=SEED)
        previews = {side: list(ROSTER) for side in ('p1', 'p2')}
        public = worker.state_view(state=state, side='p2', previews=previews)
        ledger = PublicConstraintLedger.from_public_view(public)
        state, public, ledger = step(worker, state, ledger, 'move stompingtantrum +2 mega, move protect',
                                     'move psychicfangs +1 mega, move thunderbolt +2')
        assert public['player']['active_details'][0]['species'] == 'Metagross-Mega'
        assert next(e for e in public_move_result_plan(public, ledger)
                    if e['side'] == 'player' and e['slot'] == 0)['result'] == 'false'
        priors['Metagross'] = (replace(priors['Metagross'][0], item='Metagrossite'),)
        admit(worker, state, public, ledger, mega, priors, preview='team 4213')


def test_missing_partial_ambiguous_and_confusion_evidence_stays_closed():
    with HypotheticalSearchWorker(ROOT, startup_deadline=perf_counter()+30) as worker:
        state, opening, ledger, _, priors = begin(worker)
        state, view, complete = step(worker, state, ledger, 'move dragonclaw +1, move protect',
                                     'move protect, move protect')
        assert current_capability_issue(view, priors, complete) is None
        assert current_capability_issue(view, priors)  # No ledger is no certificate.
        missing = PublicConstraintLedger.from_public_view(view)
        assert public_move_result_plan(view, missing) is None
        assert current_capability_issue(view, priors, missing)
        for events in (
            [['move', 'p2a', 'dragonclaw'], ['upkeep']],  # Outcome omitted.
            [['move', 'p2a', 'dragonclaw'], ['-damage', 'p1a', '90/100'],
             ['move', 'p2a', 'dragonclaw'], ['-damage', 'p1a', '80/100'], ['upkeep']],
            [['-activate', 'p2a', 'confusion'], ['-damage', 'p2a', '90/100', '[from]:confusion'], ['upkeep']],
        ):
            changed = deepcopy(view)
            changed['public_event_delta']['events'] = events
            synthetic_ledger = PublicConstraintLedger.from_public_view(opening).advance(changed)
            plan = public_move_result_plan(changed, synthetic_ledger)
            assert not any(e['side'] == 'player' and e['slot'] == 0 for e in plan or [])
            assert current_capability_issue(changed, priors, synthetic_ledger)
        partial = deepcopy(view)
        partial['public_event_delta']['events'] = partial['public_event_delta']['events'][:-1]
        assert public_move_result_plan(partial, PublicConstraintLedger.from_public_view(opening).advance(partial)) is None
        switch_pause = deepcopy(view)
        switch_pause['phase'] = 'switch'
        assert public_move_result_plan(switch_pause, complete) is None
