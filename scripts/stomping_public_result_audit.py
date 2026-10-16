"""Read-only native verification of public move-result witnesses on sealed games."""

from collections import Counter
import gzip
import json
from pathlib import Path

from champions_practice.competitive_evaluation import canonical_view
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.public_move_result import public_move_result_plan
from champions_practice.search_worker import ShowdownSearchWorker


ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT/'reviews/mega-opposition-manifest-2026-10-16.json').read_text())
    source = json.loads(gzip.decompress((ROOT/'runs/mega-opposition/v1/games.json.gz').read_bytes()))
    counts, blocked, mismatches = Counter(), [], []
    with ShowdownSearchWorker(ROOT, startup_timeout_seconds=60) as worker:
        for game in source['games']:
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
                for checkpoint, row in enumerate(game['rows']):
                    observed = worker.session_view(session, side=side)['view']
                    assert observed == row['view']
                    public = canonical_view(observed, side)
                    ledger = PublicConstraintLedger.from_public_view(public) if ledger is None else ledger.advance(public)
                    # Classify solely from public data BEFORE reading truth.
                    plan = public_move_result_plan(public, ledger)
                    state = worker.session_snapshot(session)['state']
                    for entry in plan or []:
                        native_side = side if entry['side'] == 'player' else other
                        mon = state['sides'][0 if native_side == 'p1' else 1]['pokemon'][entry['slot']]
                        native = ('undefined' if 'moveLastTurnResult' not in mon else
                                  {True: 'true', False: 'false', None: 'null'}[mon['moveLastTurnResult']])
                        counts[entry['result']] += 1
                        if native != entry['result']:
                            mismatches.append({'game': game['id'], 'checkpoint': checkpoint,
                                'entry': entry, 'native': native, 'events': public['public_event_delta']})
                    trace = row['decision']
                    if trace and trace['reason'] == 'unsupported-persistent:move:stompingtantrum':
                        blocked.append({'game': game['id'], 'checkpoint': checkpoint, 'turn': row['turn'],
                                        'phase': row['phase'], 'public_plan': plan})
                    commands = {side: row['action'], other: row['enemy_action']}
                    worker.choose_session(session, p1_choice=commands['p1'], p2_choice=commands['p2'])
            finally:
                worker.close_session(session)
    report = {'verified_public_classifications': dict(counts), 'mismatches': mismatches,
              'stomping_blocked_decisions': blocked,
              'scope': 'Read-only posthoc native field comparison. Truth never enters public classification or player.'}
    out = ROOT/'runs/stomping-admission/public-result-audit.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2)+'\n')
    print('Classified:', counts, 'mismatches:', len(mismatches), 'blocked:', len(blocked))
    for mismatch in mismatches[:3]:
        print(json.dumps(mismatch))
    assert not mismatches


if __name__ == '__main__':
    main()
