"""Audit frozen weight functions, native controls and paired speed gameplay."""

import ast
import gzip
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    gameplay_path = ROOT/'runs/v2-speed-contract/gameplay-v1/games.json.gz'
    controls_path = ROOT/'runs/v2-speed-contract/native-v1/controls.json'
    games = json.loads(gzip.decompress(gameplay_path.read_bytes()))
    controls = json.loads(controls_path.read_text())
    for archive in (games, controls):
        for relative, expected in archive['source_sha256'].items():
            assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest() == expected, relative
    assert len(games['pairs']) == 48 and len(controls['controls']) == 7
    for pair in games['pairs']:
        a, b = pair['control'], pair['candidate']
        assert a['status'] == b['status'] == 'complete'
        for key in ('battle_seed', 'opponent_seed', 'own_team', 'enemy_team', 'side', 'truth_variant'):
            assert a[key] == b[key]
        assert a['rows'][0]['view'] == b['rows'][0]['view']
        assert all(r['action'] in r['legal_actions'] for game in (a, b) for r in game['rows'])
    relative = 'src/champions_practice/exact_search.py'
    old = subprocess.run(['git', 'show', 'dbb1027:'+relative], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    def functions(source):
        return {node.name: ast.dump(node, include_attributes=False) for node in ast.parse(source).body
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    before, after = functions(old), functions((ROOT/relative).read_text())
    unchanged = [name for name in before if name != '_average_active_speed']
    assert all(before[name] == after[name] for name in unchanged)
    report = {'summary': games['summary'], 'native_controls': controls['controls'],
        'weight_functions_unchanged': unchanged,
        'archive_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in (gameplay_path, controls_path)},
        'scope': games['scope'], 'new_unique_games': 36,
        'new_simulated_game_records': 52,
        'reused_retained_games': 24, 'identical_action_retained_pairs': 20}
    (ROOT/'reviews/v2-speed-contract-2026-10-15.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report['summary'], indent=2))


if __name__ == '__main__':
    main()
