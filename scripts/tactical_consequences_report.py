"""Provenance, paired controls, native sealed witnesses and default isolation."""

from collections import Counter, defaultdict
import gzip
import hashlib
import json
import subprocess
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog, observe
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.exact_search import score_exact_summary_breakdown
from champions_practice.independent_opponent import identity, load_dex
from champions_practice.search_worker import ShowdownSearchWorker
from tactical_consequences_evaluation import ROOT, blueprints, frozen_policy


def load(directory, ref=None):
    path = ROOT/f'runs/v2-consequences/{directory}'
    raw = (path/'games.json.gz').read_bytes()
    report = json.loads(gzip.decompress(raw))
    manifest = json.loads((path/'manifest.json').read_text())
    assert manifest['games'] == []
    assert all(report[k] == v for k, v in manifest.items() if k != 'games')
    for name, digest in manifest['source_sha256'].items():
        current = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        if current != digest:
            assert ref is not None, name
            source = subprocess.run(['git', 'show', ref+':'+name], cwd=ROOT,
                                    check=True, capture_output=True).stdout
            assert hashlib.sha256(source).hexdigest() == digest, name
    cases = {c['id']: c for c in report['cases']}
    assert len(cases) == len(report['cases']) == len(report['games'])
    assert {g['id'] for g in report['games']} == set(cases)
    for game in report['games']:
        assert game['status'] == 'complete'
        assert all(game[k] == v for k, v in cases[game['id']].items())
        for row in game['rows']:
            assert row['action'] in row['legal_actions']
            if row['tactical'] is None:
                assert row['action'] == row['baseline']
            elif row['tactical']['status'] != 'complete':
                assert row['action'] == row['baseline']
    return report, {'archive_sha256': hashlib.sha256(raw).hexdigest(),
                    'manifest_sha256': hashlib.sha256((path/'manifest.json').read_bytes()).hexdigest(),
                    'source_commit': ref, 'source_sha256': manifest['source_sha256']}


def native_witnesses(worker, groups, texts):
    result = []
    for pair in ('development-0-0-p1', 'development-1-0-p1', 'validation-0-0-p1',
                 'validation-1-1-p2', 'validation-2-0-p1'):
        games = groups[pair]
        game = games['consequences']
        side, variant = game['side'], game['truth_variant']
        other = 'p2' if side == 'p1' else 'p1'
        own, enemy = texts[game['own_team']], texts[game['enemy_team']]
        if variant:
            enemy = enemy.replace('Life Orb', 'Sitrus Berry')
        session = worker.start_session(battle_format=CHAMPIONS_FORMAT,
            p1_team=own if side == 'p1' else enemy, p2_team=enemy if side == 'p1' else own,
            p1_name='P1', p2_name='P2', seed=game['battle_seed'])['session_id']
        try:
            selection = {side: 'team 1234', other: 'team 1256' if variant else 'team 1234'}
            worker.choose_session(session, p1_choice=selection['p1'], p2_choice=selection['p2'])
            row = game['rows'][0]
            assert worker.session_view(session, side=side)['view'] == row['view']
            # All decisions are already sealed in the completed archives.
            # This native truth is used ONLY for conditional diagnostic checks.
            state = worker.session_snapshot(session)['state']
            witness = {'pair': pair, 'fixed_enemy_response': row['enemy_action'], 'plans': {}}
            for version in ('incumbent', 'one_turn', 'consequences'):
                action = games[version]['rows'][0]['action']
                assert action in row['legal_actions']
                branches = []
                for sample in range(8):
                    commands = {side: action, other: row['enemy_action']}
                    branches.append({'p1_choice': commands['p1'], 'p2_choice': commands['p2'],
                        'rng_seed': 'sodium,'+hashlib.sha256(f'consequence-witness:{sample}'.encode()).hexdigest()})
                outcomes = worker.branch_many(state=state, branches=branches)
                samples = []
                for branch in outcomes:
                    summary = branch['summary']
                    samples.append({'own_survivors': sum(m['hp'] > 0 for m in summary[side]['pokemon']),
                        'foe_survivors': sum(m['hp'] > 0 for m in summary[other]['pokemon']),
                        'utility': score_exact_summary_breakdown(summary, side).total})
                witness['plans'][version] = {'action': action, 'samples': samples}
            result.append(witness)
        finally:
            worker.close_session(session)
    return result


def main():
    initial, initial_identity = load('v1', '4508130')
    final, final_identity = load('v2', 'd4e65b6')
    control, control_identity = load('one-turn')
    assert control['opponent_identity'] == identity(load_dex(ROOT))
    assert control['two_turn_archive_sha256'] == final_identity['archive_sha256']
    texts, _ = blueprints()
    assert final['team_sha256'] == {k: hashlib.sha256(v.encode()).hexdigest() for k, v in texts.items()}
    groups = defaultdict(dict)
    for game in final['games']+control['games']:
        assert game['version'] not in groups[game['pair']]
        groups[game['pair']][game['version']] = game
    for games in groups.values():
        assert set(games) == {'incumbent', 'one_turn', 'consequences'}
        base = games['incumbent']
        for game in games.values():
            assert all(game[k] == base[k] for k in ('side', 'battle_seed', 'opponent_seed', 'truth_variant', 'own_team', 'enemy_team'))
            assert game['rows'][0]['view'] == base['rows'][0]['view']
            assert game['rows'][0]['enemy_action'] == base['rows'][0]['enemy_action']
        mirror = base['mirror_group']+('-p2' if base['side'] == 'p1' else '-p1')
        assert mirror in groups
    comparison = {}
    for left, right in [('incumbent', 'one_turn'), ('incumbent', 'consequences'), ('one_turn', 'consequences')]:
        comparison[left+':'+right] = {'left_wins': sum(p[left]['win'] for p in groups.values()),
            'right_wins': sum(p[right]['win'] for p in groups.values()),
            'left_only': sum(p[left]['win'] and not p[right]['win'] for p in groups.values()),
            'right_only': sum(p[right]['win'] and not p[left]['win'] for p in groups.values())}
    policy, _ = frozen_policy('e0ae723')
    catalog = PublicCatalog.load(ROOT)
    default_checked = 0
    coverage, choices, times = Counter(), Counter(), defaultdict(list)
    for game in final['games']+control['games']:
        for row in game['rows']:
            d = policy(observe(row['view'], row['legal_actions'], deadline=perf_counter()+8), catalog)
            assert d.action == row['baseline']
            default_checked += 1
        trace = game['rows'][0]['tactical']
        if trace and trace['status'] == 'complete':
            times[game['version']].append(trace['elapsed_seconds'])
            choices[game['version']+':'+game['rows'][0]['action']] += 1
            selected = trace['ranking'][0]
            replies = [set(w['sampled_responses']) for w in selected['worlds']]
            coverage[game['version']+':actual_reply_in_every_world'] += all(game['rows'][0]['enemy_action'] in r for r in replies)
            assert trace['branch_count'] <= 4096 and trace['elapsed_seconds'] < 8
    with ShowdownSearchWorker(ROOT, startup_timeout_seconds=60) as worker:
        witnesses = native_witnesses(worker, groups, texts)
    report = {'disposition': 'experimental; no default promotion',
        'runs': {'initial': initial_identity, 'two_turn': final_identity, 'one_turn': control_identity},
        'initial_summary': initial['summary'], 'two_turn_summary': final['summary'], 'one_turn_summary': control['summary'],
        'paired_comparisons': comparison, 'default_decisions_replayed': default_checked,
        'opponent_enum_repair_decisions_unchanged': control['opponent_replayed_unchanged'],
        'actual_response_coverage': dict(coverage),
        'opening_choices': dict(choices),
        'search_timing': {k: {'mean_seconds': sum(v)/len(v), 'max_seconds': max(v)} for k, v in times.items()},
        'native_witness_scope': 'Actual sealed state, fixed recorded enemy reply, eight coupled futures; first-decision diagnostics only, not win probabilities.',
        'native_witnesses': witnesses,
        'limitations': final['limitations']+['v1/v2 replay the same cases after coverage repairs and are not independent evidence.',
            'One-turn and two-turn controls use the same candidates, response limits, hypotheses and position scorer.',
            'Native position scorer remains a hand-written material/HP/status/boost/field/speed utility, not a learned winning-position model.']}
    (ROOT/'reviews/v2-consequences-2026-10-15.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: report[k] for k in ('paired_comparisons', 'actual_response_coverage', 'search_timing', 'default_decisions_replayed')}, indent=2))


if __name__ == '__main__':
    main()
