"""Post-selection oracle diagnostics across replies and short continuations."""

from dataclasses import asdict
import gzip
import hashlib
import json
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog, observe
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.exact_search import score_exact_summary_breakdown
from champions_practice.independent_opponent import IndependentOpponent, load_dex
from champions_practice.search_worker import ShowdownSearchWorker
from tactical_consequences_evaluation import ROOT, blueprints, frozen_policy, species


def board(summary, side):
    other = 'p2' if side == 'p1' else 'p1'
    return {'score': asdict(score_exact_summary_breakdown(summary, side)),
        'own_survivors': sum(m['hp'] > 0 for m in summary[side]['pokemon']),
        'foe_survivors': sum(m['hp'] > 0 for m in summary[other]['pokemon']),
        'field': summary.get('field', {}), 'ended': summary.get('ended', False)}


def main():
    source = ROOT/'runs/v2-objective/v1/results.json.gz'
    objective = json.loads(gzip.decompress(source.read_bytes()))
    base = json.loads(gzip.decompress((ROOT/'runs/v2-consequences/one-turn/games.json.gz').read_bytes()))
    games = {g['pair']: g for g in base['games']}
    matrices = {m['pair']: m for m in objective['matrices']}
    assigned = {(a['pair'], a['objective']): a for a in objective['assignments']}
    cases = ('development-0-0-p1', 'validation-1-1-p1', 'validation-2-0-p1')
    texts, _ = blueprints()
    catalog, dex = PublicCatalog.load(ROOT), load_dex(ROOT)
    policy, _ = frozen_policy('e0ae723')
    report = {'cases': cases, 'positions': [], 'objective_archive_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'scope': 'Sealed recommendations, actual native states used only afterward for diagnostics. Fixed replies, eight coupled RNG samples, frozen V2 own continuation and independent heuristic enemy continuation. Not opponent probabilities or deployable state inputs.',
        'source_sha256': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
            ('scripts/tactical_objective_continuations.py', 'src/champions_practice/exact_search.py', 'tools/showdown-search-worker.js')}}
    output = ROOT/'runs/v2-objective/continuations-v1'
    output.mkdir(parents=True, exist_ok=True)
    (output/'manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    with ShowdownSearchWorker(ROOT, startup_timeout_seconds=60) as worker:
        for pair in cases:
            game, matrix = games[pair], matrices[pair]
            side, variant = game['side'], game['truth_variant']
            other = 'p2' if side == 'p1' else 'p1'
            own_text, enemy_text = texts[game['own_team']], texts[game['enemy_team']]
            if variant:
                enemy_text = enemy_text.replace('Life Orb', 'Sitrus Berry')
            session = worker.start_session(battle_format=CHAMPIONS_FORMAT,
                p1_team=own_text if side == 'p1' else enemy_text,
                p2_team=enemy_text if side == 'p1' else own_text,
                p1_name='P1', p2_name='P2', seed=game['battle_seed'])['session_id']
            try:
                selection = {side: 'team 1234', other: 'team 1256' if variant else 'team 1234'}
                worker.choose_session(session, p1_choice=selection['p1'], p2_choice=selection['p2'])
                first = game['rows'][0]
                assert worker.session_view(session, side=side)['view'] == first['view']
                choices = list(dict.fromkeys([assigned[pair, name]['action'] for name in
                    ('min', 'risk_50', 'no_position', 'no_hp')]+[first['baseline']]))
                replies = list(matrix['ranking'][0]['worlds'][0]['sampled_responses'])
                if first['enemy_action'] not in replies:
                    replies.append(first['enemy_action'])
                legal_enemy = worker.session_public_choices(session, side=other)
                assert all(a in first['legal_actions'] for a in choices)
                assert all(r in legal_enemy for r in replies)
                # Root choices and response sweep are fixed before this read.
                state = worker.session_snapshot(session)['state']
                previews = {side: species(own_text), other: species(enemy_text)}
                position = {'pair': pair, 'actions': choices, 'replies': replies,
                            'recorded_enemy_reply': first['enemy_action'], 'rows': []}
                for action in choices:
                    for reply in replies:
                        branches = []
                        for sample in range(8):
                            commands = {side: action, other: reply}
                            branches.append({'p1_choice': commands['p1'], 'p2_choice': commands['p2'],
                                'rng_seed': 'sodium,'+hashlib.sha256(f'objective-future:{pair}:{reply}:{sample}:0'.encode()).hexdigest(),
                                'include_state': True})
                        outcomes = worker.branch_many(state=state, branches=branches)
                        for sample, outcome in enumerate(outcomes):
                            current, summary = outcome['state'], outcome['summary']
                            first_turn = board(summary, side) if summary['turn'] >= 2 or summary.get('ended') else None
                            enemy = IndependentOpponent(dex, f'objective-continuation:{pair}:{reply}:{sample}')
                            fallback = False
                            phases = 0
                            while not summary.get('ended') and summary['turn'] < 3 and phases < 6:
                                owned_view = worker.state_view(state=current, side=side, previews=previews)
                                owned_menu = worker.legal_choices(state=current, side=side)
                                decision = policy(observe(owned_view, owned_menu, deadline=perf_counter()+8), catalog)
                                enemy_view = worker.state_view(state=current, side=other, previews=previews)
                                enemy_menu = worker.legal_choices(state=current, side=other)
                                response, trace = enemy.choose(enemy_view, enemy_menu)
                                fallback |= trace['fallback']
                                commands = {side: decision.action, other: response}
                                phases += 1
                                result = worker.branch_many(state=current, branches=[{
                                    'p1_choice': commands['p1'], 'p2_choice': commands['p2'], 'include_state': True,
                                    'rng_seed': 'sodium,'+hashlib.sha256(f'objective-future:{pair}:{reply}:{sample}:{phases}'.encode()).hexdigest()}])[0]
                                current, summary = result['state'], result['summary']
                                if first_turn is None and (summary['turn'] >= 2 or summary.get('ended')):
                                    first_turn = board(summary, side)
                            position['rows'].append({'action': action, 'reply': reply, 'sample': sample,
                                'status': 'complete' if summary.get('ended') or summary['turn'] >= 3 else 'phase-limit',
                                'first_turn': first_turn, 'second_turn': board(summary, side),
                                'opponent_fallback': fallback})
                    print(pair, action, 'diagnosed', flush=True)
                report['positions'].append(position)
                (output/'results.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
            finally:
                worker.close_session(session)
    (output/'results.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    print('Diagnostic samples', sum(len(p['rows']) for p in report['positions']))


if __name__ == '__main__':
    main()
