"""Public-only turn-two admission/decision probe using existing belief engine.

This is a position coverage audit, not a midgame intervention win-rate trial.
"""

from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import gzip
import hashlib
import json
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog, observe
from champions_practice.belief_controller import BeliefDecision, BeliefDecisionEngine
from champions_practice.belief_search import ExactBeliefWorldState
from champions_practice.competitive_evaluation import canonical_view
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.diversity_league import catalog as public_priors
from champions_practice.search_worker import HypotheticalSearchWorker
from champions_practice.tactical_consequences import TacticalLimits, evaluate_consequences, observation_key
from champions_practice.present_rebase import _first_public_difference, _positive_mechanics_rejection
from champions_practice.public_origin import PublicOriginWorker
from champions_practice.plan_feasibility import compare_routes
from tactical_consequences_evaluation import ROOT, PublicPreviewWorker, blueprints, frozen_policy, species


def main():
    archives = {'familiar': 'runs/v2-consequences/one-turn/games.json.gz',
                'unfamiliar': 'runs/v2-coverage/unfamiliar-v1/games.json.gz'}
    cases, games = [], {}
    for family, path in archives.items():
        report = json.loads(gzip.decompress((ROOT/path).read_bytes()))
        for game in report['games']:
            if game['version'] != 'one_turn' or game['side'] != 'p1' or '-1-p1' in game['pair']:
                continue
            target = next((i for i, r in enumerate(game['rows']) if r['view']['turn'] >= 2 and r['view']['phase'] == 'move'), None)
            case_id = family+':'+game['id']
            cases.append({'id': case_id, 'family': family, 'game': game['id'], 'checkpoint': target,
                          'archive': path, 'archive_sha256': hashlib.sha256((ROOT/path).read_bytes()).hexdigest()})
            games[case_id] = game
    assert len(cases) == 12
    texts, _ = blueprints()
    metadata = PublicCatalog.load(ROOT)
    policy, _ = frozen_policy('e0ae723')
    paths = ['scripts/midgame_admission_probe.py', 'src/champions_practice/belief_controller.py',
             'src/champions_practice/present_rebase.py', 'src/champions_practice/tactical_consequences.py',
             'src/champions_practice/present_mechanics.py', 'src/champions_practice/persistent_support.py',
             'src/champions_practice/search_worker.py', 'tools/showdown-search-worker.js']
    paths.append('src/champions_practice/public_origin.py')
    paths.append('src/champions_practice/plan_feasibility.py')
    report = {'cases': cases, 'positions': [],
        'source_sha256': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},
        'scope': 'One first turn-two move checkpoint per seed-zero p1 game; known OWN actions and public observations only. No enemy command, seed or live snapshot supplied to belief engine or tactical policy.',
        'limitations': ['Bounded current-fact and lifecycle support; remaining persistent domains stay closed.',
            'Eight-second existing admission/search preparation plus separate eight-second tactical diagnostic budget; not a deployment latency result.',
            'This tests early midgame availability/decisions, not full-game strength or later-turn generalization.']}
    output = ROOT/'runs/v2-midgame-admission/v9'
    output.mkdir(parents=True, exist_ok=True)
    (output/'manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    with HypotheticalSearchWorker(ROOT, startup_deadline=perf_counter()+60) as worker:
        for case in cases:
            if case['checkpoint'] is None:
                report['positions'].append({**case, 'status': 'no-target-position'})
                continue
            game = games[case['id']]
            engine = BeliefDecisionEngine(ROOT, battle_format=CHAMPIONS_FORMAT,
                ai_team=texts[game['own_team']], opponent_priors=public_priors(), world_limit=2,
                max_particles=2, candidate_limit=2, response_limit=2, strategic_plan_limit=1,
                decision_budget_seconds=8, conditioning_budget_seconds=8, particle_seed=63101)
            try:
                start = perf_counter()
                engine.initialize_preview(view=canonical_view(game['rows'][0]['view'], 'p1'), ai_choice='team 1234')
                for index in range(case['checkpoint']):
                    known_action = game['rows'][index]['action']
                    decision = BeliefDecision(known_action, 'recorded-own-choice', len(engine.particles), 1, 0, 0)
                    engine.observe_public_turn(decision=decision, view=canonical_view(game['rows'][index+1]['view'], 'p1'))
                row = game['rows'][case['checkpoint']]
                current = canonical_view(row['view'], 'p1')
                prepared = engine.choose_ai_action(legal_live=row['legal_actions'])
                entry = {**case, 'turn': current['turn'], 'preparation_seconds': perf_counter()-start,
                    'production_mode': prepared.mode, 'production_fallback_reason': prepared.fallback_reason,
                    'native_admission': engine.last_native_admission, 'admitted_particles': len(engine.particles)}
                if not engine.particles:
                    entry['status'] = 'unavailable'
                else:
                    worlds = tuple(ExactBeliefWorldState(p.state, p.weight, p.world_id or str(i))
                                   for i, p in enumerate(engine.particles))
                    incumbent = policy(observe(current, row['legal_actions'], deadline=perf_counter()+8), metadata).action
                    scoped = PublicPreviewWorker(worker, {'p1': current['opponent']['preview_species'],
                                                         'p2': species(texts[game['own_team']])})
                    root_views = [scoped.state_view(state=p.state, side='p2') for p in engine.particles]
                    entry['root_information_difference'] = _first_public_difference(
                        json.loads(observation_key(root_views[0])), json.loads(observation_key(root_views[-1])), '$')
                    entry['root_vs_authoritative_differences'] = [_first_public_difference(
                        json.loads(observation_key(projected)), json.loads(observation_key(current)), '$')
                        for projected in root_views]
                    entry['negative_controls'] = []
                    for particle, projected in zip(engine.particles, root_views, strict=True):
                        menu = scoped.legal_choices(state=particle.state, side='p2')
                        def rejection(state):
                            return _positive_mechanics_rejection(state, projected, current_view=current,
                                ledger=engine.public_constraint_ledger, legal_live=tuple(row['legal_actions']), hypothetical_legal=menu)
                        assert rejection(particle.state) is None
                        for side_index, side in enumerate(particle.state['sides']):
                            for index, mon in enumerate(side['pokemon']):
                                if mon['isActive']:
                                    continue
                                if any(move.lower().replace(' ', '') == 'stompingtantrum' for move in mon['set']['moves']):
                                    bad = deepcopy(particle.state)
                                    bad['sides'][side_index]['pokemon'][index]['moveLastTurnResult'] = False
                                    reason = rejection(bad)
                                    assert reason == 'unsupported-persistent:inactive-last-move-result', reason
                                    entry['negative_controls'].append('inactive-last-result-corruption-rejected')
                                if side_index == 1 and mon['ability'] == 'unburden':
                                    bad = deepcopy(particle.state)
                                    bad['sides'][side_index]['pokemon'][index]['volatiles']['unburden'] = {}
                                    reason = rejection(bad)
                                    assert reason == 'unsupported-persistent:native-volatile', reason
                                    entry['negative_controls'].append('inactive-unburden-corruption-rejected')
                    public_worker = PublicOriginWorker(worker, states=[p.state for p in engine.particles],
                        current_view=current, ledger=engine.public_constraint_ledger,
                        previews={'p1': current['opponent']['preview_species'], 'p2': species(texts[game['own_team']])},
                        legal_actions=row['legal_actions'])
                    tampered = deepcopy(current)
                    tampered['opponent']['active'][0]['hp_percent'] = 99 if current['opponent']['active'][0]['hp_percent'] == 100 else 100
                    try:
                        PublicOriginWorker(worker, states=[worlds[0].state], current_view=tampered,
                            ledger=engine.public_constraint_ledger, previews=public_worker.previews,
                            legal_actions=row['legal_actions'])
                    except ValueError:
                        pass
                    else:
                        raise AssertionError('public origin accepted a modified source observation')
                    entry['projected_root_differences'] = [_first_public_difference(
                        json.loads(observation_key(public_worker.state_view(state=p.state, side='p2'))),
                        json.loads(observation_key(current)), '$') for p in engine.particles]
                    assert not any(entry['projected_root_differences']), entry['projected_root_differences']
                    probe_reply = public_worker.legal_choices(state=worlds[0].state, side='p1')[0]
                    probe = public_worker.branch_many(state=worlds[0].state, branches=[{
                        'p1_choice': probe_reply, 'p2_choice': incumbent, 'include_state': True,
                        'rng_seed': 'sodium,'+'12345678'*8}])[0]
                    after = public_worker.state_view(state=probe['state'], side='p2')
                    assert after['public_event_delta']['turn'] == current['turn']
                    assert not any('splash' in mon['moves'] for mon in after['opponent']['revealed'])
                    entry['public_origin_controls'] = ['exact-authoritative-root', 'parent-state-unchanged',
                        'next-native-events-current-turn', 'no-constructor-splash-revelation',
                        'modified-source-observation-rejected']
                    result = evaluate_consequences(public_worker, worlds=worlds, side='p2',
                        authoritative_actions=row['legal_actions'], incumbent=incumbent,
                        catalog=metadata, deadline=perf_counter()+8, horizon_turns=1, include_leaf_positions=True,
                        limits=TacticalLimits(root_actions=8, responses=3, next_actions=2))
                    entry.update(status=result.status, tactical=asdict(result), incumbent=incumbent)
                    if result.status == 'complete':
                        entry['plan_requirements'] = compare_routes(result.ranking, current, metadata, side='p2')
                report['positions'].append(entry)
                print(case['id'], entry['status'], entry['admitted_particles'], entry['production_fallback_reason'], flush=True)
            except Exception as error:
                report['positions'].append({**case, 'status': 'failed', 'error_type': type(error).__name__, 'error': str(error)})
                print(case['id'], 'failed', type(error).__name__, flush=True)
            (output/'positions.json').write_text(json.dumps(report, indent=2)+'\n')
    report['summary'] = {family: dict(Counter(p['status'] for p in report['positions'] if p['family'] == family)) for family in archives}
    (output/'positions.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report['summary'], indent=2))


if __name__ == '__main__':
    main()
