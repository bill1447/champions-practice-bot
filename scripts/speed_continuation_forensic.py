"""Exact-world forensic branches, explicitly NOT public native admissions."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog, observe
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.plan_consequences import exact_log_lines
from champions_practice.search_worker import HypotheticalSearchWorker
from paired_native_continuation import facts, seed
from tactical_consequences_evaluation import frozen_policy


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'runs/paired-continuation/speed-forensic-v1')
    parser.add_argument('--report', type=Path, default=ROOT/'reviews/speed-continuation-forensic-2026-10-16.json')
    args = parser.parse_args()
    assert not args.output.exists()
    args.output.mkdir(parents=True)
    manifest_path = ROOT/'reviews/paired-continuation-manifest-2026-10-16.json'
    manifest = json.loads(manifest_path.read_text())
    fresh = json.loads((ROOT/'reviews/fresh-tactical-manifest-v2-2026-10-15.json').read_text())
    spec = manifest['cases'][0]
    case = next(c for c in fresh['cases'] if c['id'] == spec['id'])
    floor_reply = spec['root_floor_attribution'][spec['selected']]['controlling_responses'][0]['reply']
    assert floor_reply in {r['reply'] for r in spec['root_floor_attribution'][spec['alternative']]['controlling_responses']}
    report = {'scope': 'Exploratory exact-state move forensics, not a public-only continuation policy or admitted native search.',
        'case': spec['id'], 'fixed_root_reply': floor_reply, 'parent_manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        'protocol': 'Both fixed roots, all four original labels, original V2 phase completion. At the next actionable own move, enumerate every legal own command against the same frozen-V2 opposing reply and coupled RNG. No policy is selected from these results.',
        'source_sha256': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [Path(__file__).resolve(), ROOT/'scripts/paired_native_continuation.py', ROOT/'tools/showdown-search-worker.js']},
        'samples': []}
    (args.output/'manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    catalog = PublicCatalog.load(ROOT)
    policy, _ = frozen_policy('e0ae723')
    previews = {'p1': case['own_roster'], 'p2': case['enemy_roster']}
    with HypotheticalSearchWorker(ROOT, startup_deadline=perf_counter()+60) as worker:
        def choose(state, side, full=True):
            view = worker.state_view(state=state, side=side, previews=previews if full else None)
            menu = worker.legal_choices(state=state, side=side)
            return policy(observe(view, menu, deadline=perf_counter()+8), catalog).action

        def branch(state, own, enemy, rng):
            assert own in worker.legal_choices(state=state, side='p1')
            assert enemy in worker.legal_choices(state=state, side='p2')
            return worker.branch_many(state=state, branches=[{'p1_choice': own, 'p2_choice': enemy,
                'rng_seed': rng, 'include_state': True}])[0]

        state = worker.create_state(battle_format=CHAMPIONS_FORMAT, p1_team=case['own_team'], p2_team=case['enemy_team'],
            p1_preview=case['preview'], p2_preview=case['preview'], seed=case['seed'])
        for step in range(case['warmup_completed_turns']):
            goal = worker.state_view(state=state, side='p1')['turn']+1
            for phase in range(6):
                outcome = branch(state, choose(state, 'p1', False), choose(state, 'p2', False),
                    seed(case['id']+f':prefix:{step}') if phase == 0 else seed(case['id']+f':prefix-complete:{step}'))
                state = outcome['state']
                if outcome['summary']['ended'] or outcome['summary']['turn'] >= goal:
                    break
            else:
                raise AssertionError('prefix phase bound')
        root_turn = worker.state_view(state=state, side='p1')['turn']
        for role in ('selected', 'alternative'):
            for roll, rng in enumerate(manifest['rng_labels']):
                outcome = branch(state, spec[role], floor_reply, rng)
                for _ in range(12):
                    assert not outcome['summary']['ended'], 'Unexpected terminal before next own move'
                    parent = outcome['state']
                    view = worker.state_view(state=parent, side='p1', previews=previews)
                    menu = worker.legal_choices(state=parent, side='p1')
                    if view['turn'] >= root_turn+1 and view['phase'] == 'move' and menu != ['wait']:
                        break
                    outcome = branch(parent, choose(parent, 'p1'), choose(parent, 'p2'),
                        seed(rng+(':phase' if view['turn'] < root_turn+1 else ':next')))
                else:
                    raise AssertionError('No next actionable move within bound')
                parent = outcome['state']
                selected = choose(parent, 'p1')
                enemy = choose(parent, 'p2')
                alternatives = []
                for own in menu:
                    result = branch(parent, own, enemy, seed(rng+':next'))
                    for _ in range(6):
                        if result['summary']['ended'] or result['summary']['turn'] >= root_turn+2:
                            break
                        child = result['state']
                        result = branch(child, choose(child, 'p1'), choose(child, 'p2'), seed(rng+':next'))
                    else:
                        raise AssertionError('forensic phase bound')
                    alternatives.append({'action': own, 'measurement': facts(result['summary']),
                        'native_events': list(exact_log_lines(result['state']['log'][len(parent['log']):]))})
                report['samples'].append({'root_role': role, 'rng': roll, 'public_own_request': view['request'],
                    'public_opponents': view['opponent'], 'v2_action': selected, 'opponent_reply': enemy,
                    'alternatives': alternatives})
    args.report.write_text(json.dumps(report, indent=2)+'\n')
    (args.output/'results.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    print('Forensic samples:', len(report['samples']), 'branches:', sum(len(s['alternatives']) for s in report['samples']))
    for row in report['samples']:
        selected = next(a for a in row['alternatives'] if a['action'] == row['v2_action'])
        survivors = [a['action'] for a in row['alternatives'] if not a['measurement']['terminal_loss']]
        print(row['root_role'], row['rng'], row['v2_action'], 'loss:', selected['measurement']['terminal_loss'], 'nonlosing:', survivors)


if __name__ == '__main__':
    main()
