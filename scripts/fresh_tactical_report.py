"""Audit coupled tactical samples and report counterexamples without new weights."""

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
from statistics import fmean


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.archive.read_bytes()
    data = json.loads(gzip.decompress(raw))
    manifest = json.loads(args.manifest.read_text())
    assert hashlib.sha256(args.manifest.read_bytes()).hexdigest() == data['report']['manifest_sha256']
    assert len(data['report']['cases']) == len(manifest['cases']) == 12
    root = Path(__file__).resolve().parents[1]
    for path, digest in manifest['source_sha256'].items():
        assert hashlib.sha256((root/path).read_bytes()).hexdigest() == digest, path
    reports = {c['id']: c for c in data['report']['cases']}
    assert set(reports) == {c['id'] for c in manifest['cases']}
    output = {'archive_sha256': hashlib.sha256(raw).hexdigest(),
              'manifest_sha256': data['report']['manifest_sha256'], 'cases': []}
    for case in data['raw']:
        summary = reports[case['case']]
        assert summary['status'] == 'complete'
        samples = case['measurements']
        actions = {m['action'] for m in samples}
        coverage = Counter((m['action'], m['reply'], m['rng']) for m in samples)
        expected = {(action, reply, roll) for action in actions for reply in summary['replies']
                    for roll in range(len(manifest['protocol']['rng']))}
        assert set(coverage) == expected and set(coverage.values()) == {1}
        for sample in samples:
            for stage in ('first', 'second'):
                fact = sample[stage]
                assert not (fact['terminal_win'] and fact['terminal_loss'])
                if fact['terminal_win']:
                    assert fact['utility']['terminal'] == fact['utility']['total'] == 1_000_000
                if fact['terminal_loss']:
                    assert fact['utility']['terminal'] == fact['utility']['total'] == -1_000_000
        assert all(m['reply_in_search'] == (m['reply'] in {
            reply for w in case['ranking'][0]['worlds'] for reply in w['sampled_responses']}) for m in samples)
        selected = {(m['reply'], m['rng']): m for m in samples if m['action'] == summary['selected']}
        ranked = {r['action']: r for r in case['ranking']}
        def score_parity(action):
            if action not in ranked:
                return None
            controls = ranked[action]['worlds'][0]['sampled_responses']
            return all(next(m for m in samples if m['action'] == action and m['reply'] == reply and m['rng'] == 0)[
                'first']['utility']['total'] == fact['leaf_utility'] for reply, fact in controls.items())
        witnesses = []
        for action in sorted(actions):
            if action == summary['selected']:
                continue
            alternate = {(m['reply'], m['rng']): m for m in samples if m['action'] == action}
            for stage in ('first', 'second'):
                # Conditional conversion evidence: compare terminal facts for
                # each coupled scenario, never turn the totals into probabilities.
                no_fewer_wins = all(alternate[k][stage]['terminal_win'] >= selected[k][stage]['terminal_win'] for k in selected)
                no_more_losses = all(alternate[k][stage]['terminal_loss'] <= selected[k][stage]['terminal_loss'] for k in selected)
                extra_wins = sum(alternate[k][stage]['terminal_win'] and not selected[k][stage]['terminal_win'] for k in selected)
                avoided_losses = sum(selected[k][stage]['terminal_loss'] and not alternate[k][stage]['terminal_loss'] for k in selected)
                if no_fewer_wins and no_more_losses and (extra_wins or avoided_losses):
                    witnesses.append({'action': action, 'stage': stage, 'extra_terminal_wins': extra_wins,
                        'avoided_terminal_losses': avoided_losses,
                        'inside_search_candidates': action in {r['action'] for r in case['ranking']},
                        'native_control_score_parity_selected_and_alternative': bool(score_parity(action) and score_parity(summary['selected'])),
                        'extra_wins_original_responses_default_rng': sum(
                            alternate[k][stage]['terminal_win'] and not selected[k][stage]['terminal_win']
                            for k in selected if selected[k]['reply_in_search'] and k[1] == 0),
                        'lost_wins_original_responses_default_rng': sum(
                            selected[k][stage]['terminal_win'] and not alternate[k][stage]['terminal_win']
                            for k in selected if selected[k]['reply_in_search'] and k[1] == 0),
                        'avoided_losses_original_responses_default_rng': sum(
                            selected[k][stage]['terminal_loss'] and not alternate[k][stage]['terminal_loss']
                            for k in selected if selected[k]['reply_in_search'] and k[1] == 0),
                        'first_turn_fewer_surviving_allies_than_selected': sum(
                            len(alternate[k]['first']['own_living']) < len(selected[k]['first']['own_living']) for k in selected),
                        'first_turn_fewer_surviving_enemies_than_selected': sum(
                            len(alternate[k]['first']['enemy_living']) < len(selected[k]['first']['enemy_living']) for k in selected),
                        'extra_win_scenarios': [{'reply': k[0], 'rng': k[1]} for k in selected
                            if alternate[k][stage]['terminal_win'] and not selected[k][stage]['terminal_win']],
                        'avoided_loss_scenarios': [{'reply': k[0], 'rng': k[1]} for k in selected
                            if selected[k][stage]['terminal_loss'] and not alternate[k][stage]['terminal_loss']],
                        'interpretation': 'Scenario-wise terminal improvement under these continuations; nonterminal routes remain unresolved.'})
        rng_ranking = []
        for action in actions:
            replies = defaultdict(list)
            for m in samples:
                if m['action'] == action:
                    replies[m['reply']].append(m['first']['utility']['total'])
            rng_ranking.append({'action': action, 'worst_response_rng_mean': min(fmean(v) for v in replies.values())})
        rng_ranking.sort(key=lambda row: (-row['worst_response_rng_mean'], row['action']))
        output['cases'].append({'id': case['case'], 'selected': summary['selected'],
            'incumbent': summary['incumbent'], 'samples': len(samples),
            'terminal_improvement_witnesses': witnesses,
            'expanded_response_rng_utility_ranking': rng_ranking,
            'continuation_limitation': 'Frozen V2 follow-up can miss a stronger available tactical continuation.'})
    assert len(data['raw']) == sum(c['status'] == 'complete' for c in reports.values())
    output['summary'] = {'cases': len(reports), 'audited_actionable': len(data['raw']),
        'samples': sum(len(c['measurements']) for c in data['raw']),
        'cases_with_first_turn_terminal_witness': sum(any(w['stage'] == 'first' for w in c['terminal_improvement_witnesses']) for c in output['cases']),
        'cases_with_second_turn_terminal_witness': sum(any(w['stage'] == 'second' for w in c['terminal_improvement_witnesses']) for c in output['cases']),
        'control_cells_reproduced': sum(c.get('direct_completed_control_cells_reproduced', 0) for c in reports.values()),
        'passed': 'Manifest hashes, identities, complete coupled scenario grid and native control-cell reproduction.'}
    args.output.write_text(json.dumps(output, indent=2)+'\n')
    print(json.dumps(output['summary']))


if __name__ == '__main__':
    main()
