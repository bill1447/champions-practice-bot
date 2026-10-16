"""Continuous public rain can outlive its opening setter and active pair."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from time import perf_counter

import pytest

from champions_practice.belief_controller import _pin_known_team_genders
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.diversity_league import catalog
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.present_mechanics import public_weather_plan
from champions_practice.present_rebase import build_present_rebase, _positive_mechanics_rejection
from champions_practice.public_origin import PublicOriginWorker
from champions_practice.search_worker import HypotheticalSearchWorker, TeamValidationWorker
from champions_practice.tactical_consequences import observation_key


ROOT = Path(__file__).resolve().parents[1]
OWN = ('Rotom-Wash', 'Dragonite', 'Metagross', 'Venusaur', 'Incineroar', 'Rillaboom')
FOE = ('Pelipper', 'Metagross', 'Dragonite', 'Rotom-Wash', 'Venusaur', 'Incineroar')
SEED = 'sodium,'+'12345678'*8


def fixture(rock, weather='raindance'):
    pool = {s: (replace(cs[0], item='', moves=tuple('Earthquake' if m == 'Stomping Tantrum' else m
            for m in cs[0].moves)),) for s, cs in catalog().items()}
    setter = 'Pelipper' if weather == 'raindance' else 'Tyranitar'
    members = tuple(setter if s == 'Pelipper' else s for s in FOE)
    item = ('Damp Rock' if rock else 'Focus Sash') if weather == 'raindance' else ('Smooth Rock' if rock else 'Chople Berry')
    pool[setter] = (replace(pool[setter][0], item=item),)
    def text(species):
        return '\n\n'.join(pool[s][0].team_text for s in species)+'\n'
    return text(OWN), text(members), {s: pool[s] for s in members}, members, setter


class WeatherProbe:
    def __init__(self, worker):
        self.worker = worker
        self.requests = []

    def __getattr__(self, name):
        return getattr(self.worker, name)

    def materialize_present_hypotheses(self, **kwargs):
        result = self.worker.materialize_present_hypotheses(**kwargs)
        self.requests.append((kwargs, result))
        return result


@pytest.mark.parametrize('rock', (False, True))
@pytest.mark.parametrize('weather,fainted', (('raindance', False), ('raindance', True), ('sandstorm', False)))
def test_public_opening_source_native_clock_and_next_turn_equivalence(rock, weather, fainted):
    own, foe, priors, members, setter = fixture(rock, weather)
    previews = {'p1': list(members), 'p2': list(OWN)}
    with TeamValidationWorker(ROOT, startup_deadline=perf_counter()+30) as validator:
        for text in (own, foe):
            result = validator.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=text)
            assert result['valid'], result['problems']
    with HypotheticalSearchWorker(ROOT, startup_deadline=perf_counter()+30) as worker:
        state = worker.create_state(battle_format=CHAMPIONS_FORMAT, p1_team=foe, p2_team=own,
            p1_preview='team 1234', p2_preview='team 1234', seed=SEED)
        view = worker.state_view(state=state, side='p2', previews=previews)
        ledger = PublicConstraintLedger.from_public_view(view)

        def advance(p1, p2):
            nonlocal state, view, ledger
            assert p1 in worker.legal_choices(state=state, side='p1')
            assert p2 in worker.legal_choices(state=state, side='p2')
            state = worker.branch_many(state=state, branches=[{'p1_choice': p1, 'p2_choice': p2,
                'rng_seed': SEED, 'include_state': True}])[0]['state']
            view = worker.state_view(state=state, side='p2', previews=previews)
            ledger = ledger.advance(view)

        if fainted:
            advance('move hurricane +1, move protect', 'move thunderbolt +1, move extremespeed +1')
            source = next(m for m in state['sides'][0]['pokemon'] if m['set']['species'] == setter)
            assert source['fainted']
            for _ in range(6):
                if view['phase'] == 'move' and worker.legal_choices(state=state, side='p2') != ['wait']:
                    break
                advance(sorted(worker.legal_choices(state=state, side='p1'))[0],
                        sorted(worker.legal_choices(state=state, side='p2'))[0])
            advance('move protect, move protect', 'move protect, move protect')
        else:
            advance('move protect, move protect', 'move protect, move protect')
            # Keep real move execution in the turn; older producer switch-only
            # deltas have a separately rejected legacy execution-turn shape.
            advance('switch 3, move psychicfangs +1', 'switch 3, move extremespeed +2')
        plan = public_weather_plan(view, ledger)
        assert plan['residual_turns'] == 2 and len(plan['opening_sources']) == 4
        menu = worker.legal_choices(state=state, side='p2')
        spy = WeatherProbe(worker)
        report = build_present_rebase(spy, ledger=ledger, current_view=view, priors=priors,
            battle_format=CHAMPIONS_FORMAT, ai_team=_pin_known_team_genders(own, view['request']),
            ai_preview_choice='team 1234', legal_live=tuple(menu), max_roots=2, max_particles=2)
        assert report.particles, report.unresolved_reason
        assert spy.requests and all(not kwargs['state']['field']['weather'] for kwargs, _ in spy.requests)
        scoped = PublicOriginWorker(worker, states=[p.state for p in report.particles], current_view=view,
            ledger=ledger, previews=previews, legal_actions=menu)
        expected_duration = (8 if rock else 5)-2
        for particle in report.particles:
            rebuilt = particle.state
            actual_source = next(m for m in state['sides'][0]['pokemon'] if m['set']['species'] == setter)
            rebuilt_source = next(m for m in rebuilt['sides'][0]['pokemon'] if m['set']['species'] == setter)
            assert (rebuilt_source['isActive'], rebuilt_source['fainted']) == (actual_source['isActive'], actual_source['fainted'])
            assert not rebuilt_source['isActive']
            if fainted:
                assert rebuilt_source['hp'] == 0
            assert rebuilt['field']['weatherState']['duration'] == expected_duration
            assert state['field']['weatherState']['duration'] == expected_duration
            assert observation_key(scoped.state_view(state=rebuilt, side='p2')) == observation_key(view)
            assert set(scoped.legal_choices(state=rebuilt, side='p2')) == set(menu)
            projected = worker.state_view(state=rebuilt, side='p2', previews=previews)
            corrupted = deepcopy(rebuilt)
            corrupted['field']['weatherState']['duration'] -= 1
            assert _positive_mechanics_rejection(corrupted, projected, current_view=view, ledger=ledger,
                legal_live=tuple(menu), hypothetical_legal=menu) == 'unsupported-persistent:field-duration-mismatch'
            # Every remaining residual and expiration is produced by native
            # mechanics, without copying a duration from the actual state.
            actual, hypothetical = state, rebuilt
            for _ in range(expected_duration):
                children = []
                for parent in (actual, hypothetical):
                    assert 'move protect, move protect' in worker.legal_choices(state=parent, side='p1')
                    assert 'move protect, move protect' in worker.legal_choices(state=parent, side='p2')
                    children.append(worker.branch_many(state=parent, branches=[{
                        'p1_choice': 'move protect, move protect', 'p2_choice': 'move protect, move protect',
                        'rng_seed': SEED, 'include_state': True}])[0]['state'])
                actual, hypothetical = children
                assert actual['field']['weather'] == hypothetical['field']['weather']
                assert actual['field']['weatherState'].get('duration') == hypothetical['field']['weatherState'].get('duration')
            assert not hypothetical['field']['weather']
        request, _ = spy.requests[0]
        no_opening = deepcopy(request)
        del no_opening['weather_plan']['opening_sources']
        rejected = worker.materialize_present_hypotheses(**no_opening)
        assert not rejected['outcomes'] and rejected['reason'] == 'unsupported-public-weather-plan'
        bad_age = deepcopy(request)
        bad_age['weather_plan']['residual_turns'] += 1
        rejected = worker.materialize_present_hypotheses(**bad_age)
        assert not rejected['outcomes'] and rejected['reason'] == 'unsupported-public-weather-plan'
        # The native boundary cannot accept a source outside the public opening.
        for replacement in ('Venusaur', 'Rotom-Wash'):
            bad = deepcopy(request)
            source = next(e for e in bad['weather_plan']['opening_sources'] if e['source_species'] == setter)
            source['source_species'] = replacement
            rejected = worker.materialize_present_hypotheses(**bad)
            assert not rejected['outcomes'] and rejected['reason'] == 'unsupported-opening-weather-source'
        # Multiple possible opening Drizzle activations, or an opening Trace,
        # cannot be resolved from a continuation-only legacy channel.
        for species in (setter, 'Gardevoir'):
            pool = catalog()
            altered = own.strip().split('\n\n')
            altered[3] = replace(pool[species][0], item='').team_text
            fresh = worker.create_state(battle_format=CHAMPIONS_FORMAT, p1_team=foe,
                p2_team='\n\n'.join(altered)+'\n', p1_preview='team 3421', p2_preview='team 3214', seed=SEED)
            assert not fresh['field']['weather']
            ambiguous = deepcopy(request)
            ambiguous['state'] = fresh
            ambiguous['weather_plan']['opening_sources'][1]['source_species'] = species
            rejected = worker.materialize_present_hypotheses(**ambiguous)
            assert not rejected['outcomes'] and rejected['reason'] == 'unsupported-opening-weather-source'
