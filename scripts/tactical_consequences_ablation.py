"""Same candidates/worlds/scorer, one resolved turn; audit opponent field repair."""

from collections import Counter
import gzip
import hashlib
import json
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.independent_opponent import IndependentOpponent, identity, load_dex
from champions_practice.search_worker import HypotheticalSearchWorker, ShowdownSearchWorker
from champions_practice.tactical_consequences import evaluate_consequences
import tactical_consequences_evaluation as driver


def replay_opponent(live, game, texts, dex):
    side, variant = game['side'], game['truth_variant']
    other = 'p2' if side == 'p1' else 'p1'
    own, enemy = texts[game['own_team']], texts[game['enemy_team']]
    if variant:
        enemy = enemy.replace('Life Orb', 'Sitrus Berry')
    session = live.start_session(battle_format=CHAMPIONS_FORMAT,
        p1_team=own if side == 'p1' else enemy, p2_team=enemy if side == 'p1' else own,
        p1_name='P1', p2_name='P2', seed=game['battle_seed'])['session_id']
    policy = IndependentOpponent(dex, game['opponent_seed'])
    checked = 0
    try:
        selection = {side: 'team 1234', other: 'team 1256' if variant else 'team 1234'}
        live.choose_session(session, p1_choice=selection['p1'], p2_choice=selection['p2'])
        for row in game['rows']:
            assert live.session_view(session, side=side)['view'] == row['view']
            view = live.session_view(session, side=other)['view']
            menu = live.session_public_choices(session, side=other)
            action, trace = policy.choose(view, menu)
            assert action == row['enemy_action'] and trace['fallback'] == row['enemy_trace']['fallback']
            commands = {side: row['action'], other: action}
            live.choose_session(session, p1_choice=commands['p1'], p2_choice=commands['p2'])
            checked += 1
        ended = live.session_view(session, side=side)['view']
        assert ended['ended'] and ended['winner'] == game['winner']
        return checked
    finally:
        live.close_session(session)


def main():
    source = driver.ROOT/'runs/v2-consequences/v2/games.json.gz'
    report = json.loads(gzip.decompress(source.read_bytes()))
    texts, _ = driver.blueprints()
    policy, _ = driver.frozen_policy('e0ae723')
    catalog, dex = PublicCatalog.load(driver.ROOT), load_dex(driver.ROOT)
    # The only search change is the horizon; proposals, hypotheses, scorer and
    # response limits are identical to the two-turn driver.
    driver.evaluate_consequences = lambda *a, **kw: evaluate_consequences(*a, **kw, horizon_turns=1)
    output = driver.ROOT/'runs/v2-consequences/one-turn'
    output.mkdir(parents=True, exist_ok=True)
    cases = [{**c, 'id': c['pair']+'-one-turn', 'version': 'one_turn'}
             for c in report['cases'] if c['version'] == 'consequences']
    paths = ['src/champions_practice/tactical_consequences.py', 'src/champions_practice/independent_opponent.py',
             'scripts/tactical_consequences_ablation.py', 'scripts/tactical_consequences_evaluation.py']
    result = {'cases': cases, 'games': [], 'two_turn_archive_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'opponent_identity': identity(dex), 'source_sha256': {p: hashlib.sha256((driver.ROOT/p).read_bytes()).hexdigest() for p in paths},
        'horizon_turns': 1}
    (output/'manifest.json').write_text(json.dumps(result, indent=2)+'\n')
    with ShowdownSearchWorker(driver.ROOT, startup_timeout_seconds=60) as live, HypotheticalSearchWorker(driver.ROOT, startup_deadline=perf_counter()+60) as hypothetical:
        # Upstream SimpleHeuristicsPlayer does not use Field.TRICK_ROOM. Prove
        # that the adapter enum repair changes none of the recorded decisions.
        checked = 0
        for game in report['games']:
            checked += replay_opponent(live, game, texts, dex)
        result['opponent_replayed_unchanged'] = checked
        print('Opponent mapping repair:', checked, 'recorded decisions unchanged', flush=True)
        for case in cases:
            game = driver.play(live, hypothetical, {**case, 'version': 'consequences'}, texts, policy, catalog, dex)
            game['version'] = 'one_turn'
            result['games'].append(game)
            trace = game['rows'][0]['tactical'] if game['rows'] else None
            print(case['id'], game['status'], game.get('win'), trace['status'] if trace else '', flush=True)
            (output/'games.json.gz').write_bytes(gzip.compress(json.dumps(result).encode()))
    result['summary'] = {s: {'games': sum(g['stage'] == s for g in result['games']),
        'wins': sum(g['stage'] == s and g.get('win', False) for g in result['games']),
        'search_status': dict(Counter(g['rows'][0]['tactical']['status'] for g in result['games'] if g['stage'] == s))}
        for s in ('development', 'validation')}
    (output/'games.json.gz').write_bytes(gzip.compress(json.dumps(result).encode()))
    (output/'summary.json').write_text(json.dumps(result['summary'], indent=2)+'\n')
    print(json.dumps(result['summary'], indent=2))
    assert all(g['status'] == 'complete' for g in result['games'])


if __name__ == '__main__':
    main()
