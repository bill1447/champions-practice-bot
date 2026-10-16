"""Audit the completed Stomping regression and retain compact evidence."""

from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

from champions_practice.competitive_evaluation import canonical_view
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.public_move_result import public_move_result_plan
from champions_practice.search_worker import ShowdownSearchWorker


ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest_path = ROOT/'reviews/stomping-replay-manifest-2026-10-16.json'
    archive_path = ROOT/'runs/stomping-admission/replay-v1/results.json.gz'
    manifest = json.loads(manifest_path.read_text())
    data = json.loads(gzip.decompress(archive_path.read_bytes()))
    assert sha(manifest_path) == data['manifest_sha256']
    assert all(sha(ROOT/p) == h for p, h in manifest['source_sha256'].items())
    assert len(data['games']) == len(manifest['cases']) == 48
    counts, completed = Counter(), 0
    with ShowdownSearchWorker(ROOT, startup_timeout_seconds=60) as worker:
        for case, game in zip(manifest['cases'], data['games'], strict=True):
            assert all(game[k] == v for k, v in case.items())
            side, other = game['side'], 'p2' if game['side'] == 'p1' else 'p1'
            own, enemy = (manifest['teams'][game[k]] for k in ('own_team', 'enemy_team'))
            if game['hidden_family'] == 'heldout':
                enemy = enemy.replace('Protect', 'Substitute').replace('Life Orb', 'Sitrus Berry')
            session = worker.start_session(battle_format=CHAMPIONS_FORMAT,
                p1_team=own if side == 'p1' else enemy, p2_team=enemy if side == 'p1' else own,
                p1_name='P1', p2_name='P2', seed=game['battle_seed'])['session_id']
            try:
                commands = {side: 'team 1234', other: 'team 1256' if game['hidden_family'] == 'heldout' else 'team 1234'}
                worker.choose_session(session, p1_choice=commands['p1'], p2_choice=commands['p2'])
                ledger = None
                for row in game['rows']:
                    assert worker.session_view(session, side=side)['view'] == row['view']
                    assert row['action'] in row['legal_actions']
                    public = canonical_view(row['view'], side)
                    ledger = PublicConstraintLedger.from_public_view(public) if ledger is None else ledger.advance(public)
                    plan = public_move_result_plan(public, ledger)
                    state = worker.session_snapshot(session)['state']
                    for entry in plan or []:
                        native_side = side if entry['side'] == 'player' else other
                        mon = state['sides'][0 if native_side == 'p1' else 1]['pokemon'][entry['slot']]
                        actual = 'undefined' if 'moveLastTurnResult' not in mon else json.dumps(mon['moveLastTurnResult'])
                        assert actual == entry['result'], (game['id'], row['turn'], entry, actual)
                        counts[actual] += 1
                    if row['decision'] and row['decision']['status'] == 'fallback':
                        assert row['action'] == row['decision']['incumbent']
                    commands = {side: row['action'], other: row['enemy_action']}
                    worker.choose_session(session, p1_choice=commands['p1'], p2_choice=commands['p2'])
                end = worker.session_view(session, side=side)['view']
                assert end['ended'] and end['winner'] == game['winner']
                completed += 1
            finally:
                worker.close_session(session)
    report = data['compact']
    old = {g['id']: g for g in json.loads(gzip.decompress(
        (ROOT/'runs/mega-opposition/v1/games.json.gz').read_bytes()))['games']}
    report['changed_outcome_first_divergences'] = []
    for game in data['games']:
        control = old[game['id']]
        if game['version'] != 'native' or game['win'] == control['win']:
            continue
        for checkpoint, (before, after) in enumerate(zip(control['rows'], game['rows'])):
            if (before['action'], before['enemy_action']) == (after['action'], after['enemy_action']):
                continue
            assert before['view'] == after['view'] and before['enemy_action'] == after['enemy_action']
            assert before['decision']['reason'] == 'unsupported-persistent:move:stompingtantrum'
            assert after['decision']['status'] == 'search'
            report['changed_outcome_first_divergences'].append({'game': game['id'], 'old_win': control['win'],
                'new_win': game['win'], 'checkpoint': checkpoint, 'turn': after['turn'],
                'original_action': before['action'], 'repaired_action': after['action'],
                'matched_opposing_reply': after['enemy_action'], 'same_public_position': True,
                'original_reason': before['decision']['reason']})
            break
    assert len(report['changed_outcome_first_divergences']) == 7
    report['audit'] = {'exactly_replayed_complete_games': completed, 'native_public_result_checks': dict(counts),
        'native_public_result_mismatches': 0, 'archive_sha256': sha(archive_path),
        'same_position_max_seconds': max(r['seconds'] for r in data['shadow']),
        'same_position_over_eight_seconds': sum(r['seconds'] > 8 for r in data['shadow'])}
    forensic_path = ROOT/'runs/stomping-admission/rescue-forensics.json'
    report['rescue_forensics'] = json.loads(forensic_path.read_text())
    report['rescue_forensics_sha256'] = sha(forensic_path)
    report['control_public_result_audit'] = {k: v for k, v in json.loads(
        (ROOT/'runs/stomping-admission/public-result-audit.json').read_text()).items() if k != 'stomping_blocked_decisions'}
    output = ROOT/'reviews/stomping-replay-results-2026-10-16.json'
    output.write_text(json.dumps(report, indent=2)+'\n')
    print('Audited:', completed, 'games;', sum(counts.values()), 'native public-result fields, zero mismatches')


if __name__ == '__main__':
    main()
