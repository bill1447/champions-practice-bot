"""Posthoc conditional terminal checks of newly usable, already sealed decisions."""

from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import ShowdownSearchWorker


ROOT = Path(__file__).resolve().parents[1]


def main():
    before = json.loads(gzip.decompress((ROOT/'runs/mega-opposition/v1/games.json.gz').read_bytes()))
    replay = json.loads(gzip.decompress((ROOT/'runs/stomping-admission/replay-v1/results.json.gz').read_bytes()))
    manifest = json.loads((ROOT/'reviews/mega-opposition-manifest-2026-10-16.json').read_text())
    selected = {(r['game'], r['checkpoint']): r for r in replay['shadow'] if r['status'] == 'search'}
    assert len(selected) == 46
    witnesses = []
    with ShowdownSearchWorker(ROOT, startup_timeout_seconds=60) as worker:
        for game in before['games']:
            if game['version'] != 'native':
                continue
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
                for checkpoint, row in enumerate(game['rows']):
                    assert worker.session_view(session, side=side)['view'] == row['view']
                    rescued = selected.get((game['id'], checkpoint))
                    if rescued:
                        # Only the forensic driver reads truth; public decisions
                        # were sealed by the separate shadow evaluation first.
                        state = worker.session_snapshot(session)['state']
                        witness = {k: rescued[k] for k in ('game', 'checkpoint', 'turn', 'public_contexts', 'disagreement')}
                        witness['recorded_opposing_reply'] = row['enemy_action']
                        witness['actions'] = {}
                        for role, action in (('incumbent', rescued['incumbent']), ('native', rescued['action'])):
                            commands = {side: action, other: row['enemy_action']}
                            branch = {'p1_choice': commands['p1'], 'p2_choice': commands['p2']}
                            branches = [branch, *({**branch, 'rng_seed': 'sodium,'+hashlib.sha256(
                                f'stomping-conditional-terminal:{i}'.encode()).hexdigest()} for i in range(4))]
                            results = worker.branch_many(state=state, branches=branches)
                            witness['actions'][role] = {'action': action, 'outcomes': [{
                                'rng': 'recorded-stream' if i == 0 else f'coupled-{i-1}',
                                'turn': r['summary']['turn'],
                                'terminal_win': r['summary']['ended'] and r['summary']['winner'] == r['summary'][side]['name'],
                                'terminal_loss': r['summary']['ended'] and r['summary']['winner'] == r['summary'][other]['name'],
                                'terminal_draw': r['summary']['ended'] and not r['summary']['winner'],
                                'own_living': [m['species'] for m in r['summary'][side]['pokemon'] if m['hp'] > 0],
                                'enemy_living': [m['species'] for m in r['summary'][other]['pokemon'] if m['hp'] > 0]}
                                for i, r in enumerate(results)]}
                        witnesses.append(witness)
                    commands = {side: row['action'], other: row['enemy_action']}
                    worker.choose_session(session, p1_choice=commands['p1'], p2_choice=commands['p2'])
                assert worker.session_view(session, side=side)['view']['winner'] == game['winner']
            finally:
                worker.close_session(session)
    assert len(witnesses) == 46
    cells = Counter()
    informative = []
    for witness in witnesses:
        differences = Counter()
        for old, new in zip(witness['actions']['incumbent']['outcomes'], witness['actions']['native']['outcomes'], strict=True):
            differences['prevented_terminal_loss'] += old['terminal_loss'] and not new['terminal_loss']
            differences['introduced_terminal_loss'] += new['terminal_loss'] and not old['terminal_loss']
            differences['added_terminal_win'] += new['terminal_win'] and not old['terminal_win']
            differences['removed_terminal_win'] += old['terminal_win'] and not new['terminal_win']
        cells.update(differences)
        if any(differences.values()):
            informative.append({**{k: v for k, v in witness.items() if k != 'actions'}, 'differences': dict(differences)})
    report = {'positions': len(witnesses), 'coupled_cells': len(witnesses)*5,
        'different_actions': sum(w['disagreement'] for w in witnesses),
        'terminal_differences': dict(cells), 'informative_positions': informative, 'witnesses': witnesses,
        'scope': 'Posthoc actual-state single-resolution consequences against the recorded reply, not a counterplay-complete quality label. '
                 'Recorded stream plus four coupled labels, not probabilities. Surviving is not a winning continuation. '
                 'Only originally blocked positions now completing native search are included; all 46, irrespective of terminal results.'}
    out = ROOT/'runs/stomping-admission/rescue-forensics.json'
    out.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'witnesses'}, indent=2))


if __name__ == '__main__':
    main()
