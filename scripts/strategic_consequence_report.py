"""Audit and summarize measured plan consequences without a new utility score."""

from collections import Counter
import gzip
import hashlib
import json
from statistics import mean

from champions_practice.agent_v2 import PublicCatalog
from champions_practice.strategic_diagnostic import diagnose_match
from tactical_consequences_evaluation import ROOT


def main():
    path = ROOT/'runs/v2-plan-consequences/v1/results.json.gz'
    result = json.loads(gzip.decompress(path.read_bytes()))
    for relative, expected in result['source_sha256'].items():
        assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest() == expected, relative
    assert result['rows'] == 384
    report = {'archive_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'protocol': result['protocol'], 'branch_count': result['branch_count'], 'positions': []}
    catalog = PublicCatalog.load(ROOT)
    base = json.loads(gzip.decompress((ROOT/'runs/v2-consequences/one-turn/games.json.gz').read_bytes()))
    report['diagnostic_source_sha256'] = {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in (
        'src/champions_practice/strategic_diagnostic.py', 'scripts/strategic_consequence_report.py',
        'external/pokemon-showdown/data/mods/champions/scripts.ts')}
    for position in result['positions']:
        groups = {}
        for action in position['actions']:
            rows = [r for r in position['rows'] if r['action'] == action]
            assert len(rows) == 24
            keys = {(r['world'], r['reply'], r['sample']) for r in rows}
            assert len(keys) == 24
            if groups:
                assert keys == next(iter(groups.values()))[0]
            groups[action] = (keys, rows)
        summary = {'case': position['case'], 'control_action': position['control_action'], 'actions': []}
        game = next(g for g in base['games'] if g['pair'] == position['case'])
        summary['competing_plans'] = diagnose_match(game['rows'][0]['view'], catalog)['competing_plans']
        for action, (_, rows) in groups.items():
            entry = {'action': action, 'scenarios': len(rows),
                'mean_first_score': mean(r['first_score']['total'] for r in rows),
                'minimum_first_score': min(r['first_score']['total'] for r in rows),
                'mean_own_fainted': mean(r['first_turn']['own_fainted_total'] for r in rows),
                'mean_enemy_fainted': mean(r['first_turn']['enemy_fainted_total'] for r in rows),
                'blocker_mean_hp': {name: mean(r['first_turn']['blockers'][name] for r in rows)
                                   for name in ('Tyranitar', 'Excadrill')},
                'routes': {}, 'turn_two_extra_ko_witnesses': 0,
                'turn_two_no_extra_own_loss_ko_witnesses': 0}
            for route in ('Gardevoir', 'Metagross', 'Armarouge'):
                entry['routes'][route] = {
                    'living_after_first': sum(r['first_turn']['routes'][route]['living'] for r in rows),
                    'active_after_first': sum(r['first_turn']['routes'][route]['active'] for r in rows),
                    'productive_first_attack': sum(r['first_turn']['routes'][route]['productive_surviving_attack'] for r in rows),
                    'first_attack_before_enemy_damage_move': sum(r['first_turn']['routes'][route]['acted_before_enemy_damage_move'] for r in rows),
                    'living_but_no_legal_damage_command_next_turn': sum(
                        r['first_turn']['routes'][route]['living'] and r['route_command_coverage']['all_legal'][route] == 0 for r in rows),
                    'legal_attack_available_but_omitted_by_probe': sum(
                        r['route_command_coverage']['all_legal'][route] > 0 and r['route_command_coverage']['probed'][route] == 0 for r in rows),
                    'next_turn_some_productive_attack': sum(r['opportunities'][route]['witness'] is not None for r in rows),
                    'next_turn_common_productive_action': sum(bool(r['opportunities'][route]['sampled_common_actions']) for r in rows)}
            for row in rows:
                assert len(row['next_actions']) <= 8 and len(row['next_replies']) <= 3
                assert len(row['probes']) == len(row['next_actions'])*len(row['next_replies'])
                for command in row['next_actions']:
                    assert {p['reply'] for p in row['probes'] if p['action'] == command} == set(row['next_replies'])
                extra = [p for p in row['probes'] if p['measurement']['enemy_fainted_total'] > row['first_turn']['enemy_fainted_total']]
                entry['turn_two_extra_ko_witnesses'] += bool(extra)
                entry['turn_two_no_extra_own_loss_ko_witnesses'] += any(
                    p['measurement']['own_fainted_total'] == row['first_turn']['own_fainted_total'] for p in extra)
            summary['actions'].append(entry)
        # Matched structural disagreements are measurements, not proof the evaluator
        # is globally wrong. A dead centerpiece can still be a worthwhile trade.
        control = { (r['world'], r['reply'], r['sample']): r
                    for r in groups[position['control_action']][1] }
        disagreements = []
        for action, (_, rows) in groups.items():
            if action == position['control_action']:
                continue
            for row in rows:
                original = control[row['world'], row['reply'], row['sample']]
                a = original['opportunities']['Gardevoir']
                b = row['opportunities']['Gardevoir']
                if original['first_score']['total'] > row['first_score']['total'] and not a['sampled_common_actions'] and b['sampled_common_actions']:
                    disagreements.append({'action': action, 'world': row['world'], 'reply': row['reply'],
                        'sample': row['sample'], 'score_difference_control_minus_candidate': original['first_score']['total']-row['first_score']['total'],
                        'control_gardevoir_living': original['first_turn']['routes']['Gardevoir']['living'],
                        'control_gardevoir_active': original['first_turn']['routes']['Gardevoir']['active'],
                        'control_metagross_opportunity': bool(original['opportunities']['Metagross']['sampled_common_actions']),
                        'candidate_gardevoir_witness': b['sampled_common_actions'][0]})
        summary['matched_gardevoir_opportunity_disagreements'] = disagreements
        contract = []
        corrected_ranking = []
        for action, (_, rows) in groups.items():
            control_rows = [r for r in rows if r['sample'] == 0]
            corrected = []
            for row in control_rows:
                score = row['first_score']
                room = 'trickroom' in row['first_turn']['field']['pseudoWeather']
                ordered = row['first_turn']['own_active'] + row['first_turn']['enemy_active']
                if room:
                    assert all(m['speed'] <= 0 for m in ordered)
                    own_speed = mean(m['speed'] for m in row['first_turn']['own_active'])
                    enemy_speed = mean(m['speed'] for m in row['first_turn']['enemy_active'])
                    native_ordering_term = max(-20, min(20, (own_speed-enemy_speed)/5))
                    assert abs(native_ordering_term + score['speed']) < 1e-7
                    contract.append({'action': action, 'world': row['world'], 'reply': row['reply'],
                        'legacy_speed': score['speed'], 'native_ordering_term': native_ordering_term,
                        'completion_phases': row['completion_phases']})
                    corrected.append(score['total']-2*score['speed'])
                else:
                    corrected.append(score['total'])
            corrected_ranking.append({'action': action, 'minimum_control_sample_utility': min(corrected)})
        summary['speed_contract_evidence'] = contract
        summary['offline_speed_contract_ranking'] = sorted(corrected_ranking, key=lambda r: r['minimum_control_sample_utility'], reverse=True)
        summary['speed_contract_scope'] = 'Diagnostic correction of double inversion on verified native signed-speed first-RNG frames. Uses this experiment phase-completion policy; frozen V2 replacements can differ from the old search backup. No scorer mutation, new weights, deployed action or full-game validation.'
        summary['replacement_phase_counts'] = dict(Counter(r['completion_phases'] for r in position['rows']))
        report['positions'].append(summary)
    (ROOT/'reviews/v2-plan-consequences-2026-10-15.json').write_text(json.dumps(report, indent=2)+'\n')
    for position in report['positions']:
        print(position['case'], 'matched disagreements', len(position['matched_gardevoir_opportunity_disagreements']))
        for row in position['actions']:
            print(row['action'], 'score', round(row['mean_first_score'], 1),
                'ownKO', round(row['mean_own_fainted'], 2), 'foeKO', round(row['mean_enemy_fainted'], 2),
                'ExcadrillHP', round(row['blocker_mean_hp']['Excadrill'], 2),
                'Gard common', row['routes']['Gardevoir']['next_turn_common_productive_action'],
                'Meta common', row['routes']['Metagross']['next_turn_common_productive_action'],
                'KOwitness', row['turn_two_no_extra_own_loss_ko_witnesses'])


if __name__ == '__main__':
    main()
