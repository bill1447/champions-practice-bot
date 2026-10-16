"""Precommitted fresh tactical consequences; no player or utility changes."""

import argparse
from collections import Counter
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog, observe
from champions_practice.belief_search import ExactBeliefWorldState
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.diversity_league import team_text
from champions_practice.exact_search import score_exact_summary_breakdown
from champions_practice.plan_consequences import move_evidence
from champions_practice.search_worker import HypotheticalSearchWorker, TeamValidationWorker
from champions_practice.tactical_consequences import TacticalLimits, evaluate_consequences, shortlist
from tactical_consequences_evaluation import frozen_policy


ROOT = Path(__file__).resolve().parents[1]
SPECS = (
    ('concentrate-damage', ('Metagross', 'Rotom-Wash', 'Incineroar', 'Venusaur', 'Pelipper', 'Indeedee-F'),
     ('Tyranitar', 'Dragonite', 'Rillaboom', 'Armarouge', 'Gardevoir', 'Excadrill')),
    ('trade-and-spread', ('Garchomp', 'Rotom-Wash', 'Gardevoir', 'Rillaboom', 'Incineroar', 'Pelipper'),
     ('Metagross', 'Pelipper', 'Venusaur', 'Indeedee-F', 'Tyranitar', 'Basculegion')),
    ('speed-control', ('Pelipper', 'Metagross', 'Armarouge', 'Rillaboom', 'Dragonite', 'Indeedee-F'),
     ('Garchomp', 'Rotom-Wash', 'Excadrill', 'Gardevoir', 'Incineroar', 'Venusaur')),
    ('redirection-and-setup', ('Indeedee-F', 'Gardevoir', 'Dragonite', 'Rotom-Wash', 'Rillaboom', 'Pelipper'),
     ('Dragonite', 'Archaludon', 'Incineroar', 'Metagross', 'Venusaur', 'Tyranitar')),
    ('repositioning', ('Incineroar', 'Rotom-Wash', 'Metagross', 'Indeedee-F', 'Garchomp', 'Pelipper'),
     ('Basculegion', 'Garchomp', 'Rillaboom', 'Gardevoir', 'Armarouge', 'Excadrill')),
    ('alternative-attacker', ('Gardevoir', 'Metagross', 'Armarouge', 'Pelipper', 'Indeedee-F', 'Rotom-Wash'),
     ('Excadrill', 'Rillaboom', 'Dragonite', 'Venusaur', 'Tyranitar', 'Incineroar')),
)
SOURCES = ('scripts/fresh_tactical_benchmark.py', 'src/champions_practice/tactical_consequences.py',
           'src/champions_practice/exact_search.py', 'src/champions_practice/consequence_ties.py',
           'src/champions_practice/plan_consequences.py', 'tools/showdown-search-worker.js')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def seed(label):
    return 'sodium,'+sha(label.encode())


def benchmark_team(roster):
    # Armarouge and Excadrill otherwise share Life Orb in one six-mon roster.
    return team_text(roster).replace('Stomping Tantrum', 'Earthquake').replace(
        'Armarouge @ Life Orb', 'Armarouge @ Charcoal')


def select_probes(menu, control):
    """Deterministic command coverage, never selected by resulting utility."""
    safe = sorted(a for a in menu if not any(t in {'-1', '-2'} for t in a.split()))
    safe = safe or sorted(menu)
    selected = {control: ['control']}
    def add(label, predicate):
        action = next((a for a in safe if predicate(a)), None)
        if action:
            selected.setdefault(action, []).append(label)
    add('shield', lambda a: 'protect' in a)
    add('switch', lambda a: 'switch ' in a)
    add('speed-control', lambda a: any(m in a for m in ('tailwind', 'trickroom')))
    add('disruption', lambda a: any(m in a for m in ('followme', 'fakeout', 'sleeppowder', 'willowisp')))
    add('focus-first', lambda a: len(a.split(',')) == 2 and all('+1' in p for p in a.split(',')))
    add('focus-second', lambda a: len(a.split(',')) == 2 and all('+2' in p for p in a.split(',')))
    add('spread', lambda a: any(m in a for m in ('earthquake', 'hypervoice', 'rockslide', 'expandingforce')))
    add('mega', lambda a: ' mega' in a)
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('freeze', 'evaluate'))
    parser.add_argument('--manifest', type=Path, default=ROOT/'reviews/fresh-tactical-manifest-v2-2026-10-15.json')
    parser.add_argument('--output', type=Path, default=ROOT/'runs/fresh-tactical/v1')
    parser.add_argument('--report', type=Path, default=ROOT/'reviews/fresh-tactical-results-2026-10-15.json')
    args = parser.parse_args()
    hashes = {p: sha((ROOT/p).read_bytes()) for p in SOURCES}
    if args.phase == 'freeze':
        assert not args.manifest.exists(), 'Never replace a frozen protocol'
        cases = []
        for name, ours, theirs in SPECS:
            for warmup in (0, 2):
                cases.append({'id': f'{name}-warmup-{warmup}', 'category': name,
                    'warmup_completed_turns': warmup, 'own_roster': ours, 'enemy_roster': theirs,
                    'own_team': benchmark_team(ours),
                    'enemy_team': benchmark_team(theirs),
                    'seed': seed(f'fresh-tactical-2026-10-15:{name}:{warmup}'),
                    'preview': 'team 1234', 'optimal_action_label': 'unproven'})
        args.manifest.write_text(json.dumps({'cases': cases, 'source_sha256': hashes,
            'protocol': {'search': 'Existing one-turn 8/3, unchanged weights; explicit single-world diagnostic.',
                'roots': 'Fresh arrangements, seeds and frozen-V2 two-turn prefixes; never patch serialized battle state.',
                'probe_actions': 'All eight search candidates plus deterministic legal command-category witnesses.',
                'responses': 'All three native search replies, then frozen V2/category witnesses to six unique replies; fixed per root.',
                'rng': ['sodium,'+'12345678'*8]+[seed(f'fresh-tactical-roll:{i}') for i in range(3)],
                'continuation': 'Frozen V2 from each side own public view, through one additional completed turn; six phase limit.',
                'metrics': 'Terminal wins/losses, surviving allies/enemies, direct damaging actors; no route weights.',
                'labels': 'Terminal outcomes are native facts conditional on supplied state/response/RNG. Other plan preferences unproven.',
                'gates': 'Legal validated teams/actions; bounded complete phases; same replies/RNG across candidates; no result-based case removal.',
                'limits': ['Designed categories do not guarantee a KO, trade or setup payoff exists.',
                    'Single exact hypothetical world bypasses admission; this is not a public-only player trial.',
                    'Four coupled RNG labels are scenarios, not probabilities.',
                    'Fixed previews, familiar species and sets, synthetic opposition; no competence claim.',
                    'These cases become development data after the first inspection.']}}, indent=2)+'\n')
        print('Frozen', len(cases), 'fresh cases before evaluation')
        return
    manifest = json.loads(args.manifest.read_text())
    assert manifest['source_sha256'] == hashes, 'Frozen source changed'
    policy, identity = frozen_policy('e0ae723')
    catalog = PublicCatalog.load(ROOT)
    args.output.mkdir(parents=True, exist_ok=True)
    assert not (args.output/'results.json.gz').exists(), 'Choose a fresh output directory'
    report = {'manifest_sha256': sha(args.manifest.read_bytes()), 'baseline': identity, 'cases': []}
    raw = []
    with TeamValidationWorker(ROOT, startup_deadline=perf_counter()+60) as validator:
        for case in manifest['cases']:
            for key in ('own_team', 'enemy_team'):
                validation = validator.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=case[key])
                assert validation['valid'], (case['id'], validation)
    with HypotheticalSearchWorker(ROOT, startup_deadline=perf_counter()+60) as worker:
        def choice(state, side):
            menu = worker.legal_choices(state=state, side=side)
            view = worker.state_view(state=state, side=side)
            return policy(observe(view, menu, deadline=perf_counter()+8), catalog).action

        def branch(state, ours, theirs, rng):
            assert ours in worker.legal_choices(state=state, side='p1')
            assert theirs in worker.legal_choices(state=state, side='p2')
            return worker.branch_many(state=state, branches=[{'p1_choice': ours, 'p2_choice': theirs,
                'rng_seed': rng, 'include_state': True}])[0]

        def complete(outcome, goal, rng):
            trace = []
            for _ in range(6):
                summary = outcome['summary']
                if summary['ended'] or summary['turn'] >= goal:
                    return outcome, trace
                parent = outcome['state']
                views = [worker.state_view(state=parent, side=s) for s in ('p1', 'p2')]
                outcome = branch(parent, choice(parent, 'p1'), choice(parent, 'p2'), rng)
                trace.extend(move_evidence(parent, outcome['state'], *views, 'p1', catalog))
            raise AssertionError('Incomplete phase/continuation; do not silently discard')

        def facts(outcome, events):
            summary = outcome['summary']
            living = {s: [m['species'] for m in summary[s]['pokemon'] if m['hp'] > 0 and not m['fainted']]
                      for s in ('p1', 'p2')}
            return {'turn': summary['turn'], 'terminal_win': summary['ended'] and summary['winner'] == summary['p1']['name'],
                'terminal_loss': summary['ended'] and summary['winner'] == summary['p2']['name'],
                'own_living': living['p1'], 'enemy_living': living['p2'],
                'direct_damage_actors': sorted({e['actor'] for e in events if e['side'] == 'p1' and e['direct_damage_targets']}),
                'utility': asdict(score_exact_summary_breakdown(summary, 'p1'))}

        for case in manifest['cases']:
            state = worker.create_state(battle_format=CHAMPIONS_FORMAT, p1_team=case['own_team'],
                p2_team=case['enemy_team'], p1_preview=case['preview'], p2_preview=case['preview'], seed=case['seed'])
            # Prefix is generated before seeing any alternative's outcome.
            for step in range(case['warmup_completed_turns']):
                target = int(worker.state_view(state=state, side='p1')['turn'])+1
                outcome = branch(state, choice(state, 'p1'), choice(state, 'p2'), seed(case['id']+f':prefix:{step}'))
                outcome, _ = complete(outcome, target, seed(case['id']+f':prefix-complete:{step}'))
                state = outcome['state']
                if outcome['summary']['ended']:
                    break
            view = worker.state_view(state=state, side='p1')
            if view['ended'] or view['phase'] != 'move':
                report['cases'].append({'id': case['id'], 'status': 'not_actionable', 'turn': view['turn']})
                continue
            menu = worker.legal_choices(state=state, side='p1')
            incumbent = choice(state, 'p1')
            search = evaluate_consequences(worker, worlds=(ExactBeliefWorldState(state, 1, case['id']),),
                side='p1', authoritative_actions=menu, incumbent=incumbent, catalog=catalog,
                deadline=perf_counter()+8, limits=TacticalLimits(root_actions=8, responses=3), horizon_turns=1)
            assert search.status == 'complete', (case['id'], search.reason)
            candidates = select_probes(menu, incumbent)
            for row in search.ranking:
                candidates.setdefault(row['action'], []).append('search-candidate')
            enemy_menu = worker.legal_choices(state=state, side='p2')
            enemy_view = worker.state_view(state=state, side='p2')
            search_replies = shortlist(enemy_view, enemy_menu, catalog, 3)
            replies = list(dict.fromkeys([*search_replies, *select_probes(enemy_menu, choice(state, 'p2'))]))[:6]
            measurements = []
            reproduced = 0
            ranking_by_action = {r['action']: r for r in search.ranking}
            for action in candidates:
                for reply in replies:
                    for roll, rng in enumerate(manifest['protocol']['rng']):
                        first = branch(state, action, reply, rng)
                        if roll == 0 and action in ranking_by_action and reply in search_replies and (
                                first['summary']['ended'] or first['summary']['turn'] >= view['turn']+1):
                            expected = ranking_by_action[action]['worlds'][0]['sampled_responses'][reply]['leaf_utility']
                            assert score_exact_summary_breakdown(first['summary'], 'p1').total == expected
                            reproduced += 1
                        first, _ = complete(first, view['turn']+1, seed(rng+':phase'))
                        root_events = move_evidence(state, first['state'], view, enemy_view, 'p1', catalog)
                        second, next_events = complete(first, view['turn']+2, seed(rng+':next'))
                        measurements.append({'action': action, 'reply': reply, 'rng': roll,
                            'reply_in_search': reply in search_replies,
                            'first': facts(first, root_events), 'second': facts(second, next_events)})
            summaries = []
            for action, roles in candidates.items():
                samples = [m for m in measurements if m['action'] == action]
                by_stage = {}
                for stage in ('first', 'second'):
                    actors = Counter(actor for m in samples for actor in m[stage]['direct_damage_actors'])
                    by_stage[stage] = {'samples': len(samples),
                        'wins': sum(m[stage]['terminal_win'] for m in samples),
                        'losses': sum(m[stage]['terminal_loss'] for m in samples),
                        'own_living_total': sum(len(m[stage]['own_living']) for m in samples),
                        'enemy_living_total': sum(len(m[stage]['enemy_living']) for m in samples),
                        'direct_damage_samples_by_actor': dict(actors)}
                summaries.append({'action': action, 'roles': roles, **by_stage})
            result = {'id': case['id'], 'category': case['category'], 'turn': view['turn'], 'status': 'complete',
                'incumbent': incumbent, 'selected': search.action, 'disagreement': incumbent != search.action,
                'search_seconds': search.elapsed_seconds, 'branches': search.branch_count,
                'probe_samples': len(measurements), 'replies': replies,
                'direct_completed_control_cells_reproduced': reproduced,
                'search_replies_not_probed': [r for r in search_replies if r not in replies],
                'action_measurements': summaries, 'optimal_action_label': 'unproven'}
            report['cases'].append(result)
            raw.append({'case': case['id'], 'root_view': view, 'ranking': search.ranking, 'measurements': measurements})
            print(case['id'], 'turn', view['turn'], 'samples', len(measurements), 'different', result['disagreement'], flush=True)
            (args.output/'results.json.gz').write_bytes(gzip.compress(json.dumps({'report': report, 'raw': raw}).encode()))
    report['summary'] = {'statuses': dict(Counter(c['status'] for c in report['cases'])),
        'samples': sum(c.get('probe_samples', 0) for c in report['cases']),
        'disagreements': sum(c.get('disagreement', False) for c in report['cases']),
        'weights_changed': False, 'admission_changed': False, 'strength_claim': False}
    args.report.write_text(json.dumps(report, indent=2)+'\n')
    (args.output/'results.json.gz').write_bytes(gzip.compress(json.dumps({'report': report, 'raw': raw}).encode()))
    print(json.dumps(report['summary']))


if __name__ == '__main__':
    main()
