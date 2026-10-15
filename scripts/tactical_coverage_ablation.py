"""One-turn factorial coverage ablation; frozen hypotheses and position scorer."""

import argparse
from collections import Counter
from dataclasses import replace
import gzip
import hashlib
import json
from pathlib import Path
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog
from champions_practice.independent_opponent import identity, load_dex
from champions_practice.search_worker import HypotheticalSearchWorker, ShowdownSearchWorker
from champions_practice.tactical_consequences import evaluate_consequences
import tactical_consequences_evaluation as driver


ARMS = {
    'candidates': {'root_actions': 16, 'responses': 3},
    'responses': {'root_actions': 8, 'responses': 8},
    'both': {'root_actions': 16, 'responses': 8},
}


def summarize(games):
    result = {}
    for arm in ARMS:
        selected = [g for g in games if g['version'] == arm]
        complete = [g for g in selected if g['status'] == 'complete']
        traces = [g['rows'][0]['tactical'] for g in complete]
        result[arm] = {'statuses': dict(Counter(g['status'] for g in selected)),
            'wins': sum(g['win'] for g in complete), 'games': len(complete),
            'stages': {stage: {'wins': sum(g['win'] for g in complete if g['stage'] == stage),
                               'games': sum(g['stage'] == stage for g in complete)}
                       for stage in ('development', 'validation')},
            'search_statuses': dict(Counter(t['status'] for t in traces)),
            'search_reasons': dict(Counter(t.get('reason', '') for t in traces if t['status'] != 'complete')),
            'max_search_seconds': max((t['elapsed_seconds'] for t in traces), default=0),
            'mean_search_seconds': sum(t['elapsed_seconds'] for t in traces)/max(1, len(traces)),
            'budget_overruns': sum(t['elapsed_seconds'] > 8 for t in traces),
            'opponent_fallbacks': sum(r['enemy_trace']['fallback'] for g in complete for r in g['rows'])}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = driver.ROOT/'runs/v2-consequences/one-turn/games.json.gz'
    raw = source.read_bytes()
    base = json.loads(gzip.decompress(raw))
    texts, _ = driver.blueprints()
    catalog, dex = PublicCatalog.load(driver.ROOT), load_dex(driver.ROOT)
    policy, policy_identity = driver.frozen_policy('e0ae723')
    assert base['opponent_identity'] == identity(dex)
    cases = [{**c, 'id': c['pair']+'-'+arm, 'version': arm}
             for c in base['cases'] for arm in ARMS]
    paths = ['src/champions_practice/tactical_consequences.py', 'src/champions_practice/exact_search.py',
             'src/champions_practice/independent_opponent.py', 'scripts/tactical_consequences_evaluation.py',
             'scripts/tactical_coverage_ablation.py', 'tools/showdown-search-worker.js']
    report = {'cases': cases, 'games': [], 'arms': ARMS, 'horizon_turns': 1,
        'control_archive_sha256': hashlib.sha256(raw).hexdigest(), 'control_archive': str(source),
        'opponent_identity': identity(dex), 'incumbent': policy_identity,
        'source_sha256': {p: hashlib.sha256((driver.ROOT/p).read_bytes()).hexdigest() for p in paths},
        'team_sha256': {k: hashlib.sha256(v.encode()).hexdigest() for k, v in texts.items()},
        'limitations': ['Same previously examined 24 cases, correlated side reversals; a diagnostic ablation, not fresh validation.',
            'Opening intervention only; later actions use frozen PR249.',
            'Same two friendly-family hypotheses, RNG sample, scorer and eight-second deadline.',
            'Candidate expansion changes the root cap; replacement own-choice cap remains two.',
            'Response expansion applies at the root and intervening replacement/pivot phases.',
            'Deadline/branch/phase failures retain V2; report these separately from completed search.']}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    with ShowdownSearchWorker(driver.ROOT, startup_timeout_seconds=60) as live, HypotheticalSearchWorker(driver.ROOT, startup_deadline=perf_counter()+60) as hypothetical:
        for case in cases:
            config = ARMS[case['version']]
            def evaluate(*args, **kwargs):
                kwargs['limits'] = replace(kwargs['limits'], **config)
                return evaluate_consequences(*args, **kwargs, horizon_turns=1)
            driver.evaluate_consequences = evaluate
            game = driver.play(live, hypothetical, {**case, 'version': 'consequences'}, texts, policy, catalog, dex)
            game['version'] = case['version']
            report['games'].append(game)
            trace = game['rows'][0]['tactical'] if game['rows'] else None
            print(case['id'], game['status'], game.get('win'),
                  (trace['status'], trace.get('reason'), round(trace['elapsed_seconds'], 2)) if trace else '', flush=True)
            (args.output/'games.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    report['summary'] = summarize(report['games'])
    (args.output/'games.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    (args.output/'summary.json').write_text(json.dumps(report['summary'], indent=2)+'\n')
    print(json.dumps(report['summary'], indent=2))
    assert len(report['games']) == len(cases) and all(g['status'] == 'complete' for g in report['games'])


if __name__ == '__main__':
    main()
