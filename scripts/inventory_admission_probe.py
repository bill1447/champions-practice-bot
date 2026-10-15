"""Replay retained inventory gates; actual native replay is a separate control.

The admission player receives only saved public views, own team and unchanged
approved priors. Actual sets/seeds are used ONLY by the native control below.
No game outcomes are rerun or credited to this position-level experiment.
"""

import argparse
from copy import deepcopy
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog
from champions_practice.competitive_evaluation import canonical_view
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.diversity_league import catalog as public_priors
from champions_practice.experimental_native_player import ExperimentalNativePlayer
from champions_practice.public_inventory import public_inventory_plan, native_inventory_rejection
from champions_practice.search_worker import HypotheticalSearchWorker
from champions_practice.tactical_consequences import observation_key
from tactical_consequences_evaluation import ROOT, blueprints, frozen_policy, species


def native_controls(worker, game, texts, targets):
    """Oracle fixture only: reproduce actual native fields, never give to player."""
    own, actual = texts[game['own_team']], texts[game['enemy_team']]
    if game['hidden_family'] == 'heldout':
        actual = actual.replace('Protect', 'Substitute').replace('Life Orb', 'Sitrus Berry')
    side = game['side']
    other = 'p1' if side == 'p2' else 'p2'
    selection = {side: 'team 1234', other: 'team 1256' if game['hidden_family'] == 'heldout' else 'team 1234'}
    state = worker.create_state(battle_format=CHAMPIONS_FORMAT,
        p1_team=own if side == 'p1' else actual, p2_team=actual if side == 'p1' else own,
        p1_preview=selection['p1'], p2_preview=selection['p2'], p1_name='P1', p2_name='P2', seed=game['battle_seed'])
    controls, ledger = {}, None
    previews = {side: species(own), other: species(actual)}
    for index, row in enumerate(game['rows']):
        view = canonical_view(row['view'], side)
        ledger = PublicConstraintLedger.from_public_view(view) if ledger is None else ledger.advance(view)
        actual_view = worker.state_view(state=state, side=side, previews=previews)
        assert observation_key(actual_view) == observation_key(row['view']), (game['id'], index, 'native replay drift')
        if index in targets:
            plan = public_inventory_plan(view, ledger)
            assert plan
            ordered = {'sides': [state['sides'][0 if other == 'p1' else 1], state['sides'][0 if side == 'p1' else 1]]}
            assert native_inventory_rejection(ordered, plan) is None, (game['id'], index, plan)
            failures = 0
            for entry in plan:
                name = ''.join(c for c in entry['species'].lower() if c.isalnum())
                target = next(i for i, mon in enumerate(ordered['sides'][0]['pokemon'])
                              if ''.join(c for c in mon['set']['species'].lower() if c.isalnum()) == name)
                for key, value in [('item', entry['item']), ('lastItem', ''),
                                   ('ateBerry', not entry['ate_berry']), ('usedItemThisTurn', not entry['used_this_turn'])]:
                    corrupted = deepcopy(ordered)
                    corrupted['sides'][0]['pokemon'][target][key] = value
                    assert native_inventory_rejection(corrupted, plan) is not None
                    failures += 1
            controls[index] = {'native_inventory_matches': True, 'corruptions_rejected': failures,
                               'plan': plan}
        if index == max(targets):
            break
        commands = {side: row['action'], other: row['enemy_action']}
        state = worker.branch_many(state=state, branches=[{'p1_choice': commands['p1'],
            'p2_choice': commands['p2'], 'include_state': True}])[0]['state']
    return controls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    archive = ROOT/'runs/v2-full-game-native/frozen-v2/games.json.gz'
    raw = archive.read_bytes()
    original = json.loads(gzip.decompress(raw))
    texts, _ = blueprints()
    policy, baseline = frozen_policy('e0ae723')
    catalog = PublicCatalog.load(ROOT)
    priors = public_priors()
    source_paths = ['scripts/inventory_admission_probe.py', 'src/champions_practice/public_inventory.py',
        'src/champions_practice/persistent_support.py', 'src/champions_practice/present_rebase.py',
        'src/champions_practice/search_worker.py', 'src/champions_practice/experimental_native_player.py',
        'src/champions_practice/tactical_consequences.py', 'src/champions_practice/exact_search.py',
        'src/champions_practice/public_origin.py', 'tools/showdown-search-worker.js']
    report = {'archive_sha256': hashlib.sha256(raw).hexdigest(), 'baseline': baseline,
              'source_sha256': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in source_paths},
              'priors_sha256': hashlib.sha256(json.dumps({s: [asdict(c) for c in cs]
                  for s, cs in priors.items()}, sort_keys=True).encode()).hexdigest(),
              'positions': [], 'strategic_weights_changed': False}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    with HypotheticalSearchWorker(ROOT, startup_deadline=perf_counter()+30) as control_worker:
        for game in original['games']:
            if game['version'] != 'native':
                continue
            targets = {i for i, row in enumerate(game['rows'])
                       if row['decision']['reason'] == 'unsupported-persistent:opponent-inventory'}
            if not targets:
                continue
            controls = native_controls(control_worker, game, texts, targets)
            player = ExperimentalNativePlayer(ROOT, own_team=texts[game['own_team']],
                opening_prior=texts[game['enemy_team']], priors=priors, catalog=catalog, incumbent_policy=policy)
            ledger = None
            for index, row in enumerate(game['rows']):
                view = canonical_view(row['view'], game['side'])
                ledger = PublicConstraintLedger.from_public_view(view) if ledger is None else ledger.advance(view)
                if index not in targets:
                    continue
                player.ledger = ledger
                _, trace = player.decide(view, row['legal_actions'])
                def ident(value):
                    return ''.join(c for c in str(value).lower() if c.isalnum())
                item_catalog = {ident(s): {ident(c.item) for c in cs} for s, cs in priors.items()}
                covered = all(e['item'] in item_catalog.get(ident(e['species']), set())
                              for e in controls[index]['plan'])
                report['positions'].append({'game': game['id'], 'checkpoint': index,
                    'turn': view['turn'], 'phase': view['phase'], 'prior_items_covered': covered,
                    'decision': trace, 'control': controls[index]})
                print(game['id'], index, trace['status'], trace['admitted_worlds'], trace['reason'], flush=True)
                (args.output/'positions.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    assert len(report['positions']) == 29
    print('Completed', len(report['positions']), 'retained positions', flush=True)


if __name__ == '__main__':
    main()
