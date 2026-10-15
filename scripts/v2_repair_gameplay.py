"""Paired development games against frozen V2 and frozen related opponents."""

import argparse
from collections import Counter
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from types import FunctionType, ModuleType

from champions_practice.agent_v2 import PublicCatalog, decide, observe
from champions_practice.competitive_evaluation import fixtures, pressure_choice
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.risk_joint_audit import guard_choice
from champions_practice.search_worker import ShowdownSearchWorker, TeamValidationWorker

ROOT = Path(__file__).resolve().parents[1]
BASELINE = '567556a'


def frozen_policy():
    source = subprocess.run(['git', 'show', BASELINE+':src/champions_practice/agent_v2/policy.py'],
                            cwd=ROOT, capture_output=True, check=True).stdout
    module = ModuleType('frozen_v2_repair_reference')
    module.__file__ = str(ROOT/'src/champions_practice/agent_v2/policy.py')
    sys.modules[module.__name__] = module
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    return module, hashlib.sha256(source).hexdigest()


def freeze_opponent(function, reference):
    # Clone only the function globals: neither live policy nor opponent is mutated.
    namespace = {**function.__globals__, 'rank_action': reference.rank_action}
    return FunctionType(function.__code__, namespace, function.__name__, function.__defaults__)


def play(worker, case, teams, metadata, policy, enemy):
    side = case['side']
    other = 'p2' if side == 'p1' else 'p1'
    session = worker.start_session(battle_format=CHAMPIONS_FORMAT,
        p1_team=teams[case['p1_team']], p2_team=teams[case['p2_team']],
        p1_name='P1', p2_name='P2', seed=case['seed'])['session_id']
    rows = []
    try:
        worker.choose_session(session, p1_choice='team 1234', p2_choice='team 1234')
        for checkpoint in range(120):
            view = worker.session_view(session, side=side)['view']
            if view['ended']:
                return {**case, 'status': 'complete', 'winner': view['winner'],
                        'win': view['winner'] == side.upper(), 'rows': rows}
            choices = worker.session_public_choices(session, side=side)
            start = perf_counter()
            decision = policy(observe(view, choices, deadline=start+8), metadata)
            elapsed = perf_counter()-start
            enemy_view = worker.session_view(session, side=other)['view']
            enemy_choices = worker.session_public_choices(session, side=other)
            reply = enemy(enemy_view, enemy_choices, 8, metadata)[0]
            assert decision.action in choices and reply in enemy_choices
            rows.append({'checkpoint': checkpoint, 'view': view, 'legal_actions': choices,
                         'decision': asdict(decision), 'elapsed_seconds': elapsed,
                         'budget_overrun': elapsed > 8, 'enemy_action': reply})
            commands = {side: decision.action, other: reply}
            worker.choose_session(session, p1_choice=commands['p1'], p2_choice=commands['p2'])
        return {**case, 'status': 'incomplete', 'rows': rows}
    finally:
        worker.close_session(session)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seeds', type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.seeds <= 10:
        parser.error('seeds must be 1..10')
    reference, reference_hash = frozen_policy()
    opponents = {name: freeze_opponent(fn, reference)
                 for name, fn in [('pressure', pressure_choice), ('guard', guard_choice)]}
    _, teams = fixtures()
    names = list(teams)[:3]
    metadata = PublicCatalog.load(ROOT)
    with TeamValidationWorker(ROOT) as validator:
        for team in teams.values():
            assert validator.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=team)['valid']
    report = {'baseline_ref': BASELINE, 'baseline_policy_sha256': reference_hash,
        'candidate_policy_sha256': hashlib.sha256((ROOT/'src/champions_practice/agent_v2/policy.py').read_bytes()).hexdigest(),
        'catalog_sha256': metadata.fingerprint,
        'team_sha256': {k: hashlib.sha256(v.encode()).hexdigest() for k, v in teams.items()},
        'budget_seconds': 8, 'games': [],
        'limitations': ['Reused development teams and related opponents; not competitive strength evidence.',
                        'No final holdout used; seeds and sides are paired, not independent trials.']}
    args.output.mkdir(parents=True, exist_ok=True)
    with ShowdownSearchWorker(ROOT) as worker:
        for index, name in enumerate(names):
            for seed_index in range(args.seeds):
                seed = 'sodium,'+hashlib.sha256(f'v2-steel-roller-development:{index}:{seed_index}'.encode()).hexdigest()
                for side in ('p1', 'p2'):
                    for opponent, enemy in opponents.items():
                        pair = f'{index}-{seed_index}-{side}-{opponent}'
                        for agent, policy in [('baseline', reference.decide), ('candidate', decide)]:
                            case = {'id': pair+'-'+agent, 'pair': pair, 'side': side,
                                    'p1_team': name, 'p2_team': names[(index+1)%3],
                                    'seed': seed, 'agent': agent, 'opponent': opponent}
                            game = play(worker, case, teams, metadata, policy, enemy)
                            report['games'].append(game)
                            print(game['id'], game['status'], game.get('win'), flush=True)
                            (args.output/'games.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    summary = {'statuses': dict(Counter(g['status'] for g in report['games'])), 'strata': {}}
    for opponent in opponents:
        games = [g for g in report['games'] if g['opponent'] == opponent]
        pairs = {}
        for game in games:
            pairs.setdefault(game['pair'], {})[game['agent']] = game
        assert all(set(pair) == {'baseline', 'candidate'} for pair in pairs.values())
        summary['strata'][opponent] = {
            agent: {'games': len(pairs), 'wins': sum(p[agent]['win'] for p in pairs.values())}
            for agent in ('baseline', 'candidate')}
        summary['strata'][opponent].update({
            'candidate_only_wins': sum(p['candidate']['win'] and not p['baseline']['win'] for p in pairs.values()),
            'baseline_only_wins': sum(p['baseline']['win'] and not p['candidate']['win'] for p in pairs.values())})
    rows = [r for g in report['games'] for r in g['rows']]
    summary.update(decisions=len(rows), budget_overruns=sum(r['budget_overrun'] for r in rows),
                   deadline_exhaustions=sum(r['decision']['deadline_exhausted'] for r in rows))
    summary['no_terrain_steel_roller_selections'] = {
        agent: sum('move steelroller ' in r['decision']['action'] and
                   not r['view']['field'].get('terrain')
                   for g in report['games'] if g['agent'] == agent for r in g['rows'])
        for agent in ('baseline', 'candidate')}
    first_changes = []
    all_pairs = {}
    for game in report['games']:
        all_pairs.setdefault(game['pair'], {})[game['agent']] = game
    for pair_id, pair in all_pairs.items():
        for old, new in zip(pair['baseline']['rows'], pair['candidate']['rows']):
            if old['decision']['action'] != new['decision']['action']:
                assert old['view'] == new['view']
                first_changes.append({'pair': pair_id, 'turn': old['view']['turn'],
                                      'baseline': old['decision']['action'],
                                      'candidate': new['decision']['action']})
                break
    summary['first_action_changes'] = first_changes
    report['summary'] = summary
    (args.output/'games.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    (args.output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))
    assert summary['statuses'] == {'complete': args.seeds*3*2*2*2}


if __name__ == '__main__':
    main()
