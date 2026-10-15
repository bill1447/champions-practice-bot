"""Paired native plan diagnostics on explicit public-conditioned opening worlds."""

from dataclasses import asdict
from collections import Counter
import gzip
import hashlib
import json
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog, observe
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.exact_search import score_exact_summary_breakdown
from champions_practice.plan_consequences import measure_transition, route_command_counts, summarize_opportunities
from champions_practice.search_worker import HypotheticalSearchWorker
from champions_practice.tactical_consequences import observation_key, shortlist
from tactical_consequences_evaluation import (
    ROOT, PublicPreviewWorker, blueprints, frozen_policy, owned_genders, species,
)


def seed(label):
    return 'sodium,'+hashlib.sha256(label.encode()).hexdigest()


def read(relative):
    return json.loads(gzip.decompress((ROOT/relative).read_bytes()))


def conditioned_worlds(worker, game, texts):
    view = game['rows'][0]['view']
    side = game['side']
    other = 'p2' if side == 'p1' else 'p1'
    own = owned_genders(texts[game['own_team']], view)
    prior = texts[game['enemy_team']]
    previews = {side: species(own), other: view['opponent']['preview_species']}
    scoped = PublicPreviewWorker(worker, previews)
    worlds = []
    for hypothesis in range(2):
        candidate = prior.replace('Life Orb', 'Sitrus Berry') if hypothesis else prior
        choices = {side: 'team 1234', other: 'team 1256' if hypothesis else 'team 1234'}
        for sample in range(16):
            state = worker.create_state(battle_format=CHAMPIONS_FORMAT,
                p1_team=own if side == 'p1' else candidate,
                p2_team=candidate if side == 'p1' else own,
                p1_preview=choices['p1'], p2_preview=choices['p2'],
                p1_name='P1', p2_name='P2', seed=seed(f'public-root:{hypothesis}:{sample}'))
            if observation_key(scoped.state_view(state=state, side=side)) == observation_key(view):
                worlds.append(state)
                break
    assert len(worlds) == 2
    return scoped, worlds


def main():
    base = read('runs/v2-consequences/one-turn/games.json.gz')
    matrix = read('runs/v2-objective/v1/results.json.gz')
    texts, _ = blueprints()
    catalog = PublicCatalog.load(ROOT)
    policy, _ = frozen_policy('e0ae723')
    output = ROOT/'runs/v2-plan-consequences/v1'
    output.mkdir(parents=True, exist_ok=True)
    cases = ('development-0-0-p1', 'validation-1-1-p1')
    report = {'cases': cases, 'positions': [], 'protocol': {
        'roots': 'All eight retained commands, all three identical retained responses per world, two original public-conditioned hypotheses.',
        'samples': 'Four root RNG samples, first the original control seed; coupled across own commands.',
        'next_turn_probe': 'Same public-only shortlist procedure, at most eight joint commands and three replies. One coupled RNG sample per continuation pair. No alternate action is selected from probe results.',
        'phase_completion': 'Frozen V2 on each side public view for replacement/pivot phases, at most six; no live truth or independent-opponent fallback.',
        'opportunity': 'Native direct damage to an opponent by the named attacker, with that attacker alive at completed-turn end. KO/trade and realized move order reported separately.',
        'limits': 'Sampled opportunity, not win probability or proof of impossibility. Current-turn probes can miss multi-turn entry routes. These are already examined counterexamples, not held-out validation.'},
        'source_sha256': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in (
            'scripts/strategic_consequence_comparison.py', 'src/champions_practice/plan_consequences.py',
            'src/champions_practice/tactical_consequences.py', 'src/champions_practice/exact_search.py',
            'tools/showdown-search-worker.js', 'runs/v2-consequences/one-turn/games.json.gz',
            'runs/v2-objective/v1/results.json.gz')}}
    (output/'manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    branch_count = 0

    def branch(scoped, state, action, reply, rng):
        nonlocal branch_count
        branch_count += 1
        return scoped.branch_many(state=state, branches=[{'p1_choice': action,
            'p2_choice': reply, 'rng_seed': rng, 'include_state': True}])[0]

    def complete(scoped, outcome, goal, label):
        phases = 0
        while not outcome['summary']['ended'] and outcome['summary']['turn'] < goal:
            assert phases < 6, 'phase limit: comparison incomplete'
            actions = {}
            for side in ('p1', 'p2'):
                visible = scoped.state_view(state=outcome['state'], side=side)
                menu = scoped.legal_choices(state=outcome['state'], side=side)
                actions[side] = policy(observe(visible, menu, deadline=perf_counter()+8), catalog).action
                assert actions[side] in menu
            outcome = branch(scoped, outcome['state'], actions['p1'], actions['p2'], seed(f'{label}:phase:{phases}'))
            phases += 1
        return outcome, phases

    with HypotheticalSearchWorker(ROOT, startup_deadline=perf_counter()+60) as worker:
        for case in cases:
            game = next(g for g in base['games'] if g['pair'] == case)
            assert game['side'] == 'p1'
            scoped, worlds = conditioned_worlds(worker, game, texts)
            ranking = next(m['ranking'] for m in matrix['matrices'] if m['pair'] == case)
            position = {'case': case, 'control_action': ranking[0]['action'],
                'actions': [r['action'] for r in ranking], 'rows': []}
            report['positions'].append(position)
            for world, state in enumerate(worlds):
                own_view = scoped.state_view(state=state, side='p1')
                enemy_view = scoped.state_view(state=state, side='p2')
                responses = list(ranking[0]['worlds'][world]['sampled_responses'])
                assert len(responses) == 3
                assert all(list(r['worlds'][world]['sampled_responses']) == responses for r in ranking)
                assert all(a in scoped.legal_choices(state=state, side='p1') for a in position['actions'])
                assert all(r in scoped.legal_choices(state=state, side='p2') for r in responses)
                for action in position['actions']:
                    for reply in responses:
                        for sample in range(4):
                            label = f'plan:{case}:{world}:{reply}:{sample}'
                            rng = 'sodium,'+'12345678'*8 if sample == 0 else seed(label+':root')
                            first = branch(scoped, state, action, reply, rng)
                            first, phases = complete(scoped, first, 2, label+':first')
                            measurement = measure_transition(state, first, own_view, enemy_view, 'p1', catalog)
                            score = asdict(score_exact_summary_breakdown(first['summary'], 'p1'))
                            old = next(r for r in ranking if r['action'] == action)['worlds'][world]['sampled_responses'][reply]['leaf_utility']
                            if sample == 0 and phases == 0:
                                assert abs(score['total']-old) < 1e-7
                            row = {'world': world, 'action': action, 'reply': reply, 'sample': sample,
                                'first_turn': measurement, 'first_score': score,
                                'cached_control_sample_score': old, 'completion_phases': phases, 'probes': []}
                            position['rows'].append(row)
                            if not first['summary']['ended']:
                                own_next = scoped.state_view(state=first['state'], side='p1')
                                foe_next = scoped.state_view(state=first['state'], side='p2')
                                menu = scoped.legal_choices(state=first['state'], side='p1')
                                enemy_menu = scoped.legal_choices(state=first['state'], side='p2')
                                actions = shortlist(own_next, menu, catalog, 8)
                                replies = shortlist(foe_next, enemy_menu, catalog, 3)
                                row['next_actions'], row['next_replies'] = actions, replies
                                row['route_command_coverage'] = {
                                    'all_legal': route_command_counts(own_next, menu, catalog),
                                    'probed': route_command_counts(own_next, actions, catalog)}
                                for next_action in actions:
                                    for next_reply in replies:
                                        second = branch(scoped, first['state'], next_action, next_reply,
                                                        seed(label+':next:'+next_reply))
                                        second, next_phases = complete(scoped, second, 3, label+':second:'+next_reply)
                                        row['probes'].append({'action': next_action, 'reply': next_reply,
                                            'completion_phases': next_phases,
                                            'measurement': measure_transition(first['state'], second, own_next, foe_next, 'p1', catalog),
                                            'score': asdict(score_exact_summary_breakdown(second['summary'], 'p1'))})
                            row['opportunities'] = summarize_opportunities(row['probes'])
                    print(case, world, action, 'complete', flush=True)
                    report['branch_count'] = branch_count
                    (output/'results.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    report['rows'] = sum(len(p['rows']) for p in report['positions'])
    assert report['rows'] == 384
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest() == expected for p, expected in report['source_sha256'].items())
    report['counts'] = dict(Counter(r['completion_phases'] for p in report['positions'] for r in p['rows']))
    (output/'results.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    print('Completed', report['rows'], 'root scenarios and', branch_count, 'native branches')


if __name__ == '__main__':
    main()
