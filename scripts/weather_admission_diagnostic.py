"""Read-only instrumentation of the retained spread/trade admission failure."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import sys

import paired_native_continuation as experiment
from champions_practice.present_mechanics import public_weather_plan


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    args.output.mkdir(parents=True)
    source = ROOT/'reviews/paired-continuation-earthquake-v2-manifest-2026-10-16.json'
    manifest = json.loads(source.read_text())
    manifest['cases'] = [c for c in manifest['cases'] if c['id'] == 'trade-and-spread-warmup-2']
    manifest['diagnostic'] = {'read_only_instrumentation_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                              'parent_manifest_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    subset = args.output/'subset-manifest.json'
    subset.write_text(json.dumps(manifest, indent=2)+'\n')
    probes = []
    original = experiment.ExperimentalNativePlayer

    class LoggedPlayer(original):
        def _bounded(self, operation, deadline):
            ledger = self.ledger

            class ReadOnlyWorker:
                def __init__(self, worker):
                    self.worker = worker

                def __getattr__(self, name):
                    return getattr(self.worker, name)

                def materialize_present_hypotheses(self, **kwargs):
                    state, view = kwargs['state'], kwargs['current_view']
                    result = self.worker.materialize_present_hypotheses(**kwargs)
                    probes.append({'turn': view['turn'], 'phase': view['phase'],
                        'public_weather': view['field']['weather'],
                        'public_plan': public_weather_plan(view, ledger),
                        'opening_public_snapshot': json.loads(ledger.field_snapshots[0][1]),
                        'hypothetical_opening_weather': state['field']['weather'],
                        'hypothetical_drizzle_members': [{'side': i, 'species': m['set']['species'], 'item': m['item'],
                            'active': m['isActive']} for i, s in enumerate(state['sides']) for m in s['pokemon'] if m['ability'] == 'drizzle'],
                        'native_rejection': result.get('reason'), 'outcomes': len(result['outcomes'])})
                    return result

            return super()._bounded(lambda worker: operation(ReadOnlyWorker(worker)), deadline)

    experiment.ExperimentalNativePlayer = LoggedPlayer
    sys.argv = ['paired_native_continuation.py', 'evaluate', '--manifest', str(subset), '--output', str(args.output/'run')]
    try:
        experiment.main()
    finally:
        experiment.ExperimentalNativePlayer = original
    raw = json.loads(gzip.decompress((args.output/'run/results.json.gz').read_bytes()))
    decisions = [d for c in raw['cases'] for r in c['rows'] if r['policy'] == 'native' for d in r['decisions']]
    summary = {'probe_calls': len(probes), 'native_rejections': dict(Counter(p['native_rejection'] for p in probes)),
        'actionable_fallback_occurrences': sum(d['trace']['status'] == 'fallback' for d in decisions),
        'public_rain_fresh_opening_without_rain': sum(p['public_weather'] == 'raindance' and not p['hypothetical_opening_weather'] for p in probes),
        'scope': 'Read-only public history / hypothetical-constructor instrumentation; no live hidden state or admission bypass.',
        'probes': probes}
    (args.output/'diagnostic.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'probes'}))


if __name__ == '__main__':
    main()
