"""Frozen pre/post PR249 evaluation against an adapted external doubles heuristic."""

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from types import ModuleType

from champions_practice.agent_v2 import PublicCatalog, observe
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.diversity_league import team_text
from champions_practice.independent_opponent import IndependentOpponent, identity, load_dex
from champions_practice.search_worker import ShowdownSearchWorker, TeamValidationWorker

ROOT = Path(__file__).resolve().parents[1]


def frozen_policy(ref):
    commit = subprocess.run(['git', 'rev-parse', ref], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    name = 'independent_reference_'+commit[:12]
    package = ModuleType(name)
    package.__path__ = []
    sys.modules[name] = package
    hashes, modules = {}, {}
    for filename in ('policy', 'joint'):
        source = subprocess.run(['git', 'show', f'{commit}:src/champions_practice/agent_v2/{filename}.py'],
                                cwd=ROOT, capture_output=True, check=True).stdout
        module = ModuleType(name+'.'+filename)
        module.__package__ = name
        module.__file__ = str(ROOT/f'src/champions_practice/agent_v2/{filename}.py')
        sys.modules[module.__name__] = module
        exec(compile(source, module.__file__, 'exec'), module.__dict__)
        modules[filename] = module
        hashes[filename] = hashlib.sha256(source).hexdigest()
    assert modules['joint'].rank_action is modules['policy'].rank_action
    return modules['policy'].decide, {'commit': commit, 'source_sha256': hashes}


def teams():
    # Fresh compositions frozen before running either version; selection isolates play.
    rosters = {
        'rain-grass': ('Pelipper', 'Archaludon', 'Basculegion', 'Rillaboom', 'Venusaur', 'Metagross'),
        'ground-pivot': ('Garchomp', 'Dragonite', 'Incineroar', 'Rotom-Wash', 'Metagross', 'Venusaur'),
        'psychic-room': ('Indeedee-F', 'Gardevoir', 'Metagross', 'Venusaur', 'Armarouge', 'Sneasler'),
        'sand-pivot': ('Tyranitar', 'Excadrill', 'Rotom-Wash', 'Incineroar', 'Garchomp', 'Dragonite'),
        'armarouge-support': ('Armarouge', 'Indeedee-F', 'Venusaur', 'Sneasler', 'Gardevoir', 'Metagross'),
        'grass-balance': ('Incineroar', 'Rillaboom', 'Garchomp', 'Metagross', 'Rotom-Wash', 'Pelipper'),
    }
    return {name: team_text(species).replace('Stomping Tantrum', 'Earthquake')
            for name, species in rosters.items()}


def play(worker, case, texts, metadata, policy, dex):
    side = case['side']
    other = 'p2' if side == 'p1' else 'p1'
    enemy = IndependentOpponent(dex, case['opponent_seed'])
    session = worker.start_session(battle_format=CHAMPIONS_FORMAT,
        p1_team=texts[case['p1_team']], p2_team=texts[case['p2_team']],
        p1_name='P1', p2_name='P2', seed=case['battle_seed'])['session_id']
    rows = []
    try:
        worker.choose_session(session, p1_choice=case['selection'], p2_choice=case['selection'])
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
            enemy_menu = worker.session_public_choices(session, side=other)
            start = perf_counter()
            reply, trace = enemy.choose(enemy_view, enemy_menu)
            enemy_elapsed = perf_counter()-start
            assert decision.action in choices and reply in enemy_menu
            rows.append({'checkpoint': checkpoint, 'view': view, 'legal_actions': choices,
                'decision': asdict(decision), 'elapsed_seconds': elapsed,
                'budget_overrun': elapsed > 8, 'enemy_view': enemy_view,
                'enemy_menu': enemy_menu, 'enemy_action': reply, 'enemy_trace': trace,
                'enemy_seconds': enemy_elapsed, 'enemy_budget_overrun': enemy_elapsed > 8})
            commands = {side: decision.action, other: reply}
            worker.choose_session(session, p1_choice=commands['p1'], p2_choice=commands['p2'])
        return {**case, 'status': 'incomplete', 'rows': rows}
    except Exception as error:
        return {**case, 'status': 'failed', 'error_type': type(error).__name__, 'rows': rows}
    finally:
        worker.close_session(session)


def summarize(report):
    groups = defaultdict(dict)
    for game in report['games']:
        groups[game['pair']][game['version']] = game
    valid = [pair for pair in groups.values() if set(pair) == {'pre249', 'post249'} and
             all(g['status'] == 'complete' for g in pair.values())]
    summary = {'statuses': dict(Counter(g['status'] for g in report['games'])),
        'complete_pairs': len(valid), 'strata': {},
        'post_only_wins': sum(p['post249']['win'] and not p['pre249']['win'] for p in valid),
        'pre_only_wins': sum(p['pre249']['win'] and not p['post249']['win'] for p in valid)}
    for version in ('pre249', 'post249'):
        games = [p[version] for p in valid]
        rows = [r for g in games for r in g['rows']]
        summary['strata'][version] = {'games': len(games), 'wins': sum(g['win'] for g in games),
            'decisions': len(rows), 'deadline_exhaustions': sum(r['decision']['deadline_exhausted'] for r in rows),
            'budget_overruns': sum(r['budget_overrun'] for r in rows),
            'opponent_fallbacks': sum(r['enemy_trace']['fallback'] for r in rows),
            'opponent_budget_overruns': sum(r['enemy_budget_overrun'] for r in rows)}
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seeds', type=int, default=4)
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--mirror-teams', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.seeds <= 10:
        parser.error('seeds must be 1..10')
    policies, identities = {}, {}
    for version, ref in [('pre249', '567556a'), ('post249', 'e0ae723')]:
        policies[version], identities[version] = frozen_policy(ref)
    texts = teams()
    with TeamValidationWorker(ROOT, startup_deadline=perf_counter()+60) as validator:
        for text in texts.values():
            result = validator.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=text)
            assert result['valid'], result['problems']
    dex = load_dex(ROOT)
    metadata = PublicCatalog.load(ROOT)
    names = list(texts)
    cases = []
    for matchup in range(1 if args.smoke else 3):
        for seed_index in range(1 if args.smoke else args.seeds):
            for side in ('p1', 'p2'):
                base_pair = f'{matchup}-{seed_index}-{side}'
                for mirrored in ((False, True) if args.mirror_teams else (False,)):
                    pair = base_pair+('-mirrored' if mirrored else '')
                    actual_side = ('p2' if side == 'p1' else 'p1') if mirrored else side
                    first, second = names[2*matchup:2*matchup+2]
                    if mirrored:
                        first, second = second, first
                    for version in policies:
                        cases.append({'id': pair+'-'+version, 'pair': pair, 'side': actual_side,
                            'mirror_group': base_pair, 'mirrored': mirrored,
                            'version': version, 'p1_team': first, 'p2_team': second,
                            'selection': 'team 1234' if seed_index % 2 == 0 else 'team 1324',
                            'battle_seed': 'sodium,'+hashlib.sha256(('external-eval-v1:'+base_pair).encode()).hexdigest(),
                            'opponent_seed': 'external-policy-v1:'+base_pair})
    report = {'schema': 'independent-opponent-evaluation-v1', 'format': CHAMPIONS_FORMAT,
        'showdown_revision': (ROOT/'showdown-version.txt').read_text().strip(),
        'versions': identities, 'opponent_identity': identity(dex), 'budget_seconds': 8,
        'team_sha256': {name: hashlib.sha256(text.encode()).hexdigest() for name, text in texts.items()},
        'cases': cases, 'games': [], 'smoke': args.smoke, 'mirror_teams': args.mirror_teams,
        'evaluation_source_sha256': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
            ('scripts/independent_opponent_evaluation.py', 'tools/independent-opponent-dex.js')},
        'limitations': ['Adapted upstream simple heuristic, not a proven competitive opponent.',
                        'No Mega augmentation: upstream heuristic does not normally select Mega.',
                        'Seeded random legal fallback is explicit; failures are not silently scored as losses.',
                        'Fixed selected-four sequences isolate play; not full team-preview evaluation.']}
    args.output.mkdir(parents=True, exist_ok=True)
    # Freeze identities, teams and cases before games begin.
    (args.output/'manifest.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    with ShowdownSearchWorker(ROOT, startup_timeout_seconds=60) as worker:
        for case in cases:
            result = play(worker, case, texts, metadata, policies[case['version']], dex)
            report['games'].append(result)
            print(case['id'], result['status'], result.get('win'), flush=True)
            (args.output/'games.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    report['summary'] = summarize(report)
    (args.output/'games.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    (args.output/'summary.json').write_text(json.dumps(report['summary'], indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report['summary'], indent=2))
    if any(g['status'] != 'complete' for g in report['games']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
