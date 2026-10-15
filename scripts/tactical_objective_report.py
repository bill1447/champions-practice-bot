"""Audit retained objective experiments and summarize continuation diagnostics."""

import gzip
import hashlib
import json
from pathlib import Path
from statistics import mean

from tactical_objective_experiment import strip_telemetry


ROOT = Path(__file__).resolve().parents[1]


def read(relative):
    return json.loads(gzip.decompress((ROOT / relative).read_bytes()))


def digest(relative):
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def main():
    source = 'runs/v2-objective/v1/results.json.gz'
    future_source = 'runs/v2-objective/continuations-v1/results.json.gz'
    result, future = read(source), read(future_source)
    base_path = 'runs/v2-consequences/one-turn/games.json.gz'
    assert digest(base_path) == result['base_archive_sha256']
    assert digest(source) == future['objective_archive_sha256']
    for archive in (result, future):
        for path, expected in archive['source_sha256'].items():
            assert digest(path) == expected, path
    archives = {p: read(p) for p in result['reference_archives']}
    for path, expected in result['reference_archives'].items():
        assert digest(path) == expected
    games = {g['pair']: g for g in archives[base_path]['games']}
    assert len(result['matrices']) == len(games) == 24
    for matrix in result['matrices']:
        original = games[matrix['pair']]['rows'][0]['tactical']
        assert strip_telemetry(matrix['ranking']) == original['ranking']
        assert matrix['branch_count'] == original['branch_count']
    assert len(result['assignments']) == 264
    assert len(result['new_games']) == len(result['schedule']) == 12
    for assignment in result['assignments']:
        reference = assignment['result_ref']
        pool = result['new_games'] if reference['archive'] == 'new_games' else archives[reference['archive']]['games']
        game = next(g for g in pool if g['id'] == reference['game'])
        assert game['status'] == 'complete'
        assert game['pair'] == assignment['pair']
        assert game['rows'][0]['action'] == assignment['action']
        assert game['win'] == assignment['win']
        assert any(r['enemy_trace']['fallback'] for r in game['rows']) == assignment['fallback']
    continuation = []
    for position in future['positions']:
        for action in position['actions']:
            rows = [r for r in position['rows'] if r['action'] == action]
            assert all(r['status'] == 'complete' for r in rows)
            clean = [r for r in rows if not r['opponent_fallback']]
            continuation.append({'pair': position['pair'], 'action': action,
                'samples': len(rows), 'clean_samples': len(clean),
                'first_turn_mean': mean(r['first_turn']['score']['total'] for r in clean),
                'second_turn_mean': mean(r['second_turn']['score']['total'] for r in clean),
                'second_turn_survivor_difference': mean(r['second_turn']['own_survivors'] - r['second_turn']['foe_survivors'] for r in clean)})
    report = {'archives_sha256': {p: digest(p) for p in (source, future_source)},
        'summary': result['summary'], 'continuations': continuation,
        'continuation_samples': sum(r['samples'] for r in continuation),
        'continuation_fallback_samples': sum(r['samples']-r['clean_samples'] for r in continuation)}
    assert report['continuation_samples'] == 288
    (ROOT/'reviews/v2-objective-2026-10-15.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
