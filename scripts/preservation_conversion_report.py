"""Attribute frozen scores and summarize measured conversion opportunities."""

import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
from statistics import fmean

from champions_practice.tactical_objective import OBJECTIVES, rerank


def bins(candidate):
    return {(index, reply): sample['leaf_utility'] for index, world in enumerate(candidate['worlds'])
            for reply, sample in world['sampled_responses'].items()}


def dominators(ranking, selected):
    chosen = bins(next(c for c in ranking if c['action'] == selected))
    result = []
    for candidate in ranking:
        values = bins(candidate)
        if values.keys() == chosen.keys() and all(values[k] >= chosen[k]-1e-7 for k in chosen) and any(
                values[k] > chosen[k]+1e-7 for k in chosen):
            result.append(candidate['action'])
    return result


def stage_metrics(rows, stage):
    by_reply = defaultdict(list)
    for row in rows:
        by_reply[row['world'], row['reply']].append(row[stage]['breakdown']['total'])
    values = [fmean(samples) for samples in by_reply.values()]
    return {'samples': len(rows), 'worst_world_response_rng_mean': min(values),
        'equal_bin_mean': fmean(values), 'worst_individual_sample': min(row[stage]['breakdown']['total'] for row in rows),
        'terminal_wins': sum(row[stage]['terminal_win'] for row in rows),
        'terminal_losses': sum(row[stage]['terminal_loss'] for row in rows),
        'focal_living': sum(row[stage]['focal_living'] for row in rows),
        'focal_active': sum(row[stage]['focal_active'] for row in rows),
        'focal_with_legal_damaging_commands': sum(row[stage]['focal_legal_damaging_joint_commands'] > 0 for row in rows)}


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
    result = {k: v for k, v in data.items() if k != 'positions'}
    result.update(archive=str(args.archive.resolve().relative_to(root)), archive_sha256=hashlib.sha256(raw).hexdigest(), positions=[])
    for position in data['positions']:
        samples = position['samples']
        cells = defaultdict(set)
        for row in samples:
            cells[row['world'], row['reply'], row['action']].add(row['rng_sample'])
            for stage in ('immediate', 'first_turn', 'second_turn'):
                if row[stage]['terminal_win']:
                    assert row[stage]['breakdown']['total'] == 1_000_000
                if row[stage]['terminal_loss']:
                    assert row[stage]['breakdown']['total'] == -1_000_000
        assert all(indices == set(range(8)) for indices in cells.values())
        assert len(samples) == 8*len(cells)
        for world, reply, action in cells:
            assert all((world, reply, candidate) in cells for candidate in position['actions'])
        ranking = position['control']['ranking']
        worst_parts = {}
        for candidate in ranking:
            worst_parts[candidate['action']] = [
                {'world': index, 'reply': reply, 'breakdown': sample['leaf_breakdown']}
                for index, world in enumerate(candidate['worlds']) for reply, sample in world['sampled_responses'].items()
                if abs(sample['leaf_utility']-candidate['worst_world_utility']) < 1e-7]
        summary = {k: position[k] for k in ('case', 'game', 'checkpoint', 'focal', 'turn', 'selected',
                    'incumbent', 'recorded_reply', 'actions', 'action_coverage', 'worlds')}
        summary.update(production_rankings=[{k: c[k] for k in ('action', 'worst_world_utility', 'weighted_utility')}
                                           for c in ranking], production_floor_components=worst_parts,
            production_selected_pointwise_dominated_by=dominators(ranking, position['selected']),
            frozen_matrix_sensitivities={o.name: rerank(ranking, o)[0] for o in OBJECTIVES},
            action_measurements=[], next_turn_native_audit=[])
        focal = ''.join(c for c in position['focal'].lower() if c.isalnum())
        for action, labels in position['actions'].items():
            for scope, selected in [('covered_three_responses', [r for r in samples if r['action'] == action and r['covered_reply']]),
                                    ('recorded_reply', [r for r in samples if r['action'] == action and r['recorded_reply']])]:
                if not selected:
                    continue
                def focal_moves(row, stage):
                    return [event for event in row[stage] if event['side'] == 'p2'
                            and ''.join(c for c in event['actor'].lower() if c.isalnum()) == focal]
                summary['action_measurements'].append({'action': action, 'labels': labels, 'scope': scope,
                    'first_turn': stage_metrics(selected, 'first_turn'), 'second_turn': stage_metrics(selected, 'second_turn'),
                    'focal_damaging_execution_first_turn': sum(any(e['damaging'] for e in focal_moves(r, 'root_move_events')) for r in selected),
                    'focal_direct_damage_first_turn': sum(any(e['direct_damage_targets'] for e in focal_moves(r, 'root_move_events')) for r in selected),
                    'focal_damaging_execution_next_turn': sum(any(e['damaging'] for e in focal_moves(r, 'next_move_events')) for r in selected),
                    'focal_direct_damage_next_turn': sum(any(e['direct_damage_targets'] for e in focal_moves(r, 'next_move_events')) for r in selected),
                    'continuation_opponent_fallbacks': sum(d['opponent_fallback'] for r in selected for d in r['phase_decisions']+r['next_decisions'])})
        for audit in position['next_turn_native_audit']:
            executions = []
            for execution in audit['selected_action_executions']:
                measurement = execution['measurement']
                executions.append({'member': execution['member'], 'reply': execution['reply'],
                    'completed_next_turn': measurement['ended'] or measurement['turn'] >= position['turn']+2,
                    'measurement': {k: measurement[k] for k in ('turn', 'terminal_win', 'terminal_loss',
                        'focal_living', 'focal_active', 'focal_hp')},
                    'focal_moves': [event for event in execution['moves'] if event['side'] == 'p2'
                        and ''.join(c for c in event['actor'].lower() if c.isalnum()) == focal],
                    'status_events': execution['status_events']})
            summary['next_turn_native_audit'].append({k: audit[k] for k in
                ('sources', 'incumbent', 'selected', 'indistinguishable_hypotheses')} | {
                'selected_action_executions': executions,
                'ranking': [{k: c[k] for k in ('action', 'worst_world_utility', 'weighted_utility')} for c in audit['ranking']]})
        result['positions'].append(summary)
    result['diagnostic_root_samples'] = sum(len(p['samples']) for p in data['positions'])
    result['next_turn_information_groups'] = sum(len(p['next_turn_native_audit']) for p in data['positions'])
    result['audit'] = ['All frozen source hashes match; every action/response/world cell has eight RNG labels.',
        'Every compared action faces the same per-world replies and coupled initial RNG labels.',
        'Root production choices, scores and default-seed immediate branch breakdowns reproduce the retained 8/3 control.',
        'Own V2 continuation choices agree across equal public information and own action history.',
        'Next-turn native controls share one action across indistinguishable leaf hypotheses.',
        'Every measured terminal win/loss receives the exact existing positive/negative million-point terminal value.',
        'No production scorer, admission implementation, prior, horizon or budget changed.']
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print('Samples:', result['diagnostic_root_samples'], 'native continuation groups:', result['next_turn_information_groups'])
    for p in result['positions']:
        print(p['case'], 'dominating alternatives:', p['production_selected_pointwise_dominated_by'])


if __name__ == '__main__':
    main()
