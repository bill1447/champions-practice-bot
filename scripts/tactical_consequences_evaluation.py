"""Opening intervention trials: public hypotheses, native two-turn consequences.

All later choices use frozen PR249. This measures an opening prototype, not a
new full-game policy. The evaluator never receives the live battle worker.
"""

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog, observe
from champions_practice.agent_v2.policy import ident
from champions_practice.belief_search import ExactBeliefWorldState
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.diversity_league import team_text
from champions_practice.independent_opponent import IndependentOpponent, identity, load_dex
from champions_practice.search_worker import HypotheticalSearchWorker, ShowdownSearchWorker, TeamValidationWorker
from champions_practice.tactical_consequences import TacticalLimits, evaluate_consequences, observation_key
from independent_opponent_evaluation import ROOT, frozen_policy, teams


def blueprints():
    original = teams()
    fresh_rosters = {
        'rain-support': ('Pelipper', 'Basculegion', 'Archaludon', 'Indeedee-F', 'Venusaur', 'Metagross'),
        'ground-grass': ('Garchomp', 'Rillaboom', 'Dragonite', 'Incineroar', 'Rotom-Wash', 'Metagross'),
        'psychic-balance': ('Gardevoir', 'Indeedee-F', 'Rotom-Wash', 'Metagross', 'Venusaur', 'Armarouge'),
        'sand-dragon': ('Excadrill', 'Tyranitar', 'Dragonite', 'Garchomp', 'Incineroar', 'Rotom-Wash'),
        'armarouge-pivot': ('Indeedee-F', 'Armarouge', 'Incineroar', 'Venusaur', 'Metagross', 'Gardevoir'),
        'grass-water': ('Rillaboom', 'Rotom-Wash', 'Pelipper', 'Garchomp', 'Metagross', 'Incineroar'),
    }
    texts = {**original, **{k: team_text(v).replace('Stomping Tantrum', 'Earthquake') for k, v in fresh_rosters.items()}}
    return texts, {
        'development': [('psychic-room', 'sand-pivot'), ('armarouge-support', 'grass-balance'), ('ground-pivot', 'rain-grass')],
        'validation': [('ground-grass', 'rain-support'), ('psychic-balance', 'sand-dragon'), ('armarouge-pivot', 'grass-water')],
    }


def species(text):
    return [chunk.splitlines()[0].split(' @ ')[0].removesuffix(' (M)').removesuffix(' (F)')
            for chunk in text.strip().split('\n\n')]


def owned_genders(text, view):
    known = {}
    for mon in view['request']['side']['pokemon']:
        details = mon['details'].split(', ')
        known[ident(details[0])] = next((v for v in details[1:] if v in ('M', 'F')), None)
    chunks = []
    for chunk in text.strip().split('\n\n'):
        lines = chunk.splitlines()
        name, *item = lines[0].split(' @ ')
        gender = known.get(ident(name))
        if gender:
            lines[0] = name+f' ({gender})'+(' @ '+item[0] if item else '')
        chunks.append('\n'.join(lines))
    return '\n\n'.join(chunks)+'\n'


class PublicPreviewWorker:
    """Attach observed full preview to hypothetical selected-four states."""
    def __init__(self, worker, previews):
        self.worker, self.previews = worker, previews

    def state_view(self, *, state, side):
        return self.worker.state_view(state=state, side=side, previews=self.previews)

    def legal_choices(self, **kwargs):
        return self.worker.legal_choices(**kwargs)

    def branch_many(self, **kwargs):
        return self.worker.branch_many(**kwargs)


def opening(worker, case, own_text, public_priors, view, legal, incumbent, catalog):
    start = perf_counter()
    deadline = start+8
    side = case['side']
    other = 'p2' if side == 'p1' else 'p1'
    own_text = owned_genders(own_text, view)
    scoped = PublicPreviewWorker(worker, {side: species(own_text), other: view['opponent']['preview_species']})
    roots = []
    key = observation_key(view)
    # Bench selection and held item differ across explicit set hypotheses. No
    # actual enemy team, command, battle seed or live snapshot is read here.
    for hypothesis in range(2):
        candidate = public_priors.replace('Life Orb', 'Sitrus Berry') if hypothesis else public_priors
        for sample in range(16):
            if perf_counter() >= deadline:
                return incumbent, {'status': 'incomplete', 'reason': 'opening conditioning deadline',
                                   'admitted_worlds': len(roots), 'elapsed_seconds': perf_counter()-start}
            arguments = {'p1_team': own_text if side == 'p1' else candidate,
                         'p2_team': candidate if side == 'p1' else own_text,
                         'p1_preview': 'team 1234' if side == 'p1' else ('team 1234' if hypothesis == 0 else 'team 1256'),
                         'p2_preview': ('team 1234' if hypothesis == 0 else 'team 1256') if side == 'p1' else 'team 1234'}
            state = worker.create_state(battle_format=CHAMPIONS_FORMAT, **arguments,
                p1_name='P1', p2_name='P2', seed='sodium,'+hashlib.sha256(f'public-root:{hypothesis}:{sample}'.encode()).hexdigest())
            if observation_key(scoped.state_view(state=state, side=side)) == key:
                roots.append(ExactBeliefWorldState(state, 1, f'public-prior-{hypothesis}'))
                break
    if len(roots) != 2:
        return incumbent, {'status': 'unavailable', 'reason': 'public opening conditioning rejected a hypothesis',
                           'admitted_worlds': len(roots), 'elapsed_seconds': perf_counter()-start}
    result = evaluate_consequences(scoped, worlds=tuple(roots), side=side,
        authoritative_actions=legal, incumbent=incumbent, catalog=catalog, deadline=deadline,
        limits=TacticalLimits(root_actions=8, responses=3, next_actions=2))
    trace = asdict(result)
    trace['admitted_worlds'] = len(roots)
    trace['elapsed_seconds'] = perf_counter()-start
    return result.action, trace


def play(live, hypothetical, case, texts, policy, catalog, dex):
    side = case['side']
    other = 'p2' if side == 'p1' else 'p1'
    enemy = IndependentOpponent(dex, case['opponent_seed'])
    own_text, prior = texts[case['own_team']], texts[case['enemy_team']]
    # The actual hidden selection/item is supplied only to the live driver.
    # Both paired variants face the same truth, independently of hypothesis RNG.
    actual = prior.replace('Life Orb', 'Sitrus Berry') if case['truth_variant'] else prior
    session = live.start_session(battle_format=CHAMPIONS_FORMAT,
        p1_team=own_text if side == 'p1' else actual, p2_team=actual if side == 'p1' else own_text,
        p1_name='P1', p2_name='P2', seed=case['battle_seed'])['session_id']
    rows = []
    try:
        selection = {side: 'team 1234', other: 'team 1256' if case['truth_variant'] else 'team 1234'}
        live.choose_session(session, p1_choice=selection['p1'], p2_choice=selection['p2'])
        for checkpoint in range(120):
            view = live.session_view(session, side=side)['view']
            if view['ended']:
                return {**case, 'status': 'complete', 'win': view['winner'] == side.upper(), 'winner': view['winner'], 'rows': rows}
            menu = live.session_public_choices(session, side=side)
            decision = policy(observe(view, menu, deadline=perf_counter()+8), catalog)
            action, trace = decision.action, None
            if checkpoint == 0 and case['version'] == 'consequences':
                # Only public input and OWN team cross into the decision helper.
                action, trace = opening(hypothetical, {'side': side}, own_text, prior,
                                        view, menu, action, catalog)
            enemy_view = live.session_view(session, side=other)['view']
            enemy_menu = live.session_public_choices(session, side=other)
            reply, enemy_trace = enemy.choose(enemy_view, enemy_menu)
            assert action in menu and reply in enemy_menu
            rows.append({'turn': view['turn'], 'action': action, 'baseline': decision.action,
                'view': view, 'legal_actions': menu, 'tactical': trace,
                'enemy_action': reply, 'enemy_trace': enemy_trace})
            commands = {side: action, other: reply}
            live.choose_session(session, p1_choice=commands['p1'], p2_choice=commands['p2'])
        return {**case, 'status': 'incomplete', 'rows': rows}
    except Exception as error:
        return {**case, 'status': 'failed', 'error_type': type(error).__name__, 'error': str(error), 'rows': rows}
    finally:
        live.close_session(session)


def summarize(games):
    groups = defaultdict(dict)
    for g in games:
        groups[g['pair']][g['version']] = g
    valid = [p for p in groups.values() if set(p) == {'incumbent', 'consequences'} and
             all(g['status'] == 'complete' for g in p.values())]
    clean = [p for p in valid if not any(r['enemy_trace']['fallback'] for g in p.values() for r in g['rows'])]
    result = {'statuses': dict(Counter(g['status'] for g in games))}
    for label, pairs in [('all', valid), ('fallback_free', clean)]:
        result[label] = {'pairs': len(pairs), 'incumbent_wins': sum(p['incumbent']['win'] for p in pairs),
            'consequences_wins': sum(p['consequences']['win'] for p in pairs),
            'consequences_only': sum(p['consequences']['win'] and not p['incumbent']['win'] for p in pairs),
            'incumbent_only': sum(p['incumbent']['win'] and not p['consequences']['win'] for p in pairs)}
    traces = [p['consequences']['rows'][0]['tactical'] for p in valid]
    result['search_status'] = dict(Counter(t['status'] for t in traces))
    result['search_reasons'] = dict(Counter(t.get('reason', '') for t in traces if t['status'] != 'complete'))
    result['opening_changes'] = sum(p['consequences']['rows'][0]['action'] != p['incumbent']['rows'][0]['action'] for p in valid)
    result['search_overruns'] = sum(t['elapsed_seconds'] > 8 for t in traces)
    result['max_search_seconds'] = max((t['elapsed_seconds'] for t in traces), default=0)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seeds', type=int, default=2)
    args = parser.parse_args()
    assert 1 <= args.seeds <= 4
    texts, matchups = blueprints()
    policy, policy_identity = frozen_policy('e0ae723')
    catalog, dex = PublicCatalog.load(ROOT), load_dex(ROOT)
    cases = []
    for stage, pairs in matchups.items():
        for matchup, (own, enemy) in enumerate(pairs):
            for seed in range(args.seeds):
                mirror = f'{stage}-{matchup}-{seed}'
                for side in ('p1', 'p2'):
                    pair = mirror+'-'+side
                    for version in ('incumbent', 'consequences'):
                        cases.append({'id': pair+'-'+version, 'pair': pair, 'mirror_group': mirror,
                            'stage': stage, 'own_team': own, 'enemy_team': enemy, 'side': side, 'version': version,
                            'truth_variant': seed % 2,
                            'battle_seed': 'sodium,'+hashlib.sha256(('tactical-truth-v1:'+mirror).encode()).hexdigest(),
                            'opponent_seed': 'tactical-enemy-v1:'+mirror})
    sources = ['src/champions_practice/tactical_consequences.py', 'src/champions_practice/exact_search.py',
               'scripts/tactical_consequences_evaluation.py', 'tools/showdown-search-worker.js']
    report = {'cases': cases, 'games': [], 'incumbent': policy_identity, 'opponent': identity(dex),
        'source_sha256': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources},
        'team_sha256': {k: hashlib.sha256(v.encode()).hexdigest() for k, v in texts.items()},
        'limitations': ['Opening intervention only; all later actions use frozen V2.',
            'Two explicit static set/bench hypotheses; true set drawn from that family. Not a calibrated or broad prior.',
            'Observed gender/own stats and public opening events condition hypotheses; no live snapshots or RNG enter policy.',
            'Eight-second total opening budget; incomplete comparisons retain incumbent.',
            'Familiar species; validation compositions and live RNG frozen before running either stage.',
            'Mirrored outcomes are correlated; this is not a competitive rating.']}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    with TeamValidationWorker(ROOT, startup_deadline=perf_counter()+60) as validator:
        for text in texts.values():
            for variant in (text, text.replace('Life Orb', 'Sitrus Berry')):
                result = validator.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=variant)
                assert result['valid'], result['problems']
    with ShowdownSearchWorker(ROOT, startup_timeout_seconds=60) as live, HypotheticalSearchWorker(ROOT, startup_deadline=perf_counter()+60) as hypothetical:
        for case in cases:
            game = play(live, hypothetical, case, texts, policy, catalog, dex)
            report['games'].append(game)
            trace = game['rows'][0].get('tactical') if game['rows'] else None
            print(case['id'], game['status'], game.get('win'),
                  (trace['status'], trace.get('reason'), round(trace['elapsed_seconds'], 2)) if trace else '', flush=True)
            (args.output/'games.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    report['summary'] = {s: summarize([g for g in report['games'] if g['stage'] == s]) for s in matchups}
    (args.output/'games.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    (args.output/'summary.json').write_text(json.dumps(report['summary'], indent=2)+'\n')
    print(json.dumps(report['summary'], indent=2))
    if any(g['status'] != 'complete' for g in report['games']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
