"""Audit the public-only factorial, explicitly separating fallback from search."""

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--forensic', type=Path)
    args = parser.parse_args()
    raw = args.archive.read_bytes()
    data = json.loads(gzip.decompress(raw))
    manifest = json.loads(args.manifest.read_text())
    root = Path(__file__).resolve().parents[1]
    assert data['manifest_sha256'] == hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    for path, expected in manifest['source_sha256'].items():
        assert hashlib.sha256((root/path).read_bytes()).hexdigest() == expected, path
    assert [c['id'] for c in data['cases']] == [c['id'] for c in manifest['cases']]
    output = {'archive_sha256': hashlib.sha256(raw).hexdigest(), 'manifest_sha256': data['manifest_sha256'],
        'cases': [], 'limitations': manifest['protocol']['limits']}
    for case, spec in zip(data['cases'], manifest['cases'], strict=True):
        rows = case['rows']
        expected = {(role, policy, reply, roll) for role in ('selected', 'alternative')
                    for policy in ('v2', 'native') for reply in spec['replies']
                    for roll in range(len(manifest['rng_labels']))}
        counts = Counter((r['root_role'], r['policy'], r['reply'], r['rng']) for r in rows)
        assert set(counts) == expected and set(counts.values()) == {1}
        information = {}
        for row in rows:
            assert row['root_action'] == spec[row['root_role']]
            assert row['second']['ended'] or row['second']['turn'] >= row['first']['turn']
            for stage in ('first', 'second'):
                leaf = row[stage]
                if leaf['terminal_win']:
                    assert leaf['utility']['total'] == 1_000_000
                if leaf['terminal_loss']:
                    assert leaf['utility']['total'] == -1_000_000
            for decision in row['decisions']:
                key = (row['policy'], decision['information_key'])
                value = (decision['own_action'], decision['trace']['status'])
                if key in information:
                    assert information[key] == value, 'Same public history produced a different decision'
                information[key] = value
                trace = decision['trace']
                if trace['status'] == 'search':
                    assert trace['admitted_worlds'] > 0 and trace['tactical']['status'] == 'complete'
                    assert trace['elapsed_seconds'] <= 8
                if trace['status'] == 'fallback':
                    assert decision['own_action'] == trace['incumbent']
        cells = []
        for role in ('selected', 'alternative'):
            for policy in ('v2', 'native'):
                group = [r for r in rows if r['root_role'] == role and r['policy'] == policy]
                cells.append({'role': role, 'policy': policy, 'samples': len(group),
                    'first_wins': sum(r['first']['terminal_win'] for r in group),
                    'first_losses': sum(r['first']['terminal_loss'] for r in group),
                    'second_wins': sum(r['second']['terminal_win'] for r in group),
                    'second_losses': sum(r['second']['terminal_loss'] for r in group),
                    'trajectories_with_native_search': sum(any(d['trace']['status'] == 'search' for d in r['decisions']) for r in group),
                    'strict_opposition_matched': sum(r['strict_opposition_match'] for r in group)})
        decisions = [d for r in rows if r['policy'] == 'native' for d in r['decisions']]
        unique = [d for d in decisions if not d['cached']]
        by_scenario = defaultdict(dict)
        for row in rows:
            by_scenario[row['root_role'], row['reply'], row['rng']][row['policy']] = row
        for pair in by_scenario.values():
            if not any(d['trace']['status'] == 'search' for d in pair['native']['decisions']):
                assert pair['v2']['first'] == pair['native']['first']
                assert pair['v2']['second'] == pair['native']['second']
                assert [(d['own_action'], d['enemy_action']) for d in pair['v2']['decisions']] == [
                    (d['own_action'], d['enemy_action']) for d in pair['native']['decisions']]
        output['cases'].append({'id': case['id'], 'cells': cells,
            'native_decision_occurrences': dict(Counter(d['trace']['status'] for d in decisions)),
            'native_unique_computations': dict(Counter(d['trace']['status'] for d in unique)),
            'fallback_occurrence_reasons': dict(Counter(d['trace']['reason'] for d in decisions if d['trace']['status'] == 'fallback')),
            'unique_fallback_reasons': dict(Counter(d['trace']['reason'] for d in unique if d['trace']['status'] == 'fallback')),
            'v2_historical_outcome_parity': dict(Counter(str(r['historical_v2_probe_parity']) for r in rows if r['policy'] == 'v2')),
            'root_floor_attribution': spec['root_floor_attribution'],
            'public_native_effect_identified': any(d['trace']['status'] == 'search' for d in decisions)})
    output['summary'] = {'cases': len(data['cases']), 'trajectories': sum(len(c['rows']) for c in data['cases']),
        'successful_native_search_occurrences': sum(c['native_decision_occurrences'].get('search', 0) for c in output['cases']),
        'native_fallback_occurrences': sum(c['native_decision_occurrences'].get('fallback', 0) for c in output['cases']),
        'unique_native_fallback_computations': sum(c['native_unique_computations'].get('fallback', 0) for c in output['cases']),
        'forced_wait_occurrences': sum(c['native_decision_occurrences'].get('nonactionable', 0) for c in output['cases']),
        'interpretation': 'Zero searches cannot establish native continuation quality; fallback-equivalent cells are not native-search results.'}
    if args.forensic:
        forensic_raw = args.forensic.read_bytes()
        forensic = json.loads(forensic_raw)
        assert forensic['parent_manifest_sha256'] == data['manifest_sha256']
        for path, expected in forensic['source_sha256'].items():
            assert hashlib.sha256((root/path).read_bytes()).hexdigest() == expected, path
        assert {(s['root_role'], s['rng']) for s in forensic['samples']} == {
            (role, roll) for role in ('selected', 'alternative') for roll in range(4)}
        assert len(forensic['samples']) == 8
        compact = []
        for sample in forensic['samples']:
            alternatives = {a['action']: a for a in sample['alternatives']}
            assert len(alternatives) == len(sample['alternatives']) == 10
            chosen = alternatives[sample['v2_action']]
            protect = alternatives['move protect, pass']
            glide = alternatives['move grassyglide +2, pass']
            assert not protect['measurement']['ended']
            compact.append({'root_role': sample['root_role'], 'rng': sample['rng'],
                'own_conditions': {m['ident']: m['condition'] for m in sample['public_own_request']['side']['pokemon']},
                'v2_action': sample['v2_action'], 'opponent_reply': sample['opponent_reply'],
                'v2_terminal_loss': chosen['measurement']['terminal_loss'],
                'protect_terminal_loss': protect['measurement']['terminal_loss'],
                'grassy_glide_into_second_target_terminal_loss': glide['measurement']['terminal_loss'],
                'v2_wood_hammer_executed': any('|move|p1a:' in line and '|Wood Hammer|' in line for line in chosen['native_events']),
                'v2_recoil_damage_recorded': any('[from] Recoil' in line for line in chosen['native_events'])})
        output['speed_forensic'] = {'expanded_report_sha256': hashlib.sha256(forensic_raw).hexdigest(),
            'scope': forensic['scope'], 'fixed_root_reply': forensic['fixed_root_reply'],
            'states': 8, 'branches': 80, 'samples': compact}
    args.output.write_text(json.dumps(output, indent=2)+'\n')
    print(json.dumps(output['summary']))


if __name__ == '__main__':
    main()
