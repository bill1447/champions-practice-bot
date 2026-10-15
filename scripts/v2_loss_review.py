"""Extract development loss evidence without running or changing a policy."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    archive = json.loads(gzip.decompress(args.archive.read_bytes()))
    losses, witnesses, flagged = [], [], Counter()
    games = []
    for game in archive['games']:
        if game['category'] != 'common-pressure' or 'v2' not in game['agents'].values():
            continue
        if game['status'] != 'complete':
            raise ValueError('Review requires complete games')
        side = next(s for s, agent in game['agents'].items() if agent == 'v2')
        games.append(game['id'])
        name = game['rows'][0]['sides'][side]['view']['player']['name']
        if game['winner'] == name or not game['winner']:
            continue
        losses.append(game['id'])
        for row in game['rows']:
            decision = row['sides'][side]
            diagnostic = decision.get('tactical_diagnostic', {})
            if diagnostic.get('dominated_on_both_samples'):
                flagged[game['id']] += 1
            # Exact command IDs in this frozen archive are named, not numeric.
            if ('move steelroller ' in decision['action'] and
                    not decision['view']['field'].get('terrain')):
                witnesses.append({
                    'game': game['id'], 'side': side,
                    'checkpoint': row['checkpoint'], 'turn': row['turn'],
                    'action': decision['action'],
                    'view': decision['view'],
                    'legal_actions': decision['public_choices'],
                    'ranking': decision['telemetry']['detail']['alternatives'],
                    'bounded_diagnostic': diagnostic,
                })
    result = {
        'archive_sha256': hashlib.sha256(args.archive.read_bytes()).hexdigest(),
        'baseline_commit': archive['baseline_commit'],
        'policy_sha256': archive['policy_sha256'],
        'games': len(games), 'losses': len(losses), 'loss_ids': losses,
        'losses_with_conditional_material_flags': len(flagged),
        'conditional_material_flag_decisions': sum(flagged.values()),
        'no_terrain_steel_roller_decisions': len(witnesses),
        'no_terrain_steel_roller_loss_games': len({w['game'] for w in witnesses}),
        'witnesses': witnesses,
        'limitations': [
            'Reused development archive; not fresh strength evidence.',
            'Repeated seeds and positions are correlated, not independent mistakes.',
            'Conditional hindsight material flags do not establish optimal actions or loss causation.',
            'Terrain at decision time can change before execution; review joint field-setting actions.',
            'No policy changed and no final holdout accessed.',
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'witnesses'}, indent=2))


if __name__ == '__main__':
    main()
