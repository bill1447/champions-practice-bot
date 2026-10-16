"""Keep the Charcoal-only repair and the public-prior control distinct."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNS = (
    ('failed_admission', 'runs/paired-continuation/v1/results.json.gz', 'reviews/paired-continuation-manifest-2026-10-16.json'),
    ('charcoal_only', 'runs/paired-continuation/charcoal-v1/results.json.gz', 'reviews/paired-continuation-charcoal-manifest-2026-10-16.json'),
    ('separate_public_prior_control', 'runs/paired-continuation/earthquake-v2/results.json.gz', 'reviews/paired-continuation-earthquake-v2-manifest-2026-10-16.json'),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'reviews/charcoal-continuation-comparison-2026-10-16.json')
    args = parser.parse_args()
    output, reference, previous_manifest = {'runs': []}, None, None
    for name, archive_path, manifest_path in RUNS:
        raw = (ROOT/archive_path).read_bytes()
        data = json.loads(gzip.decompress(raw))
        manifest_raw = (ROOT/manifest_path).read_bytes()
        manifest = json.loads(manifest_raw)
        assert data['manifest_sha256'] == hashlib.sha256(manifest_raw).hexdigest()
        if previous_manifest:
            for field in ('cases', 'rng_labels', 'input_sha256', 'fresh_manifest_sha256'):
                assert previous_manifest[field] == manifest[field], field
            changed = [p for p in manifest['source_sha256'] if
                       previous_manifest['source_sha256'][p] != manifest['source_sha256'][p]]
            assert changed == (['src/champions_practice/persistent_support.py'] if name == 'charcoal_only'
                               else ['scripts/paired_native_continuation.py']), changed
        else:
            changed = []
        if reference:
            assert reference['baseline'] == data['baseline']
        else:
            reference = data
        cases = []
        for case in data['cases']:
            control = next(c for c in reference['cases'] if c['id'] == case['id'])
            old_v2 = {(r['root_role'], r['reply'], r['rng']): r for r in control['rows'] if r['policy'] == 'v2'}
            current_v2 = {(r['root_role'], r['reply'], r['rng']): r for r in case['rows'] if r['policy'] == 'v2'}
            assert old_v2.keys() == current_v2.keys()
            for key, row in current_v2.items():
                assert row['first'] == old_v2[key]['first'] and row['second'] == old_v2[key]['second']
                assert [(d['own_action'], d['enemy_action']) for d in row['decisions']] == [
                    (d['own_action'], d['enemy_action']) for d in old_v2[key]['decisions']]
            native = [r for r in case['rows'] if r['policy'] == 'native']
            decisions = [d for r in native for d in r['decisions']]
            groups = []
            for role in ('selected', 'alternative'):
                rows = [r for r in native if r['root_role'] == role]
                for scope, selected in [('all', rows), ('strict_opposition_matched', [r for r in rows if r['strict_opposition_match']])]:
                    controls = [current_v2[r['root_role'], r['reply'], r['rng']] for r in selected]
                    groups.append({'role': role, 'scope': scope, 'samples': len(selected),
                        'v2_wins': sum(r['second']['terminal_win'] for r in controls),
                        'native_wins': sum(r['second']['terminal_win'] for r in selected),
                        'v2_losses': sum(r['second']['terminal_loss'] for r in controls),
                        'native_losses': sum(r['second']['terminal_loss'] for r in selected),
                        'native_search_trajectories': sum(any(d['trace']['status'] == 'search' for d in r['decisions']) for r in selected)})
            rescued = []
            for row in native:
                baseline = current_v2[row['root_role'], row['reply'], row['rng']]
                if row['strict_opposition_match'] and baseline['second']['terminal_loss'] and not row['second']['terminal_loss']:
                    assert any(d['trace']['status'] == 'search' and d['trace']['disagreement'] for d in row['decisions'])
                    rescued.append({'root_role': row['root_role'], 'reply': row['reply'], 'rng': row['rng'],
                        'decisions': [{'own': d['own_action'], 'v2_incumbent': d['trace'].get('incumbent'),
                                       'status': d['trace']['status'], 'opposition': d['enemy_action']}
                                      for d in row['decisions']]})
            cases.append({'id': case['id'], 'groups': groups, 'v2_exact_trajectory_parity': len(current_v2),
                'statuses': dict(Counter(d['trace']['status'] for d in decisions)),
                'unique_search_computations': sum(d['trace']['status'] == 'search' and not d['cached'] for d in decisions),
                'admitted_occurrences': sum(d['trace'].get('admitted_worlds', 0) > 0 for d in decisions),
                'changed_occurrences': sum(d['trace'].get('disagreement', False) for d in decisions),
                'fallback_reasons': dict(Counter(d['trace']['reason'] for d in decisions if d['trace']['status'] == 'fallback')),
                'prevented_sampled_terminal_losses': rescued})
        output['runs'].append({'name': name, 'archive_sha256': hashlib.sha256(raw).hexdigest(),
            'manifest_sha256': data['manifest_sha256'], 'changed_sources_from_previous': changed,
            'prior_profile': manifest.get('public_prior_profile', 'baseline'), 'cases': cases})
        previous_manifest = manifest
    output['interpretation'] = 'Three separate controls, not pooled. Surviving one turn is not a winning-route claim.'
    args.output.write_text(json.dumps(output, indent=2)+'\n')
    print('Verified roots, responses, RNG labels and 144 unchanged V2 trajectories in each run.')
    for run in output['runs']:
        print(run['name'], 'searches', sum(c['statuses'].get('search', 0) for c in run['cases']),
              'prevented strict-paired terminal losses', sum(len(c['prevented_sampled_terminal_losses']) for c in run['cases']))


if __name__ == '__main__':
    main()
