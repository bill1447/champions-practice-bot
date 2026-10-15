"""Fresh hidden items/moves outside the frozen opening prior family."""

from collections import Counter, defaultdict
import gzip
import hashlib
import json
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.independent_opponent import identity, load_dex
from champions_practice.search_worker import HypotheticalSearchWorker, ShowdownSearchWorker, TeamValidationWorker
from champions_practice.tactical_consequences import evaluate_consequences
import tactical_consequences_evaluation as driver


def alter_enemy_team(text):
    items = {'Tyranitar': 'Expert Belt', 'Excadrill': 'Focus Sash', 'Pelipper': 'Wacan Berry',
             'Archaludon': 'Magnet', 'Basculegion': 'Choice Scarf', 'Rillaboom': 'Miracle Seed',
             'Incineroar': 'Charcoal', 'Rotom-Wash': 'Sitrus Berry'}
    moves = {'Tyranitar': {'Protect': 'Ice Punch'},
        'Excadrill': {'High Horsepower': 'Earthquake', 'Rock Slide': 'Swords Dance'},
        'Pelipper': {'Weather Ball': 'Hydro Pump'}, 'Archaludon': {'Protect': 'Thunderbolt'},
        'Basculegion': {'Protect': 'Flip Turn'}, 'Rillaboom': {'High Horsepower': 'Drain Punch'},
        'Incineroar': {'Parting Shot': 'Taunt'}}
    chunks = []
    for chunk in text.strip().split('\n\n'):
        lines = chunk.splitlines()
        name = lines[0].split(' @ ')[0]
        if name in items:
            lines[0] = name+' @ '+items[name]
        lines = ['- '+moves.get(name, {}).get(line[2:], line[2:]) if line.startswith('- ') else line for line in lines]
        chunks.append('\n'.join(lines))
    return '\n\n'.join(chunks)+'\n'


class UnfamiliarLiveWorker:
    """Only the live driver receives perturbed truth; decision helpers do not."""
    def __init__(self, live, side):
        self.live, self.side = live, side

    def start_session(self, **kwargs):
        enemy_key = 'p2_team' if self.side == 'p1' else 'p1_team'
        kwargs[enemy_key] = alter_enemy_team(kwargs[enemy_key])
        return self.live.start_session(**kwargs)

    def __getattr__(self, name):
        return getattr(self.live, name)


def summarize(games):
    pairs = defaultdict(dict)
    for game in games:
        pairs[game['pair']][game['version']] = game
    complete = [p for p in pairs.values() if set(p) == {'incumbent', 'one_turn'} and all(g['status'] == 'complete' for g in p.values())]
    clean = [p for p in complete if not any(r['enemy_trace']['fallback'] for g in p.values() for r in g['rows'])]
    result = {'statuses': dict(Counter(g['status'] for g in games))}
    for label, selected in [('all', complete), ('fallback_free', clean)]:
        result[label] = {'pairs': len(selected), 'incumbent_wins': sum(p['incumbent']['win'] for p in selected),
            'one_turn_wins': sum(p['one_turn']['win'] for p in selected),
            'one_turn_only': sum(p['one_turn']['win'] and not p['incumbent']['win'] for p in selected),
            'incumbent_only': sum(p['incumbent']['win'] and not p['one_turn']['win'] for p in selected)}
    traces = [p['one_turn']['rows'][0]['tactical'] for p in complete]
    result['search_status'] = dict(Counter(t['status'] for t in traces))
    result['search_reasons'] = dict(Counter(t.get('reason', '') for t in traces if t['status'] != 'complete'))
    result['search_overruns'] = sum(t['elapsed_seconds'] > 8 for t in traces)
    result['opponent_fallbacks'] = sum(r['enemy_trace']['fallback'] for g in games for r in g['rows'])
    return result


def main():
    texts, matchups = driver.blueprints()
    actual = {k: alter_enemy_team(v) for k, v in texts.items()}
    output = driver.ROOT/'runs/v2-coverage/unfamiliar-v1'
    output.mkdir(parents=True, exist_ok=True)
    # No expanded arm beats the cheaper 8/3 baseline on fallback-free evidence.
    # Freeze that selection and fresh cases before this test, without retuning.
    driver.evaluate_consequences = lambda *a, **kw: evaluate_consequences(*a, **kw, horizon_turns=1)
    policy, policy_identity = driver.frozen_policy('e0ae723')
    catalog, dex = PublicCatalog.load(driver.ROOT), load_dex(driver.ROOT)
    cases = []
    for stage, pairs in matchups.items():
        for matchup, (own, enemy) in enumerate(pairs):
            for seed in range(2):
                mirror = f'unfamiliar-{stage}-{matchup}-{seed}'
                for side in ('p1', 'p2'):
                    pair = mirror+'-'+side
                    for version in ('incumbent', 'one_turn'):
                        cases.append({'id': pair+'-'+version, 'pair': pair, 'mirror_group': mirror,
                            'stage': stage, 'own_team': own, 'enemy_team': enemy, 'side': side,
                            'version': version, 'truth_variant': seed % 2,
                            'battle_seed': 'sodium,'+hashlib.sha256(('coverage-ood-v1:'+mirror).encode()).hexdigest(),
                            'opponent_seed': 'coverage-ood-enemy-v1:'+mirror})
    paths = ['src/champions_practice/tactical_consequences.py', 'src/champions_practice/exact_search.py',
             'src/champions_practice/independent_opponent.py', 'scripts/tactical_consequences_evaluation.py',
             'scripts/tactical_unfamiliar_sets.py']
    report = {'cases': cases, 'games': [], 'selection': {'root_actions': 8, 'responses': 3, 'horizon_turns': 1},
        'selection_reason': 'Expanded arms have no fallback-free advantage; retain cheaper original experimental baseline.',
        'incumbent': policy_identity, 'opponent_identity': identity(dex),
        'source_sha256': {p: hashlib.sha256((driver.ROOT/p).read_bytes()).hexdigest() for p in paths},
        'prior_sha256': {k: hashlib.sha256(v.encode()).hexdigest() for k, v in texts.items()},
        'actual_hidden_teams': {k: v for k, v in actual.items() if any(enemy == k for pairs in matchups.values() for _, enemy in pairs)},
        'limitations': ['Fresh RNG and hidden item/move combinations, but familiar species, compositions and stat allocations.',
            'Actual item/move changes stay in the live driver; search priors remain frozen and misspecified.',
            'Opening-only intervention; later actions use frozen V2. Mirrored outcomes are correlated.',
            'No unseen-ability/stat-family or midgame policy claim.']}
    (output/'manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    with TeamValidationWorker(driver.ROOT, startup_deadline=perf_counter()+60) as validator:
        for name in report['actual_hidden_teams']:
            result = validator.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=actual[name])
            assert result['valid'], (name, result['problems'])
    with ShowdownSearchWorker(driver.ROOT, startup_timeout_seconds=60) as live, HypotheticalSearchWorker(driver.ROOT, startup_deadline=perf_counter()+60) as hypothetical:
        for case in cases:
            run_case = {**case, 'version': 'consequences' if case['version'] == 'one_turn' else 'incumbent'}
            game = driver.play(UnfamiliarLiveWorker(live, case['side']), hypothetical, run_case, texts, policy, catalog, dex)
            game['version'] = case['version']
            report['games'].append(game)
            trace = game['rows'][0]['tactical'] if game['rows'] else None
            print(case['id'], game['status'], game.get('win'), trace['status'] if trace else '', flush=True)
            (output/'games.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    report['summary'] = summarize(report['games'])
    (output/'games.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    (output/'summary.json').write_text(json.dumps(report['summary'], indent=2)+'\n')
    print(json.dumps(report['summary'], indent=2))
    assert all(g['status'] == 'complete' for g in report['games'])


if __name__ == '__main__':
    main()
