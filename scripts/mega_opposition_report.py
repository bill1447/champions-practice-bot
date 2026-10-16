"""Audit the sealed fresh suite and inspect its two discordant game pairs."""

from collections import Counter
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.exact_search import score_exact_summary_breakdown
from champions_practice.search_worker import ShowdownSearchWorker
from mega_opposition_evaluation import summarize


ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    archive = ROOT/'runs/mega-opposition/v1/games.json.gz'
    manifest_path = ROOT/'reviews/mega-opposition-manifest-2026-10-16.json'
    frozen = json.loads(manifest_path.read_text())
    data = json.loads(gzip.decompress(archive.read_bytes()))
    assert len(data['games']) == len(frozen['cases']) == 48
    assert all(sha(ROOT/p) == h for p, h in frozen['source_sha256'].items())
    for case, game in zip(frozen['cases'], data['games'], strict=True):
        assert all(game[k] == value for k, value in case.items())
        assert game['status'] == 'complete'
        for row in game['rows']:
            assert row['action'] in row['legal_actions']
            trace = row['decision']
            if trace and trace['status'] == 'fallback':
                assert row['action'] == trace['incumbent']
    report = {'manifest_sha256': sha(manifest_path), 'archive_sha256': sha(archive),
              'summary': summarize(data['games']), 'witnesses': [], 'audit': {}}
    report['audit']['opponent_fallback_reasons'] = dict(Counter(
        r['enemy_trace']['fallback_reason'] for g in data['games'] for r in g['rows']
        if r['enemy_trace']['fallback']))
    discordant = {f['pair'] for f in report['summary']['forensics'] if f['native_win'] != f['v2_win']}
    replayed = 0
    with ShowdownSearchWorker(ROOT, startup_timeout_seconds=60) as worker:
        for game in data['games']:
            side = game['side']
            other = 'p2' if side == 'p1' else 'p1'
            own, enemy = (frozen['teams'][game[k]] for k in ('own_team', 'enemy_team'))
            if game['hidden_family'] == 'heldout':
                enemy = enemy.replace('Protect', 'Substitute').replace('Life Orb', 'Sitrus Berry')
            session = worker.start_session(battle_format=CHAMPIONS_FORMAT,
                p1_team=own if side == 'p1' else enemy, p2_team=enemy if side == 'p1' else own,
                p1_name='P1', p2_name='P2', seed=game['battle_seed'])['session_id']
            try:
                commands = {side: 'team 1234', other: 'team 1256' if game['hidden_family'] == 'heldout' else 'team 1234'}
                worker.choose_session(session, p1_choice=commands['p1'], p2_choice=commands['p2'])
                for index, row in enumerate(game['rows']):
                    assert worker.session_view(session, side=side)['view'] == row['view']
                    if game['version'] == 'native' and game['pair'] in discordant and row['decision']['disagreement']:
                        # Driver truth is available only AFTER every player decision is sealed.
                        state = worker.session_snapshot(session)['state']
                        witness = {'pair': game['pair'], 'checkpoint': index, 'turn': row['turn'],
                            'recorded_opposing_reply': row['enemy_action'], 'actions': {}}
                        for role, action in (('incumbent', row['decision']['incumbent']), ('native', row['action'])):
                            commands = {side: action, other: row['enemy_action']}
                            branches = [{'p1_choice': commands['p1'], 'p2_choice': commands['p2']}]
                            branches.extend({**branches[0], 'rng_seed': 'sodium,'+hashlib.sha256(
                                f'mega-posthoc-coupled:{i}'.encode()).hexdigest()} for i in range(4))
                            outcomes = worker.branch_many(state=state, branches=branches)
                            witness['actions'][role] = {'action': action, 'outcomes': [{
                                'rng': 'recorded-stream' if i == 0 else f'coupled-{i-1}',
                                'turn': o['summary']['turn'], 'ended': o['summary']['ended'],
                                'winner': o['summary']['winner'],
                                'own_living': [m['species'] for m in o['summary'][side]['pokemon'] if m['hp'] > 0],
                                'enemy_living': [m['species'] for m in o['summary'][other]['pokemon'] if m['hp'] > 0],
                                'utility': asdict(score_exact_summary_breakdown(o['summary'], side))}
                                for i, o in enumerate(outcomes)]}
                        report['witnesses'].append(witness)
                    commands = {side: row['action'], other: row['enemy_action']}
                    worker.choose_session(session, p1_choice=commands['p1'], p2_choice=commands['p2'])
                end = worker.session_view(session, side=side)['view']
                assert end['ended'] and end['winner'] == game['winner']
                replayed += 1
            finally:
                worker.close_session(session)
    report['audit']['exactly_replayed_complete_games'] = replayed
    report['witness_scope'] = ('Posthoc actual-state one-resolution branches against recorded reply, recorded RNG stream plus four coupled labels. '
        'No continuation or counterplay coverage: nonterminal utility differences are not decision-quality verdicts.')
    output = ROOT/'reviews/mega-opposition-results-2026-10-16.json'
    output.write_text(json.dumps(report, indent=2)+'\n')
    print('Audited games:', replayed, 'conditional witnesses:', len(report['witnesses']))


if __name__ == '__main__':
    main()
