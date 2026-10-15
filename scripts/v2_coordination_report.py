"""Validate paired coordination evidence and replay public-entry-point decisions."""

import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
from statistics import median
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog, decide, observe
from champions_practice.agent_v2.policy import rank_action
from v2_repair_gameplay import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archives', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    metadata = PublicCatalog.load(ROOT)
    results = []
    for path in args.archives:
        report = json.loads(gzip.decompress(path.read_bytes()))
        assert metadata.fingerprint == report['catalog_sha256']
        pairs = defaultdict(dict)
        durations, changed, parity = [], 0, 0
        decisions, overruns, exhausted = 0, 0, 0
        for game in report['games']:
            assert game['status'] == 'complete'
            assert game['agent'] not in pairs[game['pair']]
            pairs[game['pair']][game['agent']] = game
            for row in game['rows']:
                assert row['decision']['action'] in row['legal_actions']
                decisions += 1
                overruns += row['budget_overrun']
                exhausted += row['decision']['deadline_exhausted']
                if game['agent'] == 'candidate':
                    durations.append(row['elapsed_seconds'] * 1000)
                    board = observe(row['view'], row['legal_actions'], deadline=perf_counter()+8)
                    current = decide(board, metadata)
                    assert current.action == row['decision']['action']
                    parity += 1
                    assert rank_action(current.action, board, metadata).score == max(
                        rank_action(action, board, metadata).score for action in board.legal_actions)
        strata = {}
        for pair in pairs.values():
            assert set(pair) == {'baseline', 'candidate'}
            old, new = pair['baseline'], pair['candidate']
            assert all(old[k] == new[k] for k in ('seed', 'side', 'p1_team', 'p2_team', 'opponent'))
            for a, b in zip(old['rows'], new['rows']):
                if a['decision']['action'] != b['decision']['action']:
                    assert a['view'] == b['view']
                    assert rank_action(a['decision']['action'], observe(a['view'], a['legal_actions'],
                        deadline=perf_counter()+8), metadata).score == rank_action(b['decision']['action'],
                        observe(b['view'], b['legal_actions'], deadline=perf_counter()+8), metadata).score
                    changed += 1
                    break
        for opponent in ('pressure', 'guard'):
            group = [p for p in pairs.values() if p['baseline']['opponent'] == opponent]
            strata[opponent] = {'pairs': len(group),
                'baseline_wins': sum(p['baseline']['win'] for p in group),
                'candidate_wins': sum(p['candidate']['win'] for p in group),
                'candidate_only_wins': sum(p['candidate']['win'] and not p['baseline']['win'] for p in group),
                'baseline_only_wins': sum(p['baseline']['win'] and not p['candidate']['win'] for p in group)}
        times = sorted(durations)
        results.append({'archive': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'baseline_ref': report['baseline_ref'], 'team_suite': report.get('team_suite', 'original'),
            'baseline_policy_sha256': report['baseline_policy_sha256'],
            'tested_candidate_policy_sha256': report['candidate_policy_sha256'],
            'strata': strata, 'decisions': decisions, 'budget_overruns': overruns,
            'deadline_exhaustions': exhausted, 'pairs_with_first_action_change': changed,
            'public_default_action_parity': parity,
            'candidate_ms': {'median': median(times), 'p95': times[int(.95*(len(times)-1))], 'max': max(times)}})
    files = ('src/champions_practice/agent_v2/policy.py', 'src/champions_practice/agent_v2/joint.py',
             'tools/agent-v2-catalog.js', 'src/champions_practice/competitive_evaluation.py',
             'src/champions_practice/risk_joint_audit.py', 'scripts/v2_repair_gameplay.py')
    output = {'evidence': results, 'current_runtime_sha256': {
        name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files},
        'catalog_sha256': metadata.fingerprint,
        'limitations': ['Related synthetic opponents; team and seed outcomes are correlated.',
                        'Action parity verifies default routing, not a new independent gameplay sample.',
                        'No sealed final holdout accessed; no competitive strength claim.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
