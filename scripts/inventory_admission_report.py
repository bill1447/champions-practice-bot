"""Condense the frozen inventory position replay without changing old results."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    raw = args.archive.read_bytes()
    data = json.loads(gzip.decompress(raw))
    for path, digest in data['source_sha256'].items():
        assert hashlib.sha256((root/path).read_bytes()).hexdigest() == digest, path
    positions = data.pop('positions')
    result = {**data, 'probe_archive': str(args.archive.resolve().relative_to(root)),
        'probe_archive_sha256': hashlib.sha256(raw).hexdigest(), 'positions': [], 'groups': {}}
    for name, selected in [('all', positions), ('prior_item_covered', [p for p in positions if p['prior_items_covered']]),
                           ('outside_item_priors', [p for p in positions if not p['prior_items_covered']])]:
        result['groups'][name] = {'positions': len(selected),
            'completed_searches': sum(p['decision']['status'] == 'search' for p in selected),
            'fallback_reasons': dict(Counter(p['decision']['reason'] for p in selected if p['decision']['status'] != 'search')),
            'action_disagreements': sum(p['decision']['disagreement'] for p in selected),
            'max_decision_seconds': max((p['decision']['elapsed_seconds'] for p in selected), default=0),
            'eight_second_overruns': sum(p['decision']['elapsed_seconds'] > 8 for p in selected)}
    result['native_controls'] = {'matched_recorded_public_positions': len(positions),
        'inventory_corruptions_rejected': sum(p['control']['corruptions_rejected'] for p in positions)}
    for position in positions:
        decision = position['decision']
        assert decision['status'] == 'search' or decision['action'] == decision['incumbent']
        result['positions'].append({k: v for k, v in position.items() if k != 'decision'} | {
            'status': decision['status'], 'reason': decision['reason'], 'admitted_worlds': decision['admitted_worlds'],
            'incumbent': decision['incumbent'], 'action': decision['action'], 'disagreement': decision['disagreement'],
            'elapsed_seconds': decision['elapsed_seconds'], 'admission': decision.get('admission'),
            'branch_count': decision['tactical']['branch_count'] if decision['tactical'] else 0})
    result['limitations'] = ['Position replay only; no new game outcomes or playing-strength estimate.',
        'Original 15/24 versus 10/24 games remain unchanged.',
        'All earlier decisions and public observations come from retained paths, not new-player trajectories.',
        'No new priors, scoring weights, response counts, horizon or decision budget.',
        'Separate native replay controls use oracle fixture sets/seeds; these never enter admission decisions.']
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'groups': result['groups'], 'native_controls': result['native_controls']}, indent=2))


if __name__ == '__main__':
    main()
