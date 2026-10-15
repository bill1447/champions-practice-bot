"""Legal move controls exercise restoration, not just public gate opening."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from champions_practice.belief_controller import _pin_known_team_genders
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.diversity_league import catalog
from champions_practice.present_rebase import build_present_rebase, _positive_mechanics_rejection
from champions_practice.public_inventory import public_inventory_plan, native_inventory_rejection
from champions_practice.search_worker import HypotheticalSearchWorker, TeamValidationWorker


def test_all_four_native_consumptions_and_corruption_controls():
    root = Path(__file__).resolve().parents[1]
    species_list = ('Incineroar', 'Garchomp', 'Metagross', 'Rotom-Wash', 'Dragonite', 'Venusaur')
    pool = catalog()
    base = {species: (replace(pool[species][0], item='', moves=tuple(
        'Earthquake' if move == 'Stomping Tantrum' else 'Protect' if move == 'Fake Out' else move
        for move in pool[species][0].moves)),) for species in species_list}
    own = '\n\n'.join(base[species][0].team_text for species in species_list)
    own = own.replace('- Psychic Fangs\n', '- Ice Punch\n')
    cases = (
        ('shucaberry', 'Incineroar', 'team 1423', 'team 2341', 'move earthquake, move protect'),
        ('sitrusberry', 'Incineroar', 'team 1423', 'team 2341', 'move earthquake, move protect'),
        ('colburberry', 'Metagross', 'team 3421', 'team 1342', 'move darkestlariat +1, move protect'),
        ('focussash', 'Dragonite', 'team 5413', 'team 3142', 'move icepunch +1, move darkestlariat +1'),
    )
    with HypotheticalSearchWorker(root, startup_deadline=perf_counter()+30) as worker, TeamValidationWorker(root, startup_deadline=perf_counter()+30) as validator:
        for item, target, foe_preview, own_preview, attack in cases:
            priors = {species: tuple(replace(mon, item=item if species == target else '') for mon in candidates)
                      for species, candidates in base.items()}
            enemy = '\n\n'.join(priors[species][0].team_text for species in species_list)
            for text in (own, enemy):
                validated = validator.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=text)
                assert validated['valid'], validated
            state = worker.create_state(battle_format=CHAMPIONS_FORMAT, p1_team=enemy, p2_team=own,
                p1_preview=foe_preview, p2_preview=own_preview, seed='sodium,'+'12345678'*8)
            previews = {'p1': list(species_list), 'p2': list(species_list)}
            view = worker.state_view(state=state, side='p2', previews=previews)
            ledger = PublicConstraintLedger.from_public_view(view)
            def advance(first, second):
                nonlocal state, view, ledger
                assert first in worker.legal_choices(state=state, side='p1'), first
                assert second in worker.legal_choices(state=state, side='p2'), second
                state = worker.branch_many(state=state, branches=[{'p1_choice': first, 'p2_choice': second,
                    'include_state': True, 'rng_seed': 'sodium,'+'12345678'*8}])[0]['state']
                view = worker.state_view(state=state, side='p2', previews=previews)
                ledger = ledger.advance(view)
            advance('move protect, move protect', 'move protect, move protect')
            for _ in range(4):
                advance('move dragonclaw +1, move protect' if target == 'Dragonite' else
                        'move darkestlariat +1, move protect' if target == 'Incineroar' else
                        'move psychicfangs +1, move protect', attack)
                plan = public_inventory_plan(view, ledger)
                if plan:
                    break
            assert plan and plan[0]['item'] == item, (item, view)
            assert native_inventory_rejection(state, plan) is None
            legal = worker.legal_choices(state=state, side='p2')
            report = build_present_rebase(worker, ledger=ledger, current_view=view, priors=priors,
                battle_format=CHAMPIONS_FORMAT, ai_team=_pin_known_team_genders(own, view['request']),
                ai_preview_choice=own_preview, legal_live=tuple(legal), max_roots=1, max_particles=2)
            assert report.particles, (item, report)
            incompatible = {species: tuple(replace(mon, item='') for mon in candidates)
                            for species, candidates in priors.items()}
            excluded = build_present_rebase(worker, ledger=ledger, current_view=view, priors=incompatible,
                battle_format=CHAMPIONS_FORMAT, ai_team=_pin_known_team_genders(own, view['request']),
                ai_preview_choice=own_preview, legal_live=tuple(legal), max_roots=1, max_particles=2)
            assert not excluded.particles
            assert excluded.unresolved_reason == 'unsupported-persistent:opponent-capabilities'
            for particle in report.particles:
                candidate = particle.state
                assert native_inventory_rejection(candidate, plan) is None
                native = next(m for m in state['sides'][0]['pokemon'] if m['set']['species'] == target)
                restored = next(m for m in candidate['sides'][0]['pokemon'] if m['set']['species'] == target)
                for field in ('item', 'lastItem', 'ateBerry', 'usedItemThisTurn'):
                    assert restored[field] == native[field], (item, field)
                projected = worker.state_view(state=candidate, side='p2', previews=previews)
                def rejection(bad):
                    return _positive_mechanics_rejection(bad, projected, current_view=view, ledger=ledger,
                        legal_live=tuple(legal), hypothetical_legal=worker.legal_choices(state=candidate, side='p2'))
                assert rejection(candidate) is None
                bad = deepcopy(candidate)
                next(m for m in bad['sides'][0]['pokemon'] if m['set']['species'] == target)['ability'] = 'unburden'
                assert rejection(bad) == 'unsupported-persistent:opponent-unburden'
                for field, value in [('lastItem', ''), ('ateBerry', not plan[0]['ate_berry']),
                                     ('usedItemThisTurn', not plan[0]['used_this_turn'])]:
                    bad = deepcopy(candidate)
                    mon = next(m for m in bad['sides'][0]['pokemon'] if m['set']['species'] == target)
                    mon[field] = value
                    assert rejection(bad) == 'unsupported-persistent:inventory-state'
                # Serialization, a native continuation and a forced replacement
                # must preserve the same consumed inventory as the real control.
                commands = {}
                for side in ('p1', 'p2'):
                    menu = worker.legal_choices(state=state, side=side)
                    commands[side] = 'move protect, move protect' if 'move protect, move protect' in menu else menu[0]
                children = [worker.branch_many(state=parent, branches=[{'p1_choice': commands['p1'],
                    'p2_choice': commands['p2'], 'include_state': True, 'rng_seed': 'sodium,'+'12345678'*8}])[0]['state']
                    for parent in (state, candidate)]
                oracle, rebuilt = [next(m for m in child['sides'][0]['pokemon'] if m['set']['species'] == target)
                                   for child in children]
                assert all(oracle[key] == rebuilt[key] for key in ('item', 'lastItem', 'ateBerry', 'usedItemThisTurn'))
                if item == 'focussash':
                    after = worker.state_view(state=children[0], side='p2', previews=previews)
                    after_ledger = ledger.advance(after)
                    after_plan = public_inventory_plan(after, after_ledger)
                    assert not after_plan[0]['used_this_turn']
                    after_report = build_present_rebase(worker, ledger=after_ledger, current_view=after,
                        priors=priors, battle_format=CHAMPIONS_FORMAT,
                        ai_team=_pin_known_team_genders(own, after['request']), ai_preview_choice=own_preview,
                        legal_live=tuple(worker.legal_choices(state=children[0], side='p2')),
                        max_roots=1, max_particles=2)
                    assert after_report.particles, after_report
                    assert all(native_inventory_rejection(p.state, after_plan) is None for p in after_report.particles)
