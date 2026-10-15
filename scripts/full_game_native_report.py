"""Audit and condense a completed full-game archive, without rerunning policy."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path


def audit(root, archive):
    raw = archive.read_bytes()
    data = json.loads(gzip.decompress(raw))
    assert all(g['status'] == 'complete' for g in data['games'])
    for path, digest in data['source_sha256'].items():
        assert hashlib.sha256((root/path).read_bytes()).hexdigest() == digest, path
    rows = [(g, i, r) for g in data['games'] if g['version'] == 'native' for i, r in enumerate(g['rows'])]
    actionable = [(g, i, r) for g, i, r in rows if r['decision']['admission_attempted']]
    for g, i, row in rows:
        trace = row['decision']
        assert row['action'] in row['legal_actions']
        assert trace['deadline_seconds'] == 8
        if trace['status'] != 'search':
            assert row['action'] == trace['incumbent']
        else:
            assert trace['admitted_worlds'] > 0 and trace['tactical']['status'] == 'complete'
            assert 'position_assessment' in trace
        assert 'strategy' in trace
    changed = []
    for game, index, row in actionable:
        trace = row['decision']
        if not trace['disagreement']:
            continue
        ranking = trace['tactical']['ranking']
        selected = next(c for c in ranking if c['action'] == row['action'])
        incumbent = next((c for c in ranking if c['action'] == trace['incumbent']), None)
        next_view = game['rows'][index+1]['view'] if index+1 < len(game['rows']) else None
        changed.append({'game': game['id'], 'checkpoint': index, 'turn': row['turn'], 'phase': row['phase'],
            'game_win': game['win'], 'incumbent': trace['incumbent'], 'selected': row['action'],
            'selected_worst_utility': selected['worst_world_utility'],
            'incumbent_worst_utility': incumbent['worst_world_utility'] if incumbent else None,
            'realized_reply': row['enemy_action'],
            'next_public_events': next_view['public_event_delta'] if next_view else None,
            'next_public_field': next_view['field'] if next_view else None,
            'next_owned_hp': [{'species': m['species'], 'hp_percent': m['hp_percent'], 'fainted': m['fainted']}
                              for m in next_view['player']['team']] if next_view else None})
    return {'archive': str(archive.relative_to(root)), 'archive_sha256': hashlib.sha256(raw).hexdigest(),
        'source_sha256': data['source_sha256'], 'baseline': data['baseline'], 'protocol': data['protocol'],
        'independent_opponent': data['independent_opponent'], 'limitations': data['limitations'],
        'summary': data['summary'], 'strata': data['strata'],
        'phase_coverage': {phase: {'actionable': len(rs),
            'search_completed': sum(r['decision']['status'] == 'search' for r in rs)}
            for phase in sorted({r['phase'] for _, _, r in actionable})
            if (rs := [r for _, _, r in actionable if r['phase'] == phase])},
        'opponent_fallbacks': sum(r['enemy_trace']['fallback'] for g in data['games'] for r in g['rows']),
        'experimental_searches_per_game': dict(Counter(
            sum(r['decision']['status'] == 'search' for r in g['rows'])
            for g in data['games'] if g['version'] == 'native')),
        'changed_decision_forensics': changed,
        'audit': ['All games complete; every selected action in its authoritative menu.',
                  'Every fallback retains V2; every completed search has admitted worlds and route diagnostics.',
                  'Every checkpoint has public strategy telemetry; eight-second protocol recorded.',
                  'Recorded policy/simulator source hashes match current files.',
                  'Realized replies, subsequent observations and outcomes are offline forensics only.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report = audit(root, args.archive.resolve())
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'outcomes': report['summary']['all'], 'phase_coverage': report['phase_coverage'],
                      'latency': report['summary']['latency'], 'audit': report['audit']}, indent=2))


if __name__ == '__main__':
    main()
