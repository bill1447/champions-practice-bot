"""Validate external evaluation and retain a bounded, diagnostic-only loss witness."""

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path

from poke_env.battle.pokemon_type import PokemonType
from poke_env.data import GenData

from champions_practice.agent_v2 import PublicCatalog
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.independent_opponent import identity, load_dex
from champions_practice.search_worker import ShowdownSearchWorker
from independent_opponent_evaluation import ROOT, frozen_policy, summarize, teams


def loss_witness(report):
    game = next(g for g in report['games'] if g['id'] == '1-0-p1-post249')
    first = game['rows'][0]
    candidates = [first['decision']['action'], 'move trickroom, move protect mega',
                  'move followme, move mysticalfire +2 mega', 'move psychic +2, move protect mega']
    assert all(action in first['legal_actions'] for action in candidates)
    texts = teams()
    with ShowdownSearchWorker(ROOT, startup_timeout_seconds=60) as worker:
        session = worker.start_session(battle_format=CHAMPIONS_FORMAT,
            p1_team=texts[game['p1_team']], p2_team=texts[game['p2_team']],
            p1_name='P1', p2_name='P2', seed=game['battle_seed'])['session_id']
        try:
            worker.choose_session(session, p1_choice=game['selection'], p2_choice=game['selection'])
            assert worker.session_view(session, side='p1')['view'] == first['view']
            state = worker.session_snapshot(session)['state']
            outputs = {}
            for action in candidates:
                branches = [{'p1_choice': action, 'p2_choice': first['enemy_action'],
                    'rng_seed': 'sodium,'+hashlib.sha256(f'independent-loss-witness:{i}'.encode()).hexdigest(),
                    'include_state': True} for i in range(8)]
                samples = []
                for branch in worker.branch_many(state=state, branches=branches):
                    own, foe = branch['state']['sides']
                    samples.append({'own_survivors': sum(m['hp'] > 0 for m in own['pokemon']),
                                    'foe_survivors': sum(m['hp'] > 0 for m in foe['pokemon'])})
                outputs[action] = samples
            return {'case': game['id'], 'turn': first['view']['turn'],
                'selected': first['decision']['action'], 'fixed_enemy_response': first['enemy_action'],
                'scope': 'Eight coupled futures of actual sealed native state; fixed enemy response, not optimality or win probabilities.',
                'samples': outputs}
        finally:
            worker.close_session(session)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native-witness', action='store_true')
    args = parser.parse_args()
    report = json.loads(gzip.decompress(args.archive.read_bytes()))
    manifest = json.loads((args.archive.parent/'manifest.json').read_text())
    assert manifest['games'] == [] and manifest['cases'] == report['cases']
    assert manifest['versions'] == report['versions']
    assert identity(load_dex(ROOT)) == report['opponent_identity']
    assert {name: hashlib.sha256(text.encode()).hexdigest() for name, text in teams().items()} == report['team_sha256']
    for version, expected_policy in report['versions'].items():
        _, observed_policy = frozen_policy(expected_policy['commit'])
        assert observed_policy == expected_policy
    for name, digest in report.get('evaluation_source_sha256', {}).items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest
    assert len({c['id'] for c in report['cases']}) == len(report['cases'])
    expected = {c['id']: c for c in report['cases']}
    assert len(report['games']) == len(expected)
    assert {g['id'] for g in report['games']} == set(expected)
    pairs = defaultdict(dict)
    fallback_details = []
    for game in report['games']:
        assert all(game[k] == v for k, v in expected[game['id']].items())
        assert game['status'] == 'complete' and game['winner'] in {'P1', 'P2'}
        assert game['version'] not in pairs[game['pair']]
        pairs[game['pair']][game['version']] = game
        for row in game['rows']:
            assert row['decision']['action'] in row['legal_actions']
            assert row['enemy_action'] in row['enemy_menu']
            if row['enemy_trace']['fallback']:
                fallback_details.append({'game': game['id'], 'turn': row['view']['turn'],
                    'phase': row['enemy_view']['phase'], 'reason': row['enemy_trace']['fallback_reason']})
    for pair in pairs.values():
        assert set(pair) == {'pre249', 'post249'}
        assert all(pair['pre249'][k] == pair['post249'][k] for k in
                   ('side', 'battle_seed', 'opponent_seed', 'selection', 'p1_team', 'p2_team'))
    assert summarize(report) == report['summary']
    clean = [p for p in pairs.values() if not any(row['enemy_trace']['fallback']
             for g in p.values() for row in g['rows'])]
    clean_result = {'pairs': len(clean), **{v: sum(p[v]['win'] for p in clean) for v in ('pre249', 'post249')},
        'post_only_wins': sum(p['post249']['win'] and not p['pre249']['win'] for p in clean),
        'pre_only_wins': sum(p['pre249']['win'] and not p['post249']['win'] for p in clean)}
    mirror_groups = defaultdict(dict)
    if report.get('mirror_teams'):
        for pair in pairs.values():
            for version, game in pair.items():
                mirror_groups[game['mirror_group']][version, game['mirrored']] = game
        for group in mirror_groups.values():
            assert len(group) == 4
            for version in ('pre249', 'post249'):
                normal, mirrored = group[version, False], group[version, True]
                assert normal['side'] != mirrored['side']
                assert normal['p1_team'] == mirrored['p2_team'] and normal['p2_team'] == mirrored['p1_team']
                assert normal['battle_seed'] == mirrored['battle_seed'] and normal['opponent_seed'] == mirrored['opponent_seed']
    matchups, controlled = {}, {}
    for pair in pairs.values():
        label = pair['post249']['p1_team']+' / '+pair['post249']['p2_team']
        group = matchups.setdefault(label, {'pre249': Counter(), 'post249': Counter()})
        for version in group:
            group[version][pair[version]['side']+'-games'] += 1
            group[version][pair[version]['side']+'-wins'] += pair[version]['win']
            game = pair[version]
            own_team = game['p1_team'] if game['side'] == 'p1' else game['p2_team']
            bucket = controlled.setdefault(own_team, {'pre249': Counter(), 'post249': Counter()})
            bucket[version]['games'] += 1
            bucket[version]['wins'] += game['win']
    static = PublicCatalog.load(ROOT)
    type_checks = 0
    for defender, attacks in static.types.items():
        if defender in {'Stellar', '???'}:
            continue
        for attacker in static.types:
            if attacker in {'Stellar', '???'}:
                continue
            observed = PokemonType.from_name(attacker).damage_multiplier(PokemonType.from_name(defender),
                type_chart=GenData.from_gen(9).type_chart)
            assert observed == {0: 1, 1: 2, 2: .5, 3: 0}[attacks.get(attacker, 0)]
            type_checks += 1
    output = {'archive_sha256': hashlib.sha256(args.archive.read_bytes()).hexdigest(),
        'manifest_sha256': hashlib.sha256((args.archive.parent/'manifest.json').read_bytes()).hexdigest(),
        'summary': report['summary'], 'fallback_free_pairs': clean_result, 'fallbacks': fallback_details,
        'matchups_by_side': matchups, 'opponent_identity': report['opponent_identity'],
        'controlled_team_results': controlled, 'validated_mirror_groups': len(mirror_groups),
        'policy_identities': report['versions'], 'validated_public_type_matchups': type_checks,
        'versions_frozen_no_policy_tuning': True,
        'limitations': report['limitations'] + ['Opponents and team/seed pairs are correlated; no competitive-strength certification.']}
    if args.native_witness:
        output['loss_witness'] = loss_witness(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
