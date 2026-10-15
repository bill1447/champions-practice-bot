"""Fixed-branch root-objective sensitivity and paired opening rollouts."""

from dataclasses import asdict
import gzip
import hashlib
import json
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog
from champions_practice.independent_opponent import identity, load_dex
from champions_practice.search_worker import HypotheticalSearchWorker, ShowdownSearchWorker
from champions_practice.tactical_consequences import evaluate_consequences
from champions_practice.tactical_objective import OBJECTIVES, rerank
import tactical_consequences_evaluation as driver


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strip_telemetry(ranking):
    result = json.loads(json.dumps(ranking))
    for candidate in result:
        for world in candidate['worlds']:
            for response in world['sampled_responses'].values():
                response.pop('leaf_breakdown', None)
    return result


def main():
    output = driver.ROOT/'runs/v2-objective/v1'
    output.mkdir(parents=True, exist_ok=True)
    base_path = driver.ROOT/'runs/v2-consequences/one-turn/games.json.gz'
    base = json.loads(gzip.decompress(base_path.read_bytes()))
    texts, _ = driver.blueprints()
    catalog, dex = PublicCatalog.load(driver.ROOT), load_dex(driver.ROOT)
    policy, _ = driver.frozen_policy('e0ae723')
    paths = ['src/champions_practice/tactical_objective.py', 'src/champions_practice/tactical_consequences.py',
             'src/champions_practice/exact_search.py', 'scripts/tactical_objective_experiment.py',
             'scripts/tactical_consequences_evaluation.py', 'tools/showdown-search-worker.js']
    report = {'cases': base['cases'], 'matrices': [], 'assignments': [], 'new_games': [],
        'objectives': [asdict(o) for o in OBJECTIVES], 'primary_risk_control': 'risk_50',
        'base_archive_sha256': digest(base_path), 'opponent_identity': identity(dex),
        'source_sha256': {p: digest(driver.ROOT/p) for p in paths},
        'scope': 'Root-only sensitivity. All native branches, RNG, scorer and subordinate replacement continuations are held fixed. Equal scenario means are not opponent probabilities.',
        'limitations': ['Same examined 24 cases; no parameter selected for deployment from these results.',
            'Leaf-component ablations and hidden-world averaging are separate from response-risk controls.',
            'All later actions use frozen PR249; identical case/action rollouts are reused and never counted as independent games.']}
    (output/'manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    driver.evaluate_consequences = lambda *a, **kw: evaluate_consequences(*a, **kw, horizon_turns=1)
    with HypotheticalSearchWorker(driver.ROOT, startup_deadline=perf_counter()+60) as worker:
        for game in base['games']:
            row = game['rows'][0]
            action, trace = driver.opening(worker, {'side': game['side']}, texts[game['own_team']],
                texts[game['enemy_team']], row['view'], row['legal_actions'], row['baseline'], catalog)
            assert trace['status'] == 'complete' and action == row['action']
            assert trace['branch_count'] == row['tactical']['branch_count']
            assert strip_telemetry(trace['ranking']) == row['tactical']['ranking']
            for candidate in trace['ranking']:
                for world in candidate['worlds']:
                    for sample in world['sampled_responses'].values():
                        parts = sample['leaf_breakdown']
                        assert abs(parts['total']-sample['leaf_utility']) < 1e-7
                        assert abs(parts['total']-sum(parts[k] for k in ('terminal', 'material', 'position', 'speed'))) < 1e-7
                        assert abs(parts['material']-sum(parts[k] for k in ('living', 'hp', 'status'))) < 1e-7
            report['matrices'].append({'pair': game['pair'], 'case': game['id'],
                                       'ranking': trace['ranking'], 'branch_count': trace['branch_count']})
            print('matrix', game['pair'], 'unchanged', trace['branch_count'], flush=True)
    assert digest(driver.ROOT/'tools/showdown-search-worker.js') == report['source_sha256']['tools/showdown-search-worker.js']
    (output/'matrices.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    # Known deterministic rollouts may be reused only for an identical case and
    # root command. Different objectives choosing that command are not new games.
    bank, provenance = {}, {}
    for relative in ('runs/v2-consequences/one-turn/games.json.gz',
                     'runs/v2-consequences/v2/games.json.gz', 'runs/v2-coverage/v1/games.json.gz'):
        path = driver.ROOT/relative
        archive = json.loads(gzip.decompress(path.read_bytes()))
        provenance[relative] = digest(path)
        for game in archive['games']:
            if game['status'] != 'complete':
                continue
            key = (game['pair'], game['rows'][0]['action'])
            if key in bank:
                assert bank[key][0]['winner'] == game['winner']
            else:
                bank[key] = (game, {'archive': relative, 'game': game['id']})
    report['reference_archives'] = provenance
    schedule = []
    base_games = {g['pair']: g for g in base['games']}
    for matrix in report['matrices']:
        game = base_games[matrix['pair']]
        for objective in OBJECTIVES:
            ranking = rerank(matrix['ranking'], objective)
            action = ranking[0]['action']
            assert action in game['rows'][0]['legal_actions']
            if objective.name == 'min':
                assert action == game['rows'][0]['action']
            assignment = {'pair': game['pair'], 'objective': objective.name, 'action': action,
                          'ranking': ranking}
            report['assignments'].append(assignment)
            key = (game['pair'], action)
            if key not in bank and key not in schedule:
                schedule.append(key)
    report['schedule'] = [{'pair': pair, 'action': action} for pair, action in schedule]
    (output/'rollout-manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    with ShowdownSearchWorker(driver.ROOT, startup_timeout_seconds=60) as live:
        for pair, action in schedule:
            original = base_games[pair]
            case = {k: original[k] for k in base['cases'][0]}
            case.update(id=pair+'-fixed-'+hashlib.sha256(action.encode()).hexdigest()[:10], version='consequences')
            def fixed_opening(_worker, _case, _own, _prior, view, legal, _incumbent, _catalog):
                assert view == original['rows'][0]['view'] and action in legal
                return action, {'status': 'fixed-matrix-selection', 'matrix_pair': pair}
            driver.opening = fixed_opening
            result = driver.play(live, None, case, texts, policy, catalog, dex)
            assert result['status'] == 'complete', result
            report['new_games'].append(result)
            bank[(pair, action)] = (result, {'archive': 'new_games', 'game': result['id']})
            print('rollout', pair, action, result['win'], flush=True)
            (output/'results.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    for assignment in report['assignments']:
        game, ref = bank[assignment['pair'], assignment['action']]
        assignment.update(win=game['win'], fallback=any(r['enemy_trace']['fallback'] for r in game['rows']),
                          result_ref=ref)
    control = {a['pair']: a for a in report['assignments'] if a['objective'] == 'min'}
    report['summary'] = {}
    for objective in OBJECTIVES:
        chosen = [a for a in report['assignments'] if a['objective'] == objective.name]
        clean = [a for a in chosen if not a['fallback'] and not control[a['pair']]['fallback']]
        report['summary'][objective.name] = {'games': len(chosen), 'wins': sum(a['win'] for a in chosen),
            'changed_actions': sum(a['action'] != control[a['pair']]['action'] for a in chosen),
            'candidate_only': sum(a['win'] and not control[a['pair']]['win'] for a in chosen),
            'control_only': sum(control[a['pair']]['win'] and not a['win'] for a in chosen),
            'fallback_free': {'pairs': len(clean), 'control_wins': sum(control[a['pair']]['win'] for a in clean),
                              'candidate_wins': sum(a['win'] for a in clean)}}
    (output/'results.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    (output/'summary.json').write_text(json.dumps(report['summary'], indent=2)+'\n')
    print(json.dumps(report['summary'], indent=2))


if __name__ == '__main__':
    main()
