"""Paired opening interventions: frozen legacy native scorer versus speed contract fix."""

import gzip
import hashlib
import importlib.util
import json
import subprocess
import sys
from time import perf_counter
import types

from champions_practice.agent_v2 import PublicCatalog
from champions_practice.independent_opponent import load_dex
from champions_practice.search_worker import HypotheticalSearchWorker, ShowdownSearchWorker
import champions_practice.tactical_consequences as tactical
import tactical_consequences_evaluation as driver


def main():
    root = driver.ROOT
    base_path = root/'runs/v2-consequences/one-turn/games.json.gz'
    base = json.loads(gzip.decompress(base_path.read_bytes()))
    old_source = subprocess.run(['git', 'show', 'dbb1027:src/champions_practice/exact_search.py'],
                                cwd=root, capture_output=True, text=True, check=True).stdout
    legacy = types.ModuleType('_speed_contract_legacy')
    legacy.__spec__ = importlib.util.spec_from_loader(legacy.__name__, loader=None)
    sys.modules[legacy.__name__] = legacy
    exec(compile(old_source, 'dbb1027:exact_search.py', 'exec'), legacy.__dict__)
    fixed = tactical.score_exact_summary_breakdown
    original_opening = driver.opening
    driver.evaluate_consequences = lambda *args, **kwargs: tactical.evaluate_consequences(*args, **kwargs, horizon_turns=1)
    texts, _ = driver.blueprints()
    policy, _ = driver.frozen_policy('e0ae723')
    metadata, dex = PublicCatalog.load(root), load_dex(root)
    output = root/'runs/v2-speed-contract/gameplay-v1'
    output.mkdir(parents=True, exist_ok=True)
    fresh_matchups = [('psychic-room', 'rain-grass'), ('psychic-balance', 'grass-water'),
                      ('armarouge-support', 'sand-pivot'), ('armarouge-pivot', 'sand-dragon'),
                      ('ground-pivot', 'grass-balance'), ('ground-grass', 'grass-water')]
    fresh = []
    for index, (own, enemy) in enumerate(fresh_matchups):
        for variant in range(2):
            for side in ('p1', 'p2'):
                mirror = f'speed-heldout-{index}-{variant}'
                fresh.append({'pair': mirror+'-'+side, 'mirror_group': mirror, 'own_team': own,
                    'enemy_team': enemy, 'side': side, 'version': 'consequences', 'truth_variant': variant,
                    'battle_seed': 'sodium,'+hashlib.sha256(('speed-truth-v1:'+mirror).encode()).hexdigest(),
                    'opponent_seed': 'speed-enemy-v1:'+mirror})
    report = {'control_ref': 'dbb1027', 'legacy_scorer_sha256': hashlib.sha256(old_source.encode()).hexdigest(),
        'retained_archive_sha256': hashlib.sha256(base_path.read_bytes()).hexdigest(), 'fresh_cases': fresh,
        'pairs': [], 'scope': 'Opening-only native 8/3, one turn. Legacy native scorer reads preserved cached speed; corrected scorer reads effectiveSpeed. Same native mechanics, candidates, responses, world proposals and RNG. All later own actions frozen e0ae723 V2. No strategic labels or weight changes.',
        'source_sha256': {p: hashlib.sha256((root/p).read_bytes()).hexdigest() for p in (
            'scripts/speed_contract_gameplay.py', 'scripts/tactical_consequences_evaluation.py',
            'src/champions_practice/exact_search.py', 'src/champions_practice/native_speed.py',
            'src/champions_practice/strategy_evidence.py', 'src/champions_practice/tactical_consequences.py',
            'tools/showdown-search-worker.js')}}
    (output/'manifest.json').write_text(json.dumps(report, indent=2)+'\n')

    def save():
        (output/'games.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))

    with HypotheticalSearchWorker(root, startup_deadline=perf_counter()+60) as hypothetical, \
            ShowdownSearchWorker(root, startup_timeout_seconds=60) as live:
        for game in base['games']:
            row = game['rows'][0]
            traces = {}
            for arm, scorer in (('control', legacy.score_exact_summary_breakdown), ('candidate', fixed)):
                tactical.score_exact_summary_breakdown = scorer
                action, trace = original_opening(hypothetical, {'side': game['side']}, texts[game['own_team']],
                    texts[game['enemy_team']], row['view'], row['legal_actions'], row['baseline'], metadata)
                assert trace['status'] == 'complete', trace
                traces[arm] = (action, trace)
            assert traces['control'][0] == row['action']
            assert traces['control'][1]['branch_count'] == row['tactical']['branch_count']
            stripped = json.loads(json.dumps(traces['control'][1]['ranking']))
            for candidate in stripped:
                for world in candidate['worlds']:
                    for sample in world['sampled_responses'].values():
                        sample.pop('leaf_breakdown', None)
            assert stripped == row['tactical']['ranking']
            action, trace = traces['candidate']
            if action == row['action']:
                candidate_game = game
            else:
                def fixed_opening(_worker, _case, _own, _prior, view, legal, _incumbent, _catalog):
                    assert view == row['view'] and action in legal
                    return action, trace
                driver.opening = fixed_opening
                case = {k: game[k] for k in base['cases'][0]}
                case.update(id=game['pair']+'-speed-fixed', version='consequences')
                candidate_game = driver.play(live, None, case, texts, policy, metadata, dex)
                assert candidate_game['status'] == 'complete', candidate_game
            report['pairs'].append({'pair': game['pair'], 'stage': 'retained', 'control': game,
                'candidate': candidate_game, 'reused_identical_action': action == row['action'],
                'candidate_opening': trace})
            print('retained', game['pair'], game['win'], candidate_game['win'], action != row['action'], flush=True)
            save()

        for case in fresh:
            pair = {'pair': case['pair'], 'stage': 'heldout-compositions'}
            for arm, scorer in (('control', legacy.score_exact_summary_breakdown), ('candidate', fixed)):
                tactical.score_exact_summary_breakdown = scorer
                driver.opening = original_opening
                result = driver.play(live, hypothetical, {**case, 'id': case['pair']+'-'+arm}, texts, policy, metadata, dex)
                assert result['status'] == 'complete', result
                assert result['rows'][0]['tactical']['status'] == 'complete'
                pair[arm] = result
            report['pairs'].append(pair)
            print('heldout', case['pair'], pair['control']['win'], pair['candidate']['win'], flush=True)
            save()
    tactical.score_exact_summary_breakdown = fixed
    report['summary'] = {}
    for stage in ('retained', 'heldout-compositions'):
        pairs = [p for p in report['pairs'] if p['stage'] == stage]
        clean = [p for p in pairs if not any(r['enemy_trace']['fallback'] for arm in ('control', 'candidate') for r in p[arm]['rows'])]
        def totals(selected):
            return {'pairs': len(selected), 'control_wins': sum(p['control']['win'] for p in selected),
                'candidate_wins': sum(p['candidate']['win'] for p in selected),
                'candidate_only': sum(p['candidate']['win'] and not p['control']['win'] for p in selected),
                'control_only': sum(p['control']['win'] and not p['candidate']['win'] for p in selected),
                'changed_openings': sum(p['control']['rows'][0]['action'] != p['candidate']['rows'][0]['action'] for p in selected)}
        report['summary'][stage] = {'all': totals(pairs), 'fallback_free': totals(clean)}
    assert all(hashlib.sha256((root/p).read_bytes()).hexdigest() == expected for p, expected in report['source_sha256'].items())
    save()
    print(json.dumps(report['summary'], indent=2))


if __name__ == '__main__':
    main()
