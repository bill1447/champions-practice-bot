"""Audit the failed weather boundary and separately frozen safety probes."""

from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    diagnosis_path = ROOT/'runs/weather-admission/before-v1/diagnostic.json'
    diagnosis = json.loads(diagnosis_path.read_text())
    assert diagnosis['probe_calls'] == 48 and diagnosis['actionable_fallback_occurrences'] == 74
    assert diagnosis['public_rain_fresh_opening_without_rain'] == 48
    assert diagnosis['native_rejections'] == {'unsupported-public-weather-plan': 48}
    for probe in diagnosis['probes']:
        assert probe['public_plan']['weather'] == probe['public_weather'] == 'raindance'
        assert not probe['hypothetical_opening_weather'] and not probe['outcomes']
        assert 'Pelipper' in probe['opening_public_snapshot']['active_species']['opponent']
        assert probe['hypothetical_drizzle_members'] == [{'side': 0, 'species': 'Pelipper', 'item': 'focussash', 'active': False}]
    sample = diagnosis['probes'][0]
    output = {'weather_diagnosis': {'raw_diagnostic_sha256': hashlib.sha256(diagnosis_path.read_bytes()).hexdigest(),
        **{k: diagnosis[k] for k in ('probe_calls', 'actionable_fallback_occurrences', 'native_rejections', 'scope')},
        'example': {k: sample[k] for k in ('turn', 'phase', 'public_weather', 'public_plan',
            'hypothetical_opening_weather', 'hypothetical_drizzle_members')},
        'example_public_opening_actors': sample['opening_public_snapshot']['active_species']}}
    manifest_path = ROOT/'reviews/tactical-safety-v2-manifest-2026-10-16.json'
    manifest = json.loads(manifest_path.read_text())
    raw_path = ROOT/'runs/tactical-safety/v2/results.json.gz'
    raw = json.loads(gzip.decompress(raw_path.read_bytes()))
    report = raw['report']
    assert report['manifest_sha256'] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    for path, digest in manifest['source_sha256'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == digest, path
    assert {c['id'] for c in report['cases']} == {c['id'] for c in manifest['cases']}
    assert len(report['cases']) == 12
    assert {c['case'] for c in raw['raw']} == {c['id'] for c in report['cases'] if c['status'] == 'probed'}
    for case in raw['raw']:
        trace, samples = case['decision'], case['samples']
        selected, incumbent = trace['action'], trace['incumbent']
        cells = Counter((s['action'], s['reply'], s['rng']) for s in samples)
        assert set(cells.values()) == {1}
        replies = {s['reply'] for s in samples}
        assert set(cells) == {(action, reply, roll) for action in {selected, incumbent} for reply in replies for roll in range(4)}
        if trace['status'] == 'search':
            assert trace['admitted_worlds'] > 0 and trace['tactical']['status'] == 'complete'
            assert trace['elapsed_seconds'] <= 8
        else:
            assert selected == incumbent
        for row in samples:
            fact = row['facts']
            if fact['terminal_win']:
                assert fact['utility']['total'] == 1_000_000
            if fact['terminal_loss']:
                assert fact['utility']['total'] == -1_000_000
        reference = {(s['reply'], s['rng']): s for s in samples if s['action'] == incumbent}
        candidate = {(s['reply'], s['rng']): s for s in samples if s['action'] == selected}
        expected = {
            'native_additional_terminal_wins': sum(candidate[k]['facts']['terminal_win'] and not reference[k]['facts']['terminal_win'] for k in reference),
            'native_avoided_terminal_losses': sum(reference[k]['facts']['terminal_loss'] and not candidate[k]['facts']['terminal_loss'] for k in reference),
            'native_additional_terminal_losses': sum(candidate[k]['facts']['terminal_loss'] and not reference[k]['facts']['terminal_loss'] for k in reference),
            'native_lost_terminal_wins': sum(reference[k]['facts']['terminal_win'] and not candidate[k]['facts']['terminal_win'] for k in reference)}
        saved = next(c for c in report['cases'] if c['id'] == case['case'])
        assert all(saved[k] == v for k, v in expected.items())
    cases = [c for c in report['cases'] if c['status'] == 'probed']
    searches = [c for c in cases if c['native_status'] == 'search']
    output['separate_fresh_probe'] = {'archive_sha256': hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        'manifest_sha256': report['manifest_sha256'], 'frozen_cases': 12,
        'probed': len(cases), 'native_search_positions': len(searches),
        'paired_scenarios': sum(c['matched_scenarios'] for c in cases),
        'paired_scenarios_with_search': sum(c['matched_scenarios'] for c in searches),
        'native_terminal_improvements': sum(c['native_additional_terminal_wins']+c['native_avoided_terminal_losses'] for c in searches),
        'native_terminal_regressions': sum(c['native_additional_terminal_losses']+c['native_lost_terminal_wins'] for c in searches),
        'interpretation': 'Too few admitted positions to establish broader tactical quality. Nonterminal choices remain ungraded.'}
    (ROOT/'reviews/weather-admission-audit-2026-10-16.json').write_text(json.dumps(output, indent=2)+'\n')
    print(json.dumps(output['separate_fresh_probe']))


if __name__ == '__main__':
    main()
