"""Fresh paired games against public upstream heuristics with legal Mega completion."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.diversity_league import team_text
from champions_practice.independent_opponent import IndependentOpponent, identity, load_dex
from champions_practice.search_worker import ShowdownSearchWorker, TeamValidationWorker
import full_game_native_evaluation as original
from tactical_consequences_evaluation import ROOT, frozen_policy


class MegaOpponent(IndependentOpponent):
    """Keep upstream move choice; complete it with a legal Mega modifier.

    Prefer the first eligible slot if two equivalent legal completions exist.
    Never change targets, switches, or moves to enable Mega Evolution.
    """

    def choose(self, view, choices):
        action, trace = super().choose(view, choices)
        stripped = lambda command: command.replace(' mega', '')
        completions = sorted(c for c in choices if ' mega' in c and stripped(c) == stripped(action))
        selected = completions[0] if completions else action
        return selected, {**trace, 'mega_augmentation': selected != action,
                          'upstream_action': action, 'mega_command': ' mega' in selected}


ROSTERS = (
    (('Gardevoir', 'Incineroar', 'Rillaboom', 'Rotom-Wash', 'Indeedee-F', 'Dragonite'),
     ('Metagross', 'Pelipper', 'Basculegion', 'Venusaur', 'Tyranitar', 'Excadrill')),
    (('Metagross', 'Rotom-Wash', 'Dragonite', 'Venusaur', 'Rillaboom', 'Incineroar'),
     ('Gardevoir', 'Indeedee-F', 'Garchomp', 'Rillaboom', 'Pelipper', 'Basculegion')),
    (('Pelipper', 'Gardevoir', 'Basculegion', 'Rillaboom', 'Rotom-Wash', 'Venusaur'),
     ('Metagross', 'Incineroar', 'Tyranitar', 'Excadrill', 'Dragonite', 'Garchomp')),
    (('Tyranitar', 'Metagross', 'Excadrill', 'Dragonite', 'Rotom-Wash', 'Incineroar'),
     ('Gardevoir', 'Rillaboom', 'Indeedee-F', 'Armarouge', 'Venusaur', 'Pelipper')),
    (('Gardevoir', 'Venusaur', 'Armarouge', 'Indeedee-F', 'Incineroar', 'Rotom-Wash'),
     ('Metagross', 'Garchomp', 'Rillaboom', 'Rotom-Wash', 'Dragonite', 'Pelipper')),
    (('Rillaboom', 'Metagross', 'Garchomp', 'Rotom-Wash', 'Venusaur', 'Dragonite'),
     ('Gardevoir', 'Pelipper', 'Incineroar', 'Basculegion', 'Indeedee-F', 'Armarouge')),
)


def public_tags(row):
    view = row['view']
    own = view['request'].get('side', {}).get('pokemon', [])
    tags = ['all']
    if sum('fnt' not in m.get('condition', '') for m in own) == 1:
        tags.append('last-own-pokemon')
    if row['phase'] != 'move':
        tags.append('replacement-or-other-phase')
    if any(' mega' in c for c in row['legal_actions']):
        tags.append('mega-available')
    if any(0 < m.get('hp_percent', 100) <= 25 for m in view['player']['active_details']):
        tags.append('low-hp-active')
    if any('switch ' in c for c in row['legal_actions']):
        tags.append('switch-available')
    return tags


def summarize(games):
    report = original.summarize(games)
    report['public_context_coverage'] = {}
    rows = [r for g in games if g['version'] == 'native' for r in g['rows']
            if r['decision']['admission_attempted']]
    for tag in sorted({t for r in rows for t in public_tags(r)}):
        selected = [r for r in rows if tag in public_tags(r)]
        report['public_context_coverage'][tag] = {
            'actionable': len(selected), 'searched': sum(r['decision']['status'] == 'search' for r in selected),
            'disagreed': sum(r['decision']['disagreement'] for r in selected)}
    report['opponent_mega'] = {
        'commands': sum(r['enemy_trace']['mega_command'] for g in games for r in g['rows']),
        'games_with_observed_mega_form': sum(g['opponent_mega_observed'] for g in games),
        'games': len(games),
    }
    report['result_by_composition'] = {str(i): original.summarize([g for g in games if g['composition'] == i])['all']
                                       for i in range(len(ROSTERS))}
    report['result_by_family'] = {family: original.summarize([g for g in games if g['hidden_family'] == family])['all']
                                for family in ('prior', 'heldout')}
    report['errors'] = dict(Counter(g.get('error_type') for g in games if g['status'] != 'complete'))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('freeze', 'evaluate'))
    parser.add_argument('--manifest', type=Path, default=ROOT/'reviews/mega-opposition-manifest-2026-10-16.json')
    parser.add_argument('--output', type=Path, default=ROOT/'runs/mega-opposition/v1')
    args = parser.parse_args()
    sources = [Path(__file__), ROOT/'scripts/full_game_native_evaluation.py',
               *ROOT.joinpath('src/champions_practice').rglob('*.py'), ROOT/'tools/showdown-search-worker.js']
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    dex = load_dex(ROOT)
    policy, baseline = frozen_policy('e0ae723')
    if args.phase == 'freeze':
        assert not args.manifest.exists(), 'Do not overwrite frozen protocol'
        texts, cases = {}, []
        for i, (ours, theirs) in enumerate(ROSTERS):
            for name, roster in ((f'own-{i}', ours), (f'enemy-{i}', theirs)):
                texts[name] = team_text(roster).replace('Armarouge @ Life Orb', 'Armarouge @ Charcoal')
            for family in ('prior', 'heldout'):
                for replicate in range(2):
                    pair = f'fresh-mega-{i}-{family}-{replicate}'
                    for arm in ('v2', 'native'):
                        cases.append({'id': pair+'-'+arm, 'pair': pair, 'version': arm, 'composition': i,
                            'side': 'p1' if replicate == 0 else 'p2', 'stage': 'fresh-mega',
                            'own_team': f'own-{i}', 'enemy_team': f'enemy-{i}', 'opponent': 'simple-heuristics-mega',
                            'hidden_family': family, 'opponent_seed': pair,
                            'battle_seed': 'sodium,'+hashlib.sha256(('fresh-mega-2026-10-16:'+pair).encode()).hexdigest()})
        manifest = {'source_sha256': hashes, 'baseline': baseline, 'opponent': identity(dex),
            'teams': texts, 'cases': cases, 'protocol': {
                'shared_budget_seconds': 8, 'horizon': 1, 'root_actions': 8, 'responses': 3,
                'priors': 'Unchanged production catalogue; no experimental Earthquake expansion.',
                'weights': 'Unchanged', 'preview': 'Own 1234; enemy prior 1234, heldout 1256.',
                'opposition': 'Upstream SimpleHeuristics plus deterministic legal Mega completion only.',
                'quality': 'Paired game outcomes; changed decisions are not individually graded.',
                'limitations': ['One opponent algorithm; stronger play is not independently established.',
                    'Fresh compositions and seeds, familiar species and prior-family sets.',
                    'Heldout Substitute/Sitrus variants; hidden family and selected four covary.',
                    'Fixed team selection; no ladder-strength claim; context tags are not tactical-value certification.']}}
        with TeamValidationWorker(ROOT, startup_deadline=perf_counter()+60) as validator:
            for text in texts.values():
                for variant in (text, text.replace('Protect', 'Substitute').replace('Life Orb', 'Sitrus Berry')):
                    result = validator.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=variant)
                    assert result['valid'], result['problems']
        args.manifest.write_text(json.dumps(manifest, indent=2)+'\n')
        print(f'Frozen {len(cases)//2} pairs before outcomes')
        return
    manifest = json.loads(args.manifest.read_text())
    assert hashes == manifest['source_sha256'], 'Frozen source changed'
    assert baseline == manifest['baseline'] and identity(dex) == manifest['opponent']
    args.output.mkdir(parents=True, exist_ok=False)
    original.IndependentOpponent = MegaOpponent
    report = {'manifest': str(args.manifest), 'games': []}
    with ShowdownSearchWorker(ROOT, startup_timeout_seconds=60) as live:
        for case in manifest['cases']:
            game = original.play(live, case, manifest['teams'], policy, PublicCatalog.load(ROOT), dex)
            # Observe the foe's actual public Mega form, independently of command selection.
            game['opponent_mega_observed'] = any('mega' in str(m.get('species', '')).lower()
                for row in game['rows'] for m in row['view']['opponent']['active'])
            report['games'].append(game)
            (args.output/'games.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
            print(case['id'], game['status'], game.get('win'), len(game['rows']), game.get('error', ''), flush=True)
    report['summary'] = summarize(report['games'])
    (args.output/'games.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    (args.output/'summary.json').write_text(json.dumps(report['summary'], indent=2)+'\n')
    print(json.dumps(report['summary'], indent=2))
    assert all(g['status'] == 'complete' for g in report['games'])


if __name__ == '__main__':
    main()
