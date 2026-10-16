"""Compare the inventory rerun with its frozen full-game control archive."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path


def signature(row):
    return json.dumps({k: row[k] for k in ('turn', 'phase', 'view', 'legal_actions',
                                          'action', 'enemy_action', 'enemy_trace')}, sort_keys=True)


def metrics(report):
    summary = report['summary']
    native = [g for g in report['games'] if g['version'] == 'native']
    rows = [r for g in native for r in g['rows'] if r['decision']['admission_attempted']]
    late = [r for r in rows if r['turn'] >= 4]
    return {'outcomes': summary['all'], 'opponent_fallback_free': summary['opponent_fallback_free'],
        'actionable_decisions': len(rows), 'completed_searches': sum(r['decision']['status'] == 'search' for r in rows),
        'disagreements': sum(r['decision']['disagreement'] for r in rows),
        'late_actionable': len(late), 'late_completed_searches': sum(r['decision']['status'] == 'search' for r in late),
        'fallback_reasons': summary['fallback_reasons'], 'latency': summary['latency'],
        'coverage_by_turn': summary['coverage_by_turn'],
        'strata': {key: {label: value['all'] for label, value in values.items()}
                   for key, values in report['strata'].items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    raw_old, raw_new = args.control.read_bytes(), args.candidate.read_bytes()
    old, new = [json.loads(gzip.decompress(raw)) for raw in (raw_old, raw_new)]
    assert old['cases'] == new['cases'] and old['baseline'] == new['baseline']
    assert old['team_sha256'] == new['team_sha256'] and old['protocol'] == new['protocol']
    assert old['independent_opponent'] == new['independent_opponent']
    assert len(old['games']) == len(new['games']) == 48
    assert all(g['status'] == 'complete' for report in (old, new) for g in report['games'])
    provenance = json.loads((args.candidate.parent/'inventory-provenance.json').read_text())
    assert provenance['control_archive_sha256'] == hashlib.sha256(raw_old).hexdigest()
    for path, digest in provenance['source_sha256'].items():
        assert hashlib.sha256((root/path).read_bytes()).hexdigest() == digest, path
    control = {g['id']: g for g in old['games']}
    baseline_parity, transitions = 0, []
    for game in new['games']:
        previous = control[game['id']]
        if game['version'] == 'v2':
            assert game['winner'] == previous['winner']
            assert [signature(r) for r in game['rows']] == [signature(r) for r in previous['rows']]
            baseline_parity += 1
            continue
        first = None
        for index, (before, after) in enumerate(zip(previous['rows'], game['rows'])):
            if signature(before) != signature(after):
                first = {'checkpoint': index, 'turn': after['turn'], 'phase': after['phase'],
                    'same_public_position': before['view'] == after['view'],
                    'old_action': before['action'], 'new_action': after['action'],
                    'old_status': before['decision']['status'], 'old_reason': before['decision']['reason'],
                    'new_status': after['decision']['status'], 'new_reason': after['decision']['reason'],
                    'old_realized_reply': before['enemy_action'], 'new_realized_reply': after['enemy_action'],
                    'new_candidate_ranking': [{k: candidate[k] for k in
                        ('action', 'worst_world_utility', 'weighted_utility')}
                        for candidate in after['decision']['tactical']['ranking']]
                        if after['decision']['tactical'] else None}
                break
        if first is None:
            assert len(previous['rows']) == len(game['rows']) and previous['winner'] == game['winner']
        transitions.append({'game': game['id'], 'old_win': previous['win'], 'new_win': game['win'],
                            'old_checkpoints': len(previous['rows']), 'new_checkpoints': len(game['rows']),
                            'first_trajectory_difference': first})
    result = {'control_archive_sha256': hashlib.sha256(raw_old).hexdigest(),
        'candidate_archive_sha256': hashlib.sha256(raw_new).hexdigest(), 'provenance': provenance,
        'control': metrics(old), 'candidate': metrics(new), 'unchanged_v2_trajectories': baseline_parity,
        'native_outcome_transitions': dict(Counter(f"{p['old_win']}->{p['new_win']}" for p in transitions)),
        'native_trajectory_changes': sum(p['first_trajectory_difference'] is not None for p in transitions),
        'native_games': transitions,
        'limitations': ['Same examined teams, opponents, hidden families and seeds; regression comparison, not fresh validation.',
            'Changed actions alter subsequent paths, RNG consumption and coverage denominators.',
            'Both native arms retain V2 on unsupported positions; no experimental promotion or strategic score changes.']}
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: result[k] for k in ('control', 'candidate', 'unchanged_v2_trajectories',
        'native_outcome_transitions', 'native_trajectory_changes')}, indent=2))


if __name__ == '__main__':
    main()
