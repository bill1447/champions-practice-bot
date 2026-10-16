"""Compare the exact-tie gameplay rerun against its frozen inventory control."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from full_game_inventory_comparison import metrics, signature


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = [p.read_bytes() for p in (args.control, args.candidate)]
    old, new = [json.loads(gzip.decompress(data)) for data in raw]
    for key in ('cases', 'baseline', 'team_sha256', 'protocol', 'independent_opponent'):
        assert old[key] == new[key], key
    root = Path(__file__).resolve().parents[1]
    for path, expected in new['source_sha256'].items():
        assert hashlib.sha256((root/path).read_bytes()).hexdigest() == expected, path
    changed_sources = [path for path, digest in old['source_sha256'].items()
                       if new['source_sha256'][path] != digest]
    assert set(changed_sources) == {'src/champions_practice/tactical_consequences.py',
                                    'scripts/full_game_native_evaluation.py'}
    assert len(old['games']) == len(new['games']) == 48
    assert all(g['status'] == 'complete' for report in (old, new) for g in report['games'])
    previous = {g['id']: g for g in old['games']}
    parity, transitions = 0, []
    for game in new['games']:
        before = previous[game['id']]
        same = ([signature(r) for r in before['rows']] == [signature(r) for r in game['rows']])
        if game['version'] == 'v2':
            assert same and before['winner'] == game['winner']
            parity += 1
            continue
        if same:
            continue
        first = next((i for i, (a, b) in enumerate(zip(before['rows'], game['rows']))
                      if signature(a) != signature(b)), min(len(before['rows']), len(game['rows'])))
        a, b = before['rows'][first], game['rows'][first]
        assert a['view'] == b['view'] and a['legal_actions'] == b['legal_actions']
        old_scores = {r['action']: r for r in a['decision']['tactical']['ranking']}
        new_scores = {r['action']: r for r in b['decision']['tactical']['ranking']}
        # Coverage/continuation metadata belongs to the selected row, so compare
        # immutable branch evidence and all candidate utility values explicitly.
        for action in old_scores:
            for field in ('worst_world_utility', 'weighted_utility', 'worlds'):
                assert old_scores[action][field] == new_scores[action][field]
        transitions.append({'game': game['id'], 'checkpoint': first, 'turn': a['turn'],
            'before': a['action'], 'after': b['action'],
            'control_win': before['win'], 'candidate_win': game['win'],
            'control_checkpoints': len(before['rows']), 'candidate_checkpoints': len(game['rows']),
            'first_divergence_branch_evidence_identical': True})
    result = {'control_sha256': hashlib.sha256(raw[0]).hexdigest(),
              'candidate_sha256': hashlib.sha256(raw[1]).hexdigest(),
              'source_sha256': new['source_sha256'], 'changed_existing_sources': changed_sources,
              'frozen_v2_exact_trajectory_parity': parity, 'native_changed_games': transitions,
              'control': metrics(old), 'candidate': metrics(new),
              'interpretation': 'Same-case regression, not independent playing-strength replication.'}
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
