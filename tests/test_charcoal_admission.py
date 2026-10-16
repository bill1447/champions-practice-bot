"""Native Charcoal controls; no live hidden data enters admission."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from time import perf_counter

import pytest

from champions_practice.belief_controller import _pin_known_team_genders
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.persistent_admission_smoke import SEEDS
from champions_practice.diversity_league import catalog
from champions_practice.persistent_support import static_support_issue, current_capability_issue
from champions_practice.present_rebase import build_present_rebase, _positive_mechanics_rejection
from champions_practice.public_inventory import native_inventory_rejection
from champions_practice.public_origin import PublicOriginWorker
from champions_practice.search_worker import HypotheticalSearchWorker, TeamValidationWorker
from champions_practice.tactical_consequences import observation_key


ROOT = Path(__file__).resolve().parents[1]
SPECIES = ('Incineroar', 'Dragonite', 'Metagross', 'Rotom-Wash', 'Venusaur', 'Rillaboom')
PREVIEWS = {side: list(SPECIES) for side in ('p1', 'p2')}


def teams():
    pool = catalog()
    priors = {s: (replace(pool[s][0], item='', moves=tuple(
        'Earthquake' if m == 'Stomping Tantrum' else m for m in pool[s][0].moves)),) for s in SPECIES}
    mon = priors['Incineroar'][0]
    priors['Incineroar'] = (replace(mon, moves=('Flamethrower', 'Darkest Lariat', 'Flare Blitz', 'Protect')),)
    own = {**priors, 'Incineroar': (replace(priors['Incineroar'][0], item='Charcoal'),)}
    def text(pool):
        return '\n\n'.join(pool[s][0].team_text for s in SPECIES)+'\n'
    return text(own), text(priors), priors


def step(worker, state, p1, p2, ledger, rng=SEEDS[0]):
    assert p1 in worker.legal_choices(state=state, side='p1')
    assert p2 in worker.legal_choices(state=state, side='p2')
    result = worker.branch_many(state=state, branches=[{'p1_choice': p1, 'p2_choice': p2,
        'rng_seed': rng, 'include_state': True}])[0]
    view = worker.state_view(state=result['state'], side='p2', previews=PREVIEWS)
    return result['state'], view, ledger.advance(view)


def admit(worker, state, view, ledger, own, priors):
    menu = worker.legal_choices(state=state, side='p2')
    report = build_present_rebase(worker, ledger=ledger, current_view=view, priors=priors,
        battle_format=CHAMPIONS_FORMAT, ai_team=_pin_known_team_genders(own, view['request']),
        ai_preview_choice='team 1234', legal_live=tuple(menu), max_roots=2, max_particles=2)
    assert report.particles, report.unresolved_reason
    scoped = PublicOriginWorker(worker, states=[p.state for p in report.particles], current_view=view,
        ledger=ledger, previews=PREVIEWS, legal_actions=menu)
    for particle in report.particles:
        assert observation_key(scoped.state_view(state=particle.state, side='p2')) == observation_key(view)
        assert set(scoped.legal_choices(state=particle.state, side='p2')) == set(menu)
        projected = worker.state_view(state=particle.state, side='p2', previews=PREVIEWS)
        hypothetical_menu = worker.legal_choices(state=particle.state, side='p2')
        assert projected['request'] == view['request']
        assert projected['player'] == view['player']
        assert projected['field'] == view['field']
        assert set(hypothetical_menu) == set(menu)
        assert _positive_mechanics_rejection(particle.state, projected, current_view=view,
            ledger=ledger, legal_live=tuple(menu), hypothetical_legal=hypothetical_menu) is None
    return report


def test_charcoal_does_not_authorize_other_items_moves_or_transfer():
    for inactive in (False, True):
        assert static_support_issue(ability='Intimidate', item='Charcoal', moves=['Flamethrower'], inactive=inactive) is None
        assert static_support_issue(ability='Intimidate', item='Choice Specs', moves=['Flamethrower'], inactive=inactive)
        assert static_support_issue(ability='Intimidate', item='Charcoal', moves=['Fling'], inactive=inactive)
    mon = {'set': {'species': 'Incineroar', 'item': 'Charcoal'}, 'item': '', 'lastItem': 'charcoal',
           'ateBerry': False, 'usedItemThisTurn': False}
    assert native_inventory_rejection({'sides': [{'pokemon': [mon]}]}, [])


def test_native_charcoal_boosts_only_fire_without_consumption():
    own, enemy, _ = teams()
    with TeamValidationWorker(ROOT, startup_deadline=perf_counter()+30) as validator:
        for text in (own, enemy):
            result = validator.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=text)
            assert result['valid'], result['problems']
    with HypotheticalSearchWorker(ROOT, startup_deadline=perf_counter()+30) as worker:
        for move in ('flamethrower', 'darkestlariat'):
            damages = []
            for text in (own, own.replace(' @ Charcoal', '')):
                root = worker.create_state(battle_format=CHAMPIONS_FORMAT, p1_team=enemy, p2_team=text,
                    p1_preview='team 1234', p2_preview='team 1234', seed=SEEDS[0])
                view = worker.state_view(state=root, side='p2', previews=PREVIEWS)
                result, _, _ = step(worker, root, 'move darkestlariat +2, move protect',
                    f'move {move} +1, move protect', PublicConstraintLedger.from_public_view(view))
                target = next(m for m in result['sides'][0]['pokemon'] if m['set']['species'] == 'Incineroar')
                damages.append(target['maxhp']-target['hp'])
                holder = next(m for m in result['sides'][1]['pokemon'] if m['set']['species'] == 'Incineroar')
                assert holder['item'] == ('charcoal' if text == own else '')
                assert not holder['lastItem'] and not holder['usedItemThisTurn']
            assert damages[0] > damages[1] if move == 'flamethrower' else damages[0] == damages[1]


@pytest.mark.parametrize('faint_holder', (False, True))
@pytest.mark.parametrize('opponent_charcoal', (False, True))
def test_native_public_charcoal_admission_living_and_fainted(faint_holder, opponent_charcoal):
    own, enemy, priors = teams()
    if opponent_charcoal:
        enemy = own
        priors = {**priors, 'Incineroar': (replace(priors['Incineroar'][0], item='Charcoal'),)}
    with HypotheticalSearchWorker(ROOT, startup_deadline=perf_counter()+30) as worker:
        state = worker.create_state(battle_format=CHAMPIONS_FORMAT, p1_team=enemy, p2_team=own,
            p1_preview='team 4312' if faint_holder else 'team 1234', p2_preview='team 1234', seed=SEEDS[0])
        view = worker.state_view(state=state, side='p2', previews=PREVIEWS)
        ledger = PublicConstraintLedger.from_public_view(view)
        state, view, ledger = step(worker, state,
            'move hydropump +1, move psychicfangs +1' if faint_holder else 'move darkestlariat +2, move protect',
            'move flamethrower +1, move earthquake' if faint_holder else 'move flamethrower +1, move protect', ledger)
        if faint_holder:
            holder = next(m for m in state['sides'][1]['pokemon'] if m['set']['species'] == 'Incineroar')
            assert holder['fainted'] and holder['hp'] == 0
            for _ in range(6):
                if view['phase'] == 'move' and worker.legal_choices(state=state, side='p2') != ['wait']:
                    break
                p1 = sorted(worker.legal_choices(state=state, side='p1'))[0]
                p2 = sorted(worker.legal_choices(state=state, side='p2'))[0]
                state, view, ledger = step(worker, state, p1, p2, ledger)
        admitted = admit(worker, state, view, ledger, own, priors)
        # Public projection and menu contradictions remain negative controls.
        candidate = admitted.particles[0].state
        projected = worker.state_view(state=candidate, side='p2', previews=PREVIEWS)
        menu = worker.legal_choices(state=state, side='p2')
        wrong = deepcopy(projected)
        wrong['player']['team'][0]['item'] = 'choicespecs'
        assert _positive_mechanics_rejection(candidate, wrong, current_view=view, ledger=ledger,
            legal_live=tuple(menu), hypothetical_legal=menu) is not None
        assert _positive_mechanics_rejection(candidate, projected, current_view=view, ledger=ledger,
            legal_live=tuple(menu), hypothetical_legal=menu+['impossible-command']) is not None
        corrupted = deepcopy(candidate)
        mon = next(m for m in corrupted['sides'][0]['pokemon'] if m['set']['species'] == 'Incineroar')
        mon['item'] = '' if mon['item'] else 'charcoal'
        assert _positive_mechanics_rejection(corrupted, projected, current_view=view, ledger=ledger,
            legal_live=tuple(menu), hypothetical_legal=menu) is not None
        mixed = {**priors, 'Incineroar': (*priors['Incineroar'], replace(priors['Incineroar'][0], item='Choice Specs'))}
        assert current_capability_issue(view, mixed) is not None
