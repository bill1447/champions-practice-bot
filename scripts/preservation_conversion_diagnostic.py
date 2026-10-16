"""Frozen offline preservation/conversion probe. Never changes player scoring.

Public-only admitted roots; matched action/response/RNG sweeps; frozen V2 own
continuation and the existing independent opponent for one additional turn.
Scenario counts and means are diagnostics, not opponent probabilities.
"""

import argparse
from collections import defaultdict
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog, observe
from champions_practice.agent_v2.policy import rank_action
from champions_practice.belief_controller import _pin_known_team_genders
from champions_practice.belief_search import ExactBeliefWorldState
from champions_practice.competitive_evaluation import canonical_view
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.diversity_league import catalog as public_priors
from champions_practice.independent_opponent import IndependentOpponent, load_dex
from champions_practice.plan_consequences import exact_log_lines, move_evidence
from champions_practice.present_rebase import build_present_rebase
from champions_practice.public_origin import PublicOriginWorker
from champions_practice.search_worker import HypotheticalSearchWorker
from champions_practice.strategic_diagnostic import resource_id
from champions_practice.tactical_consequences import (
    TacticalLimits, _leaf_breakdown, evaluate_consequences, observation_key, shortlist,
)
from full_game_native_evaluation import MaxPower
from tactical_consequences_evaluation import ROOT, blueprints, frozen_policy, species


CASES = (
    ('new-venusaur-protect', 'development-1-simple-heuristics-heldout-native', 7, 'Venusaur'),
    ('new-armarouge-protect', 'validation-2-simple-heuristics-heldout-native', 6, 'Armarouge'),
    ('repeated-protect-loss', 'validation-2-max-base-power-heldout-native', 1, 'Armarouge'),
    ('last-venusaur-delay', 'development-0-simple-heuristics-prior-native', 7, 'Venusaur'),
)


def seed(label):
    return 'sodium,'+hashlib.sha256(label.encode()).hexdigest()


def damaging(part, catalog):
    words = part.strip().split()
    return len(words) > 1 and words[0] == 'move' and catalog.moves.get(words[1], {}).get('category') in {'Physical', 'Special'}


def reference_actions(row, focal, catalog):
    slot = next(i for i, m in enumerate(row['view']['player']['active_details'])
                if m and resource_id(m['species']) == resource_id(focal))
    selected, baseline = row['action'], row['decision']['incumbent']
    parts = [p.strip() for p in selected.split(',')]
    legal = row['legal_actions']
    board = observe(row['view'], legal, deadline=perf_counter()+8)
    compatible = [a for a in legal if all(p.strip() == parts[i]
        for i, p in enumerate(a.split(',')) if i != slot)]
    attacks = [a for a in compatible if damaging(a.split(',')[slot], catalog)]
    assert attacks
    attack = baseline if baseline in attacks else max(attacks, key=lambda a: rank_action(a, board, catalog).score)
    covered = [c['action'] for c in row['decision']['tactical']['ranking']
               if damaging(c['action'].split(',')[slot], catalog)]
    switches = [a for a in compatible if a.split(',')[slot].strip().startswith('switch ')]
    actions = defaultdict(list)
    for label, action in [('selected_shield', selected), ('matched_partner_attack', attack),
                          ('v2_reference', baseline), *([('best_covered_focal_attack', covered[0])] if covered else [])]:
        actions[action].append(label)
    for action in switches:
        actions[action].append('matched_partner_switch')
    assert all(a in legal for a in actions)
    return dict(actions), {'slot': slot, 'switch_available': bool(switches),
                           'matched_partner_attacks_available': len(attacks)}


def snapshot(worker, state, summary, focal, catalog):
    ours, theirs = summary['p2'], summary['p1']
    own_live = [m for m in ours['pokemon'] if m['hp'] > 0 and not m['fainted']]
    foe_live = [m for m in theirs['pokemon'] if m['hp'] > 0 and not m['fainted']]
    mon = next((m for m in ours['pokemon'] if resource_id(m['species']) == resource_id(focal)), None)
    slot = next((i for i, m in enumerate(ours['active']) if m and resource_id(m['species']) == resource_id(focal)), None)
    menu = worker.legal_choices(state=state, side='p2') if not summary['ended'] else []
    legal_attacks = [a for a in menu if slot is not None and len(a.split(',')) > slot
                     and damaging(a.split(',')[slot], catalog)]
    return {'breakdown': _leaf_breakdown(summary, 'p2'), 'turn': summary['turn'],
        'terminal_win': bool(summary['ended'] and summary['winner'] == ours['name']),
        'terminal_loss': bool(summary['ended'] and summary['winner'] == theirs['name']),
        'ended': summary['ended'], 'own_living': [m['species'] for m in own_live],
        'foe_living': [m['species'] for m in foe_live], 'field': summary['field'],
        'own_active': [{k: m[k] for k in ('species', 'hp', 'maxhp', 'effectiveSpeed', 'actionOrderSpeed', 'status')}
                       for m in ours['active'] if m and m['hp'] > 0],
        'foe_active': [{k: m[k] for k in ('species', 'hp', 'maxhp', 'effectiveSpeed', 'actionOrderSpeed', 'status')}
                       for m in theirs['active'] if m and m['hp'] > 0],
        'focal_living': bool(mon and mon['hp'] > 0 and not mon['fainted']),
        'focal_active': bool(slot is not None and mon and mon['hp'] > 0),
        'focal_hp': mon['hp']/max(1, mon['maxhp']) if mon else None,
        'focal_legal_damaging_joint_commands': len(legal_attacks)}


def complete_to(worker, state, summary, goal, *, case, reply, sample, enemy, policy,
                catalog, action_history, information_actions, deadline):
    evidence, decisions = [], []
    for phase in range(7):
        if summary['ended'] or summary['turn'] >= goal:
            return state, summary, evidence, decisions
        if phase == 6 or perf_counter() >= deadline:
            raise RuntimeError('offline continuation bound exceeded')
        view = worker.state_view(state=state, side='p2')
        menu = worker.legal_choices(state=state, side='p2')
        own = policy(observe(view, menu, deadline=perf_counter()+8), catalog).action
        info = (tuple(action_history), observation_key(view))
        if info in information_actions:
            assert information_actions[info] == own, 'continuation leaked hidden world into own choice'
        information_actions[info] = own
        foe_view = worker.state_view(state=state, side='p1')
        foe_menu = worker.legal_choices(state=state, side='p1')
        response, trace = enemy.choose(foe_view, foe_menu)
        assert own in menu and response in foe_menu
        outcome = worker.branch_many(state=state, branches=[{'p1_choice': response, 'p2_choice': own,
            'include_state': True, 'rng_seed': seed(f'conversion:{case}:{reply}:{sample}:{goal}:{phase}')}])[0]
        evidence.extend(move_evidence(state, outcome['state'], view, foe_view, 'p2', catalog))
        decisions.append({'turn': view['turn'], 'phase': view['phase'], 'own_action': own,
                          'enemy_action': response, 'opponent_fallback': trace['fallback']})
        state, summary = outcome['state'], outcome['summary']
        action_history.append(own)
    raise AssertionError('unreachable')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists(), 'Do not overwrite a frozen diagnostic'
    args.output.mkdir(parents=True)
    source = ROOT/'runs/v2-full-game-native/inventory-v1/games.json.gz'
    raw = source.read_bytes()
    archive = json.loads(gzip.decompress(raw))
    games = {g['id']: g for g in archive['games']}
    texts, _ = blueprints()
    catalog, dex = PublicCatalog.load(ROOT), load_dex(ROOT)
    policy, baseline = frozen_policy('e0ae723')
    paths = [*ROOT.joinpath('src/champions_practice').rglob('*.py'),
             ROOT/'tools/showdown-search-worker.js', Path(__file__).resolve()]
    report = {'cases': CASES, 'source_archive_sha256': hashlib.sha256(raw).hexdigest(), 'baseline': baseline,
        'source_sha256': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        'scope': 'Offline diagnostic only. Unchanged admission/scoring; 8 paired RNG labels; fixed root replies; frozen V2 own and independent opponent continuation through one additional turn.',
        'limitations': ['Selected retained counterexamples; no win-rate or opponent-probability estimate.',
            'Public-only bounded roots are hypotheses, not actual hidden-state or RNG witnesses.',
            'Default control uses the existing 8/3 robust replacement kernel; diagnostic continuations use V2 and the independent opponent.',
            'Recorded opposing command is an explicitly separate forensic response, not a deployable prediction.',
            'Legal damaging commands do not certify a productive opportunity; native execution/damage is measured separately.',
            'Offline time bound is 180 seconds per case; deployed eight-second decision budget is unchanged.'],
        'positions': []}
    (args.output/'manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    with HypotheticalSearchWorker(ROOT, startup_deadline=perf_counter()+30) as worker:
        for case, game_id, checkpoint, focal in CASES:
            game = games[game_id]
            row = game['rows'][checkpoint]
            actions, action_coverage = reference_actions(row, focal, catalog)
            ledger = None
            for previous in game['rows'][:checkpoint+1]:
                view = canonical_view(previous['view'], game['side'])
                ledger = PublicConstraintLedger.from_public_view(view) if ledger is None else ledger.advance(view)
            deadline = perf_counter()+180
            admission = build_present_rebase(worker, ledger=ledger, current_view=view, priors=public_priors(),
                battle_format=CHAMPIONS_FORMAT, ai_team=_pin_known_team_genders(texts[game['own_team']], view['request']),
                ai_preview_choice='team 1234', legal_live=tuple(row['legal_actions']), max_roots=2, max_particles=2)
            assert admission.particles, admission
            worlds = tuple(ExactBeliefWorldState(p.state, p.weight, p.world_id or str(i))
                           for i, p in enumerate(admission.particles))
            scoped = PublicOriginWorker(worker, states=[w.state for w in worlds], current_view=view, ledger=ledger,
                previews={'p1': view['opponent']['preview_species'], 'p2': species(texts[game['own_team']])},
                legal_actions=row['legal_actions'])
            control = evaluate_consequences(scoped, worlds=worlds, side='p2',
                authoritative_actions=row['legal_actions'], incumbent=row['decision']['incumbent'],
                catalog=catalog, deadline=deadline, horizon_turns=1,
                limits=TacticalLimits(root_actions=8, responses=3, next_actions=2))
            assert control.status == 'complete' and control.action == row['action']
            saved = {c['action']: c for c in row['decision']['tactical']['ranking']}
            for candidate in control.ranking:
                assert abs(candidate['worst_world_utility']-saved[candidate['action']]['worst_world_utility']) < 1e-7
            control_by_action = {c['action']: c for c in control.ranking}
            position = {'case': case, 'game': game_id, 'checkpoint': checkpoint, 'focal': focal,
                'turn': view['turn'], 'actions': actions, 'action_coverage': action_coverage,
                'selected': row['action'], 'incumbent': row['decision']['incumbent'],
                'recorded_reply': row['enemy_action'], 'control': asdict(control),
                'strategy_diagnostic': row['decision']['strategy'], 'worlds': [], 'samples': []}
            information_actions = {}
            next_probes = defaultdict(list)
            for world_index, world in enumerate(worlds):
                own_view = scoped.state_view(state=world.state, side='p2')
                foe_view = scoped.state_view(state=world.state, side='p1')
                foe_menu = scoped.legal_choices(state=world.state, side='p1')
                covered = shortlist(foe_view, foe_menu, catalog, 3)
                replies = list(covered)
                recorded_legal = row['enemy_action'] in foe_menu
                if recorded_legal and row['enemy_action'] not in replies:
                    replies.append(row['enemy_action'])
                position['worlds'].append({'world': world_index, 'weight': world.weight,
                    'covered_replies': covered, 'recorded_reply_legal': recorded_legal,
                    'recorded_reply_covered': row['enemy_action'] in covered})
                for reply in replies:
                    for sample in range(8):
                        specs = [{'p1_choice': reply, 'p2_choice': action, 'include_state': True,
                            'rng_seed': 'sodium,'+'12345678'*8 if sample == 0 else seed(f'conversion:{case}:{reply}:{sample}:root')}
                                 for action in actions]
                        outcomes = scoped.branch_many(state=world.state, branches=specs)
                        for action, outcome in zip(actions, outcomes, strict=True):
                            if perf_counter() >= deadline:
                                raise RuntimeError('offline case bound exceeded')
                            current, summary = outcome['state'], outcome['summary']
                            root_events = move_evidence(world.state, current, own_view, foe_view, 'p2', catalog)
                            immediate = snapshot(scoped, current, summary, focal, catalog)
                            if sample == 0 and action in control_by_action and reply in covered:
                                expected = control_by_action[action]['worlds'][world_index]['sampled_responses'][reply]['first_turn_breakdown']
                                assert all(abs(immediate['breakdown'][key]-value) < 1e-7 for key, value in expected.items())
                            enemy = IndependentOpponent(dex, f'conversion:{case}:{reply}:{sample}')
                            if game['opponent'] == 'max-base-power':
                                enemy.policy = MaxPower()
                            history = [action]
                            current, summary, phases, phase_decisions = complete_to(scoped, current, summary,
                                view['turn']+1, case=case, reply=reply, sample=sample, enemy=enemy,
                                policy=policy, catalog=catalog, action_history=history,
                                information_actions=information_actions, deadline=deadline)
                            first = snapshot(scoped, current, summary, focal, catalog)
                            if sample == 0 and not summary['ended']:
                                next_view = scoped.state_view(state=current, side='p2')
                                next_probes[(tuple(history), observation_key(next_view))].append({
                                    'state': current, 'world': world_index, 'weight': world.weight,
                                    'action': action, 'reply': reply, 'view': next_view})
                            current, summary, following, next_decisions = complete_to(scoped, current, summary,
                                view['turn']+2, case=case, reply=reply, sample=sample, enemy=enemy,
                                policy=policy, catalog=catalog, action_history=history,
                                information_actions=information_actions, deadline=deadline)
                            second = snapshot(scoped, current, summary, focal, catalog)
                            position['samples'].append({'world': world_index, 'action': action, 'reply': reply,
                                'covered_reply': reply in covered, 'recorded_reply': reply == row['enemy_action'],
                                'rng_sample': sample, 'immediate': immediate, 'first_turn': first, 'second_turn': second,
                                'root_move_events': root_events+phases, 'next_move_events': following,
                                'phase_decisions': phase_decisions, 'next_decisions': next_decisions})
            # A separate bounded next-turn audit uses the unchanged 8/3 kernel,
            # grouping indistinguishable leaves across worlds before selecting.
            # It is not a clairvoyant best continuation for each hidden state.
            position['next_turn_native_audit'] = []
            for members in next_probes.values():
                menus = [scoped.legal_choices(state=m['state'], side='p2') for m in members]
                common = [a for a in menus[0] if all(a in menu for menu in menus)]
                assert common
                next_view = members[0]['view']
                incumbent = policy(observe(next_view, common, deadline=perf_counter()+8), catalog).action
                result = evaluate_consequences(scoped,
                    worlds=tuple(ExactBeliefWorldState(m['state'], m['weight'], f"conditional-{i}")
                                 for i, m in enumerate(members)), side='p2', authoritative_actions=common,
                    incumbent=incumbent, catalog=catalog, deadline=deadline, horizon_turns=1,
                    limits=TacticalLimits(root_actions=8, responses=3, next_actions=2))
                assert result.status == 'complete', result.reason
                executions = []
                for index, member in enumerate(members):
                    own_view = scoped.state_view(state=member['state'], side='p2')
                    foe_view = scoped.state_view(state=member['state'], side='p1')
                    for response in result.ranking[0]['worlds'][index]['sampled_responses']:
                        outcome = scoped.branch_many(state=member['state'], branches=[{
                            'p1_choice': response, 'p2_choice': result.action, 'include_state': True,
                            'rng_seed': 'sodium,'+'12345678'*8}])[0]
                        executions.append({'member': index, 'reply': response,
                            'measurement': snapshot(scoped, outcome['state'], outcome['summary'], focal, catalog),
                            'moves': move_evidence(member['state'], outcome['state'], own_view, foe_view, 'p2', catalog),
                            'status_events': [line for line in exact_log_lines(outcome['state']['log'][len(member['state']['log']):])
                                              if line.startswith('|-status|') or line.startswith('|-fail|')]})
                position['next_turn_native_audit'].append({
                    'sources': [{k: m[k] for k in ('world', 'action', 'reply')} for m in members],
                    'incumbent': incumbent, 'selected': result.action, 'ranking': result.ranking,
                    'indistinguishable_hypotheses': len(members), 'selected_action_executions': executions})
            report['positions'].append(position)
            (args.output/'results.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
            print(case, len(actions), 'actions', len(position['samples']), 'paired diagnostic branches', flush=True)
    print('Completed', len(report['positions']), 'positions', flush=True)


if __name__ == '__main__':
    main()
