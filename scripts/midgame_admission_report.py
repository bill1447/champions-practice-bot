"""Audit native midgame availability, epistemic roots and route comparisons."""

from collections import Counter
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    path = ROOT/'runs/v2-midgame-admission/v9/positions.json'
    control_path = ROOT/'runs/v2-midgame-admission/inactive-controls-v1/controls.json'
    result, controls = json.loads(path.read_text()), json.loads(control_path.read_text())
    for archive in (result, controls):
        for relative, expected in archive['source_sha256'].items():
            assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest() == expected, relative
    assert len(result['positions']) == 12
    complete = [p for p in result['positions'] if p['status'] == 'complete']
    assert len(complete) == 8
    for position in complete:
        assert not any(position['projected_root_differences'])
        assert len(position['plan_requirements']['comparisons']) == len(position['tactical']['ranking'])
        assert all(c['native_leaf_samples'] >= 1 for c in position['plan_requirements']['comparisons'])
        assert position['public_origin_controls']
    reasons = Counter(p.get('production_fallback_reason') for p in result['positions'] if p['status'] != 'complete')
    negative = Counter(control for p in complete for control in p['negative_controls'])
    def compact_requirements(requirements):
        value = {**requirements, 'comparisons': []}
        for comparison in requirements['comparisons']:
            item = {**comparison, 'routes': []}
            for route in comparison['routes']:
                item['routes'].append({k: v for k, v in route.items() if k != 'samples'} | {
                    'minimum_own_remaining': min(s['own_remaining'] for s in route['samples']),
                    'maximum_opponent_remaining': max(s['opponent_remaining'] for s in route['samples'])})
            value['comparisons'].append(item)
        return value
    report = {'before_usable': 0, 'after_admitted': 8, 'after_complete': 8, 'cases': 12,
        'summary': result['summary'], 'remaining_reasons': dict(reasons), 'negative_controls': dict(negative),
        'native_switch_controls': controls['controls'],
        'archive_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (path, control_path)},
        'positions': [{k: p[k] for k in ('id', 'family', 'status', 'turn', 'admitted_particles',
            'production_mode', 'production_fallback_reason', 'root_information_difference',
            'root_vs_authoritative_differences', 'projected_root_differences', 'public_origin_controls') if k in p}
            | ({'plan_requirements': compact_requirements(p['plan_requirements'])} if 'plan_requirements' in p else {}) for p in result['positions']],
        'scope': 'Public-only source checkpoints, native mechanical admission plus authoritative-origin projection, one-turn 8/3 comparisons. Route requirements are descriptive; no new move bonuses or plan-selection policy. No full-game intervention or strength claim.'}
    (ROOT/'reviews/v2-midgame-admission-2026-10-15.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: report[k] for k in ('before_usable', 'after_admitted', 'after_complete', 'remaining_reasons', 'negative_controls')}, indent=2))


if __name__ == '__main__':
    main()
