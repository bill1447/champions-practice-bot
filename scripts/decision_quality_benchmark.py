"""Freeze archival checkpoints, then audit root ties and measured opportunities."""

import argparse
from collections import Counter
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

from champions_practice.consequence_ties import order_exact_ties


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = 'runs/v2-full-game-native/inventory-v1/games.json.gz'
DIAGNOSTIC = 'runs/v2-preservation-conversion/frozen-v4/results.json.gz'
PROTOCOL = 'reviews/decision-quality-protocol-2026-10-15.md'


def digest(path):
    return hashlib.sha256((ROOT/path).read_bytes()).hexdigest()


def load(path):
    return json.loads(gzip.decompress((ROOT/path).read_bytes()))


def matrices(games):
    return {(g['id'], index): row for g in games if g['version'] == 'native'
            for index, row in enumerate(g['rows'])
            if (row['decision'].get('tactical') or {}).get('ranking')}


def audit(ranking):
    before = deepcopy(ranking)
    after = order_exact_ties(ranking)
    assert ranking == before
    assert {r['action']: r for r in after} == {r['action']: r for r in before}
    assert [(r['worst_world_utility'], r['weighted_utility']) for r in after] == [
        (r['worst_world_utility'], r['weighted_utility']) for r in before]
    top = (after[0]['worst_world_utility'], after[0]['weighted_utility'])
    tied = [r for r in after if (r['worst_world_utility'], r['weighted_utility']) == top]
    # Independent scalar-vector oracle; do not use the selector's helper.
    def vector(row):
        return {(i, w['world'], w['weight'], response): sample['leaf_utility']
                for i, w in enumerate(row['worlds'])
                for response, sample in w['sampled_responses'].items()}
    chosen = vector(after[0])
    for alternative in tied:
        values = vector(alternative)
        assert not (values.keys() == chosen.keys()
                    and all(values[k] >= chosen[k] for k in values)
                    and any(values[k] > chosen[k] for k in values))
    return {'before': before[0]['action'], 'after': after[0]['action'],
            'changed': before[0]['action'] != after[0]['action'],
            'top_tied_candidates': len(tied), 'robust_score': top,
            'candidate_evidence_unchanged': True}


def opportunities(position):
    result = []
    for action, labels in position['actions'].items():
        rows = [r for r in position['samples'] if r['action'] == action and r['covered_reply']]
        stages = {}
        for stage, events in [('first_turn', 'root_move_events'), ('second_turn', 'next_move_events')]:
            actors = Counter()
            for row in rows:
                actors.update({e['actor'] for e in row[events]
                               if e['side'] == 'p2' and e['direct_damage_targets']})
            stages[stage] = {'samples': len(rows),
                'terminal_wins': sum(r[stage]['terminal_win'] for r in rows),
                'terminal_losses': sum(r[stage]['terminal_loss'] for r in rows),
                'living_allies_total': sum(len(r[stage]['own_living']) for r in rows),
                'living_opponents_total': sum(len(r[stage]['foe_living']) for r in rows),
                'direct_damage_samples_by_actor': dict(actors)}
        result.append({'action': action, 'roles': labels, 'measurements': stages})
    return {'case': position['case'], 'current_choice': position['selected'],
            'alternatives': result, 'optimal_action_label': 'unproven',
            'native_next_turn_information_groups': len(position['next_turn_native_audit'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['freeze', 'evaluate'])
    parser.add_argument('--manifest', type=Path, default=ROOT/'reviews/decision-quality-manifest-2026-10-15.json')
    parser.add_argument('--output', type=Path, default=ROOT/'reviews/decision-quality-results-2026-10-15.json')
    args = parser.parse_args()
    diagnostic, games = load(DIAGNOSTIC), load(ARCHIVE)
    rows = matrices(games['games'])
    retained = {(p['game'], p['checkpoint']) for p in diagnostic['positions']}
    separate = sorted(set(rows)-retained, key=lambda key: hashlib.sha256(f'{key[0]}:{key[1]}'.encode()).hexdigest())
    paths = [ARCHIVE, DIAGNOSTIC, PROTOCOL, 'scripts/decision_quality_benchmark.py',
             'src/champions_practice/consequence_ties.py', 'src/champions_practice/tactical_consequences.py']
    hashes = {path: digest(path) for path in paths}
    if args.phase == 'freeze':
        assert not args.manifest.exists(), 'Never overwrite a frozen manifest'
        inspections = []
        for game, checkpoint in separate[:12]:
            legal = ' '.join(rows[game, checkpoint]['legal_actions'])
            inspections.append({'game': game, 'checkpoint': checkpoint,
                'turn': rows[game, checkpoint]['turn'],
                'categories': [name for name, tokens in {
                    'move_commands': ('move ',), 'shielding': ('protect',), 'repositioning': ('switch ',),
                    'speed_control': ('trickroom', 'tailwind', 'icywind', 'electroweb')}.items()
                    if any(token in legal for token in tokens)], 'optimal_action_label': 'unproven'})
        args.manifest.write_text(json.dumps({'hashes': hashes, 'retained': sorted(retained),
            'separate_checkpoints': separate, 'inspection_cases': inspections,
            'scope': 'Separate archival checkpoints; not unseen teams or independent strength evidence.'}, indent=2)+'\n')
        print('Frozen:', len(retained), 'retained;', len(separate), 'separate;', len(inspections), 'inspection cases')
        return
    manifest = json.loads(args.manifest.read_text())
    assert hashes == manifest['hashes'], 'Frozen inputs changed'
    development = [{'case': p['case'], **audit(p['control']['ranking'])} for p in diagnostic['positions']]
    changed = [r['case'] for r in development if r['changed']]
    assert changed == ['repeated-protect-loss'], changed
    separate_results = [{'game': game, 'checkpoint': checkpoint,
                         **audit(rows[game, checkpoint]['decision']['tactical']['ranking'])}
                        for game, checkpoint in manifest['separate_checkpoints']]
    result = {'manifest_sha256': hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
              'development': development, 'separate': separate_results,
              'opportunities': [opportunities(p) for p in diagnostic['positions']],
              'strategic_weights_changed': False, 'admission_changed': False,
              'interpretation': 'Sampled tie correctness and continuation diagnostics; no optimal-plan or strength claim.'}
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print('Retained changes:', changed)
    print('Separate changes:', sum(r['changed'] for r in separate_results), '/', len(separate_results))


if __name__ == '__main__':
    main()
