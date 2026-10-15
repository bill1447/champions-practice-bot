"""Audit factorial coverage, misspecified priors, and early midgame admission."""

from collections import Counter, defaultdict
import gzip
import hashlib
import json

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.exact_search import score_exact_summary_breakdown
from champions_practice.independent_opponent import identity, load_dex
from champions_practice.search_worker import ShowdownSearchWorker
from tactical_consequences_evaluation import ROOT, blueprints


def load(path, filename='games.json.gz'):
    directory = ROOT/path
    raw = (directory/filename).read_bytes()
    report = json.loads(gzip.decompress(raw) if filename.endswith('.gz') else raw)
    manifest = json.loads((directory/'manifest.json').read_text())
    for key, value in manifest.items():
        if key not in ('games', 'positions'):
            assert report[key] == value
    assert manifest.get('games', manifest.get('positions')) == []
    for name, digest in manifest['source_sha256'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest, name
    if 'games' in report:
        cases = {c['id']: c for c in report['cases']}
        assert len(cases) == len(report['cases']) == len(report['games'])
        assert {g['id'] for g in report['games']} == set(cases)
        for game in report['games']:
            assert all(game[k] == v for k, v in cases[game['id']].items())
            assert game['status'] == 'complete'
            assert all(r['action'] in r['legal_actions'] for r in game['rows'])
            assert all(r['action'] == r['baseline'] for r in game['rows'][1:])
    else:
        assert {p['id'] for p in report['positions']} == {c['id'] for c in report['cases']}
        assert len(report['positions']) == len(report['cases'])
    return report, {'archive_sha256': hashlib.sha256(raw).hexdigest(),
                    'manifest_sha256': hashlib.sha256((directory/'manifest.json').read_bytes()).hexdigest(),
                    'source_sha256': manifest['source_sha256']}


def has_fallback(game):
    return any(r['enemy_trace']['fallback'] for r in game['rows'])


def comparison(left, right):
    return {'pairs': len(left), 'left_wins': sum(g['win'] for g in left), 'right_wins': sum(g['win'] for g in right),
        'left_only': sum(a['win'] and not b['win'] for a, b in zip(left, right, strict=True)),
        'right_only': sum(b['win'] and not a['win'] for a, b in zip(left, right, strict=True))}


def ranks(game):
    return {r['action']: r for r in game['rows'][0]['tactical']['ranking']}


def witness(worker, groups, texts, pair):
    games = groups[pair]
    game = games['base']
    side, variant = game['side'], game['truth_variant']
    other = 'p2' if side == 'p1' else 'p1'
    own, enemy = texts[game['own_team']], texts[game['enemy_team']]
    if variant:
        enemy = enemy.replace('Life Orb', 'Sitrus Berry')
    session = worker.start_session(battle_format=CHAMPIONS_FORMAT,
        p1_team=own if side == 'p1' else enemy, p2_team=enemy if side == 'p1' else own,
        p1_name='P1', p2_name='P2', seed=game['battle_seed'])['session_id']
    try:
        selections = {side: 'team 1234', other: 'team 1256' if variant else 'team 1234'}
        worker.choose_session(session, p1_choice=selections['p1'], p2_choice=selections['p2'])
        first = game['rows'][0]
        assert worker.session_view(session, side=side)['view'] == first['view']
        # All archived decisions are sealed before this diagnostic snapshot.
        state = worker.session_snapshot(session)['state']
        record = {'pair': pair, 'fixed_enemy_reply': first['enemy_action'], 'plans': {}}
        for arm, g in games.items():
            row = g['rows'][0]
            action = row['action']
            branches = []
            for sample in range(8):
                commands = {side: action, other: first['enemy_action']}
                branches.append({'p1_choice': commands['p1'], 'p2_choice': commands['p2'],
                    'rng_seed': 'sodium,'+hashlib.sha256(f'coverage-witness:{sample}'.encode()).hexdigest()})
            samples = []
            for outcome in worker.branch_many(state=state, branches=branches):
                summary = outcome['summary']
                samples.append({'own_survivors': sum(m['hp'] > 0 for m in summary[side]['pokemon']),
                    'foe_survivors': sum(m['hp'] > 0 for m in summary[other]['pokemon']),
                    'utility': score_exact_summary_breakdown(summary, side).total})
            record['plans'][arm] = {'action': action,
                'modeled_worst_utility': ranks(g)[action]['worst_world_utility'],
                'samples': samples, 'full_game_win': g['win'], 'fallback_affected': has_fallback(g)}
        return record
    finally:
        worker.close_session(session)


def main():
    base, base_identity = load('runs/v2-consequences/one-turn')
    expanded, expanded_identity = load('runs/v2-coverage/v1')
    unfamiliar, unfamiliar_identity = load('runs/v2-coverage/unfamiliar-v1')
    midgame, midgame_identity = load('runs/v2-coverage/midgame-v1', 'positions.json')
    assert expanded['control_archive_sha256'] == base_identity['archive_sha256']
    assert all(r['opponent_identity'] == identity(load_dex(ROOT)) for r in (base, expanded, unfamiliar))
    for path in ('src/champions_practice/tactical_consequences.py', 'src/champions_practice/independent_opponent.py'):
        assert base['source_sha256'][path] == expanded['source_sha256'][path] == unfamiliar['source_sha256'][path]
    groups = defaultdict(dict)
    for game in base['games']:
        groups[game['pair']]['base'] = game
    for game in expanded['games']:
        groups[game['pair']][game['version']] = game
    for group in groups.values():
        assert set(group) == {'base', 'candidates', 'responses', 'both'}
        initial = group['base']
        for game in group.values():
            assert all(game[k] == initial[k] for k in ('side', 'battle_seed', 'opponent_seed', 'truth_variant', 'own_team', 'enemy_team'))
            assert game['rows'][0]['view'] == initial['rows'][0]['view']
            assert game['rows'][0]['enemy_action'] == initial['rows'][0]['enemy_action']
            assert game['rows'][0]['tactical']['status'] == 'complete'
        own = ranks(initial)
        wider_own, wider_reply, both = (ranks(group[a]) for a in ('candidates', 'responses', 'both'))
        assert set(own) <= set(wider_own) and set(own) == set(wider_reply)
        assert set(wider_own) == set(both)
        for small, large in ((own, wider_own), (wider_reply, both)):
            for action in small:
                assert small[action]['worst_world_utility'] == large[action]['worst_world_utility']
                assert small[action]['worlds'] == large[action]['worlds']
        for small, large in ((own, wider_reply), (wider_own, both)):
            for action in small:
                for a, b in zip(small[action]['worlds'], large[action]['worlds'], strict=True):
                    assert set(a['sampled_responses']) <= set(b['sampled_responses'])
                assert large[action]['worst_world_utility'] <= small[action]['worst_world_utility']+1e-8
    common_clean = [g for g in groups.values() if not any(has_fallback(v) for v in g.values())]
    comparisons, coverage = {}, {}
    for arm in ('base', 'candidates', 'responses', 'both'):
        games = [g[arm] for g in groups.values()]
        coverage[arm] = {'actual_reply_in_every_world': sum(all(g['rows'][0]['enemy_action'] in w['sampled_responses']
            for w in ranks(g)[g['rows'][0]['action']]['worlds']) for g in games),
            'search_mean_seconds': sum(g['rows'][0]['tactical']['elapsed_seconds'] for g in games)/len(games),
            'root_changes': sum(g[arm]['rows'][0]['action'] != g['base']['rows'][0]['action'] for g in groups.values())}
        if arm == 'base':
            continue
        clean = [g for g in groups.values() if not has_fallback(g['base']) and not has_fallback(g[arm])]
        comparisons[arm] = {'all': comparison([g['base'] for g in groups.values()], games),
            'pairwise_fallback_free': comparison([g['base'] for g in clean], [g[arm] for g in clean]),
            'common_fallback_free': comparison([g['base'] for g in common_clean], [g[arm] for g in common_clean])}
    texts, _ = blueprints()
    with ShowdownSearchWorker(ROOT, startup_timeout_seconds=60) as worker:
        witnesses = [witness(worker, groups, texts, pair) for pair in
                     ('development-0-0-p1', 'validation-0-0-p1', 'validation-2-0-p1')]
    result = {'disposition': 'retain 8/3 as experimental baseline; no default promotion',
        'runs': {'base': base_identity, 'coverage': expanded_identity, 'unfamiliar': unfamiliar_identity, 'midgame': midgame_identity},
        'nested_candidate_sets_and_unchanged_shared_scores': True,
        'nested_response_sets_and_nonincreasing_worst_utilities': True,
        'coverage_summary': expanded['summary'], 'comparisons': comparisons, 'coverage': coverage,
        'unfamiliar_summary': unfamiliar['summary'], 'midgame_summary': midgame['summary'],
        'midgame_reasons': dict(Counter(p.get('production_fallback_reason', p.get('error_type')) for p in midgame['positions'])),
        'midgame_positions': midgame['positions'],
        'native_witness_scope': 'Sealed actual states, fixed recorded reply, eight coupled futures; diagnostics only, not win probabilities or deployable inputs.',
        'native_witnesses': witnesses,
        'limitations': expanded['limitations']+unfamiliar['limitations']+midgame['limitations']}
    (ROOT/'reviews/v2-coverage-2026-10-15.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: result[k] for k in ('comparisons', 'coverage', 'unfamiliar_summary', 'midgame_summary', 'midgame_reasons')}, indent=2))


if __name__ == '__main__':
    main()
