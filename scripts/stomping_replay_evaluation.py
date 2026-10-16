"""Frozen-suite regression and same-position admission probe; no fresh strength claim."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

from champions_practice.agent_v2 import PublicCatalog
from champions_practice.competitive_evaluation import canonical_view
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.diversity_league import catalog as public_priors
from champions_practice.experimental_native_player import ExperimentalNativePlayer
from champions_practice.independent_opponent import load_dex
from champions_practice.search_worker import ShowdownSearchWorker
import full_game_native_evaluation as original
from mega_opposition_evaluation import MegaOpponent, public_tags, summarize
from tactical_consequences_evaluation import ROOT, frozen_policy


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def signature(game):
    return [game['status'], game['win'], game['winner'],
            [(r['view'], r['action'], r['enemy_action'], r['enemy_trace']) for r in game['rows']]]


def shadow(before, manifest, policy, catalog):
    rows = []
    for game in before['games']:
        if game['version'] != 'native':
            continue
        player = ExperimentalNativePlayer(ROOT, own_team=manifest['teams'][game['own_team']],
            opening_prior=manifest['teams'][game['enemy_team']], priors=public_priors(),
            catalog=catalog, incumbent_policy=policy)
        for checkpoint, row in enumerate(game['rows']):
            public = canonical_view(row['view'], game['side'])
            if row['decision']['reason'] == 'unsupported-persistent:move:stompingtantrum':
                action, trace = player.decide(public, row['legal_actions'])
                assert trace['incumbent'] == row['action']
                rows.append({'game': game['id'], 'checkpoint': checkpoint, 'turn': row['turn'], 'phase': row['phase'],
                    'public_contexts': public_tags(row), 'action': action, 'incumbent': row['action'],
                    'status': trace['status'], 'reason': trace['reason'], 'admitted_worlds': trace['admitted_worlds'],
                    'disagreement': trace['disagreement'], 'seconds': trace['elapsed_seconds'], 'trace': trace})
            else:
                player.ledger = (PublicConstraintLedger.from_public_view(public) if player.ledger is None
                                 else player.ledger.advance(public))
                player.previous_plan = row['decision'].get('strategy')
    assert len(rows) == 67
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('freeze', 'evaluate'))
    parser.add_argument('--manifest', type=Path, default=ROOT/'reviews/stomping-replay-manifest-2026-10-16.json')
    parser.add_argument('--output', type=Path, default=ROOT/'runs/stomping-admission/replay-v1')
    args = parser.parse_args()
    control_path = ROOT/'reviews/mega-opposition-manifest-2026-10-16.json'
    archive_path = ROOT/'runs/mega-opposition/v1/games.json.gz'
    control = json.loads(control_path.read_text())
    sources = [Path(__file__), ROOT/'scripts/mega_opposition_evaluation.py', ROOT/'scripts/full_game_native_evaluation.py',
               *ROOT.joinpath('src/champions_practice').rglob('*.py'), ROOT/'tools/showdown-search-worker.js']
    hashes = {p.relative_to(ROOT).as_posix(): digest(p) for p in sources}
    if args.phase == 'freeze':
        assert not args.manifest.exists()
        frozen = {'control_manifest_sha256': digest(control_path), 'control_archive_sha256': digest(archive_path),
            'source_sha256': hashes, 'cases': control['cases'], 'teams': control['teams'],
            'baseline': control['baseline'], 'opponent': control['opponent'], 'protocol': control['protocol'],
            'change': 'Public-certified previous-result admission for active Stomping Tantrum. No weight/prior/search-limit changes.',
            'same_position_probe': 'Reconsider exactly the 67 old native Stomping fallbacks using their original public histories; never execute shadow decisions.',
            'scope': 'Regression on already inspected cases. Full-game outcomes are not fresh playing-strength evidence.'}
        args.manifest.write_text(json.dumps(frozen, indent=2)+'\n')
        print('Frozen 24 unchanged pairs plus 67 same-position probes')
        return
    frozen = json.loads(args.manifest.read_text())
    assert frozen['source_sha256'] == hashes
    assert frozen['control_manifest_sha256'] == digest(control_path)
    assert frozen['control_archive_sha256'] == digest(archive_path)
    before = json.loads(gzip.decompress(archive_path.read_bytes()))
    policy, identity = frozen_policy('e0ae723')
    assert identity == frozen['baseline']
    args.output.mkdir(parents=True, exist_ok=False)
    catalog = PublicCatalog.load(ROOT)
    original.IndependentOpponent = MegaOpponent
    report = {'manifest_sha256': digest(args.manifest), 'shadow': shadow(before, frozen, policy, catalog), 'games': []}
    (args.output/'results.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    print('Shadow statuses:', dict(Counter(r['status'] for r in report['shadow'])), flush=True)
    with ShowdownSearchWorker(ROOT, startup_timeout_seconds=60) as live:
        dex = load_dex(ROOT)
        for case in frozen['cases']:
            game = original.play(live, case, frozen['teams'], policy, catalog, dex)
            game['opponent_mega_observed'] = any('mega' in str(m.get('species', '')).lower()
                for r in game['rows'] for m in r['view']['opponent']['active'])
            report['games'].append(game)
            print(case['id'], game['status'], game.get('win'), len(game['rows']), game.get('error', ''), flush=True)
            (args.output/'results.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    old = {g['id']: g for g in before['games']}
    assert all(g['status'] == 'complete' for g in report['games']) and len(report['games']) == 48
    assert all(signature(g) == signature(old[g['id']]) for g in report['games'] if g['version'] == 'v2')
    report['summary'] = summarize(report['games'])
    compact = {'manifest_sha256': report['manifest_sha256'], 'control_v2_exact_paths': 24,
        'summary': report['summary'], 'shadow_statuses': dict(Counter(r['status'] for r in report['shadow'])),
        'shadow_reasons': dict(Counter(r['reason'] for r in report['shadow'])),
        'shadow_disagreements': sum(r['disagreement'] for r in report['shadow']),
        'shadow_by_context': {tag: {'decisions': len(rs), 'searched': sum(r['status'] == 'search' for r in rs),
            'disagreements': sum(r['disagreement'] for r in rs)}
            for tag in sorted({t for r in report['shadow'] for t in r['public_contexts']})
            if (rs := [r for r in report['shadow'] if tag in r['public_contexts']])},
        'shadow_decisions': [{k: v for k, v in r.items() if k != 'trace'} for r in report['shadow']],
        'native_changed_games': [{'id': g['id'], 'old_win': old[g['id']]['win'], 'new_win': g['win'],
            'old_checkpoints': len(old[g['id']]['rows']), 'new_checkpoints': len(g['rows'])}
            for g in report['games'] if g['version'] == 'native' and signature(g) != signature(old[g['id']])],
        'scope': frozen['scope']}
    report['compact'] = compact
    (args.output/'results.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    (args.output/'summary.json').write_text(json.dumps(compact, indent=2)+'\n')
    print(json.dumps({k: v for k, v in compact.items() if k in {
        'shadow_statuses', 'shadow_reasons', 'shadow_disagreements', 'shadow_by_context', 'native_changed_games'}}, indent=2))
    print('Paired results:', compact['summary']['all'])


if __name__ == '__main__':
    main()
