"""Frozen paired full-game native/V2 trial against independent public policies."""

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
from time import perf_counter

from poke_env.player.baselines import MaxBasePowerPlayer

from champions_practice.agent_v2 import PublicCatalog, observe
from champions_practice.competitive_evaluation import canonical_view
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.diversity_league import catalog as public_priors
from champions_practice.experimental_native_player import ExperimentalNativePlayer
from champions_practice.independent_opponent import IndependentOpponent, identity, load_dex
from champions_practice.search_worker import ShowdownSearchWorker, TeamValidationWorker
from tactical_consequences_evaluation import ROOT, blueprints, frozen_policy


class MaxPower:
    choose_move = staticmethod(MaxBasePowerPlayer.choose_doubles_move)


def play(live, case, texts, policy, catalog, dex):
    side = case['side']
    other = 'p1' if side == 'p2' else 'p2'
    enemy = IndependentOpponent(dex, case['opponent_seed'])
    if case['opponent'] == 'max-base-power':
        enemy.policy = MaxPower()
    own, prior = texts[case['own_team']], texts[case['enemy_team']]
    # Truth construction is confined to the driver; no truth seed or live
    # session/state/command is passed to ExperimentalNativePlayer.
    actual = prior
    if case['hidden_family'] == 'heldout':
        actual = prior.replace('Protect', 'Substitute').replace('Life Orb', 'Sitrus Berry')
    session = live.start_session(battle_format=CHAMPIONS_FORMAT,
        p1_team=own if side == 'p1' else actual, p2_team=actual if side == 'p1' else own,
        p1_name='P1', p2_name='P2', seed=case['battle_seed'])['session_id']
    player = ExperimentalNativePlayer(ROOT, own_team=own, opening_prior=prior,
        priors=public_priors(), catalog=catalog, incumbent_policy=policy) if case['version'] == 'native' else None
    rows = []
    try:
        selection = {side: 'team 1234', other: 'team 1256' if case['hidden_family'] == 'heldout' else 'team 1234'}
        live.choose_session(session, p1_choice=selection['p1'], p2_choice=selection['p2'])
        for checkpoint in range(180):
            view = live.session_view(session, side=side)['view']
            if view['ended']:
                return {**case, 'status': 'complete', 'win': view['winner'] == side.upper(),
                        'winner': view['winner'], 'rows': rows}
            menu = live.session_public_choices(session, side=side)
            start = perf_counter()
            if player:
                action, trace = player.decide(canonical_view(view, side), menu)
            else:
                action = policy(observe(view, menu, deadline=start+8), catalog).action
                trace = None
            latency = perf_counter()-start
            enemy_view = live.session_view(session, side=other)['view']
            enemy_menu = live.session_public_choices(session, side=other)
            reply, enemy_trace = enemy.choose(enemy_view, enemy_menu)
            enemy_trace['policy'] = case['opponent']
            assert action in menu and reply in enemy_menu
            rows.append({'turn': view['turn'], 'phase': view['phase'], 'action': action,
                'view': view, 'legal_actions': menu, 'decision': trace, 'total_decision_seconds': latency,
                'enemy_action': reply, 'enemy_trace': enemy_trace})
            commands = {side: action, other: reply}
            live.choose_session(session, p1_choice=commands['p1'], p2_choice=commands['p2'])
        return {**case, 'status': 'incomplete', 'rows': rows}
    except Exception as error:
        return {**case, 'status': 'failed', 'error_type': type(error).__name__, 'error': str(error), 'rows': rows}
    finally:
        live.close_session(session)


def summarize(games):
    pairs = defaultdict(dict)
    for game in games:
        pairs[game['pair']][game['version']] = game
    valid = [p for p in pairs.values() if set(p) == {'v2', 'native'} and
             all(g['status'] == 'complete' for g in p.values())]
    result = {'statuses': dict(Counter(g['status'] for g in games))}
    for label, selected in [('all', valid), ('opponent_fallback_free', [p for p in valid if
            not any(r['enemy_trace']['fallback'] for g in p.values() for r in g['rows'])])]:
        result[label] = {'pairs': len(selected),
            'v2_wins': sum(p['v2']['win'] for p in selected),
            'native_wins': sum(p['native']['win'] for p in selected),
            'native_only': sum(p['native']['win'] and not p['v2']['win'] for p in selected),
            'v2_only': sum(p['v2']['win'] and not p['native']['win'] for p in selected)}
    rows = [r for g in games if g['version'] == 'native' for r in g['rows']]
    actionable = [r for r in rows if r['decision']['admission_attempted']]
    result['actionable_decisions'] = len(actionable)
    result['statuses_by_decision'] = dict(Counter(r['decision']['status'] for r in actionable))
    result['fallback_reasons'] = dict(Counter(r['decision']['reason'] for r in actionable if r['decision']['status'] != 'search'))
    result['admitted_decisions'] = sum(r['decision']['admitted_worlds'] > 0 for r in actionable)
    result['action_disagreements'] = sum(r['decision']['disagreement'] for r in actionable)
    result['coverage_by_turn'] = {str(t): {'actionable': len(rs),
        'admitted': sum(r['decision']['admitted_worlds'] > 0 for r in rs),
        'search_completed': sum(r['decision']['status'] == 'search' for r in rs),
        'disagreements': sum(r['decision']['disagreement'] for r in rs)}
        for t in sorted({r['turn'] for r in actionable}) if (rs := [r for r in actionable if r['turn'] == t])}
    times = sorted(r['total_decision_seconds'] for r in actionable)
    result['latency'] = {'mean': sum(times)/max(1, len(times)), 'max': max(times, default=0),
        'p95': times[min(len(times)-1, int(.95*len(times)))] if times else 0,
        'over_eight_seconds': sum(t > 8 for t in times)}
    result['forensics'] = [{'pair': p['native']['pair'], 'v2_win': p['v2']['win'], 'native_win': p['native']['win'],
        'changed_decisions': [{'turn': r['turn'], 'phase': r['phase'], 'v2': r['decision']['incumbent'],
                              'native': r['action'], 'checkpoint': i}
                             for i, r in enumerate(p['native']['rows']) if r['decision']['disagreement']]}
        for p in valid]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pairs', type=int, default=24)
    args = parser.parse_args()
    texts, matchups = blueprints()
    policy, policy_identity = frozen_policy('e0ae723')
    catalog, dex = PublicCatalog.load(ROOT), load_dex(ROOT)
    cases = []
    # Freeze the full matrix before play: six compositions, two independent
    # upstream opponents, two hidden families, side alternation, fresh RNG.
    for stage, compositions in matchups.items():
        for index, (own, enemy) in enumerate(compositions):
            for opponent in ('simple-heuristics', 'max-base-power'):
                for family in ('prior', 'heldout'):
                    pair = f'{stage}-{index}-{opponent}-{family}'
                    for arm in ('v2', 'native'):
                        cases.append({'id': pair+'-'+arm, 'pair': pair, 'version': arm,
                            'stage': stage, 'side': 'p1' if family == 'prior' else 'p2',
                            'own_team': own, 'enemy_team': enemy, 'opponent': opponent, 'hidden_family': family,
                            'battle_seed': 'sodium,'+hashlib.sha256(('full-game-native-v1:'+pair).encode()).hexdigest(),
                            'opponent_seed': 'full-game-native-v1:'+pair})
    cases = cases[:args.pairs*2]
    sources = ['src/champions_practice/experimental_native_player.py', 'scripts/full_game_native_evaluation.py',
               'src/champions_practice/tactical_consequences.py', 'src/champions_practice/exact_search.py',
               'src/champions_practice/present_rebase.py', 'src/champions_practice/public_origin.py',
               'src/champions_practice/native_speed.py', 'tools/showdown-search-worker.js']
    report = {'cases': cases, 'games': [], 'baseline': policy_identity, 'independent_opponent': identity(dex),
        'source_sha256': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources},
        'team_sha256': {k: hashlib.sha256(v.encode()).hexdigest() for k, v in texts.items()},
        'protocol': {'budget_seconds': 8, 'root_actions': 8, 'responses': 3, 'horizon': 1,
                     'strategic_scores_changed': False},
        'limitations': ['Small synthetic offline sample; no competitive rating.',
            'Fixed own preview 1234; opposing preview and family covary with side.',
            'Opening uses two friendly-family hypotheses; heldout Substitute sets are outside both hypotheses.',
            'Public native admission is bounded and incomplete; unsupported mechanics remain fallbacks.',
            'Upstream opposition lacks Mega augmentation; report adapter fallback-free pairs separately.',
            'Different paths alter RNG consumption; paired results do not establish causal quality of each changed move.',
            'Route diagnostics describe feasibility evidence, not certified winning plans.']}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    with TeamValidationWorker(ROOT, startup_deadline=perf_counter()+60) as validator:
        for text in texts.values():
            for variant in (text, text.replace('Protect', 'Substitute').replace('Life Orb', 'Sitrus Berry')):
                result = validator.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=variant)
                assert result['valid'], result['problems']
    with ShowdownSearchWorker(ROOT, startup_timeout_seconds=60) as live:
        for case in cases:
            game = play(live, case, texts, policy, catalog, dex)
            report['games'].append(game)
            print(case['id'], game['status'], game.get('win'), len(game['rows']), game.get('error', ''), flush=True)
            (args.output/'games.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    report['summary'] = summarize(report['games'])
    report['strata'] = {key: {value: summarize([g for g in report['games'] if g[key] == value])
        for value in sorted({g[key] for g in report['games']})} for key in ('stage', 'opponent', 'hidden_family')}
    (args.output/'games.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    (args.output/'summary.json').write_text(json.dumps({'summary': report['summary'], 'strata': report['strata']}, indent=2)+'\n')
    print(json.dumps(report['summary'], indent=2))
    assert len(report['games']) == len(cases) and all(g['status'] == 'complete' for g in report['games'])


if __name__ == '__main__':
    main()
