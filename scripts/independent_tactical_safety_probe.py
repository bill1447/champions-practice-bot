"""Fresh public decision probes; conditional immediate terminal facts only."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog, observe
from champions_practice.competitive_evaluation import canonical_view
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.experimental_native_player import ExperimentalNativePlayer
from champions_practice.search_worker import HypotheticalSearchWorker, TeamValidationWorker
from fresh_tactical_benchmark import benchmark_team, select_probes, seed
from paired_native_continuation import continuation_priors, facts
from tactical_consequences_evaluation import frozen_policy


ROOT = Path(__file__).resolve().parents[1]
ROSTERS = (
    (('Rotom-Wash', 'Metagross', 'Rillaboom', 'Dragonite', 'Indeedee-F', 'Venusaur'),
     ('Pelipper', 'Incineroar', 'Basculegion', 'Garchomp', 'Gardevoir', 'Tyranitar')),
    (('Tyranitar', 'Venusaur', 'Armarouge', 'Rotom-Wash', 'Metagross', 'Dragonite'),
     ('Indeedee-F', 'Garchomp', 'Rillaboom', 'Pelipper', 'Incineroar', 'Gardevoir')),
    (('Rillaboom', 'Gardevoir', 'Metagross', 'Pelipper', 'Rotom-Wash', 'Indeedee-F'),
     ('Dragonite', 'Excadrill', 'Venusaur', 'Tyranitar', 'Armarouge', 'Incineroar')),
    (('Dragonite', 'Armarouge', 'Venusaur', 'Metagross', 'Rotom-Wash', 'Indeedee-F'),
     ('Rotom-Wash', 'Pelipper', 'Rillaboom', 'Tyranitar', 'Gardevoir', 'Incineroar')),
    (('Metagross', 'Indeedee-F', 'Rotom-Wash', 'Gardevoir', 'Pelipper', 'Incineroar'),
     ('Venusaur', 'Garchomp', 'Archaludon', 'Rillaboom', 'Tyranitar', 'Dragonite')),
    (('Incineroar', 'Garchomp', 'Rotom-Wash', 'Metagross', 'Gardevoir', 'Pelipper'),
     ('Tyranitar', 'Armarouge', 'Venusaur', 'Rillaboom', 'Indeedee-F', 'Dragonite')),
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('freeze', 'evaluate'))
    parser.add_argument('--manifest', type=Path, default=ROOT/'reviews/tactical-safety-manifest-2026-10-16.json')
    parser.add_argument('--output', type=Path, default=ROOT/'runs/tactical-safety/v1')
    parser.add_argument('--report', type=Path, default=ROOT/'reviews/tactical-safety-results-2026-10-16.json')
    args = parser.parse_args()
    sources = [Path(__file__).resolve(), *ROOT.joinpath('src/champions_practice').rglob('*.py'),
        ROOT/'tools/showdown-search-worker.js', ROOT/'scripts/paired_native_continuation.py',
        ROOT/'scripts/fresh_tactical_benchmark.py']
    hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in sources}
    if args.phase == 'freeze':
        assert not args.manifest.exists()
        cases = [{'id': f'safety-{i}-{j}', 'ours': ours, 'theirs': theirs,
            'own_team': benchmark_team(ours), 'enemy_team': benchmark_team(theirs),
            'seed': seed(f'independent-tactical-safety-2026-10-16:{i}:{j}')}
            for i, (ours, theirs) in enumerate(ROSTERS) for j in range(2)]
        args.manifest.write_text(json.dumps({'cases': cases, 'source_sha256': hashes,
            'protocol': {'prefix': 'Frozen V2 public six-mon views, three completed turns, preview 1234, phase limit six.',
                'decision': 'Frozen V2 versus existing public-only native player; shared eight seconds; public history only.',
                'priors': 'Explicit experimental public-earthquake-coverage profile; production catalogue unchanged.',
                'responses': 'Public V2 then deterministic command-category witnesses to four legal replies; same list for both actions.',
                'rolls': [seed(f'safety-roll-2026-10-16:{i}') for i in range(4)],
                'outcomes': 'One completed turn with public V2 phase completion. Report terminal wins/losses, not nonterminal optimality.',
                'retention': 'All twelve cases retained, including ended prefixes, rejected public histories and fallbacks; no resampling.',
                'limits': 'Fresh positions and compositions from familiar synthetic sets. Not independently authored opponents, replay positions or competitive-strength evidence.'}}, indent=2)+'\n')
        print('Frozen 12 fresh cases')
        return
    manifest = json.loads(args.manifest.read_text())
    assert manifest['source_sha256'] == hashes
    assert not args.output.exists()
    args.output.mkdir(parents=True)
    catalog = PublicCatalog.load(ROOT)
    policy, identity = frozen_policy('e0ae723')
    report = {'manifest_sha256': sha(args.manifest), 'baseline': identity, 'cases': []}
    raw = []
    with TeamValidationWorker(ROOT, startup_deadline=perf_counter()+60) as validator:
        for case in manifest['cases']:
            for key in ('own_team', 'enemy_team'):
                validation = validator.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=case[key])
                assert validation['valid'], validation['problems']
    with HypotheticalSearchWorker(ROOT, startup_deadline=perf_counter()+60) as worker:
        for case in manifest['cases']:
            previews = {'p1': case['ours'], 'p2': case['theirs']}
            def view(state, side):
                return worker.state_view(state=state, side=side, previews=previews)
            def choice(state, side):
                return policy(observe(view(state, side), worker.legal_choices(state=state, side=side), deadline=perf_counter()+8), catalog).action
            def branch(state, ours, theirs, rng):
                assert ours in worker.legal_choices(state=state, side='p1')
                assert theirs in worker.legal_choices(state=state, side='p2')
                return worker.branch_many(state=state, branches=[{'p1_choice': ours, 'p2_choice': theirs,
                    'rng_seed': rng, 'include_state': True}])[0]
            state = worker.create_state(battle_format=CHAMPIONS_FORMAT, p1_team=case['own_team'], p2_team=case['enemy_team'],
                p1_preview='team 1234', p2_preview='team 1234', seed=case['seed'])
            ledger, error, ended = None, None, False
            for turn in range(3):
                goal = view(state, 'p1')['turn']+1
                for phase in range(6):
                    public = canonical_view(view(state, 'p1'), 'p1')
                    if error is None:
                        try:
                            ledger = PublicConstraintLedger.from_public_view(public) if ledger is None else ledger.advance(public)
                        except ValueError as exc:
                            error = str(exc)
                    result = branch(state, choice(state, 'p1'), choice(state, 'p2'), seed(case['id']+f':prefix:{turn}:{phase}'))
                    state = result['state']
                    ended = result['summary']['ended']
                    if ended or result['summary']['turn'] >= goal:
                        break
                else:
                    raise AssertionError('Prefix phase bound')
                if ended:
                    break
            public = canonical_view(view(state, 'p1'), 'p1')
            menu = worker.legal_choices(state=state, side='p1')
            if ended or public['phase'] != 'move' or menu == ['wait'] or error:
                report['cases'].append({'id': case['id'], 'status': 'not_probed', 'ended': ended,
                    'phase': public['phase'], 'public_history_error': error})
                continue
            incumbent = choice(state, 'p1')
            player = ExperimentalNativePlayer(ROOT, own_team=case['own_team'], opening_prior='',
                priors=continuation_priors('public-earthquake-coverage'), catalog=catalog, incumbent_policy=policy)
            player.ledger = ledger
            selected, trace = player.decide(public, menu)
            assert trace['incumbent'] == incumbent
            replies = list(select_probes(worker.legal_choices(state=state, side='p2'), choice(state, 'p2')))[:4]
            samples = []
            for action in dict.fromkeys((incumbent, selected)):
                for reply in replies:
                    for roll, rng in enumerate(manifest['protocol']['rolls']):
                        result = branch(state, action, reply, rng)
                        for _ in range(6):
                            if result['summary']['ended'] or result['summary']['turn'] >= public['turn']+1:
                                break
                            child = result['state']
                            result = branch(child, choice(child, 'p1'), choice(child, 'p2'), seed(rng+':phase'))
                        else:
                            raise AssertionError('Outcome phase bound')
                        samples.append({'action': action, 'reply': reply, 'rng': roll, 'facts': facts(result['summary'])})
            v2 = {(s['reply'], s['rng']): s for s in samples if s['action'] == incumbent}
            native = {(s['reply'], s['rng']): s for s in samples if s['action'] == selected}
            assert v2.keys() == native.keys() and len(v2) == len(replies)*4
            wins = sum(native[k]['facts']['terminal_win'] and not v2[k]['facts']['terminal_win'] for k in v2)
            losses_avoided = sum(v2[k]['facts']['terminal_loss'] and not native[k]['facts']['terminal_loss'] for k in v2)
            losses_added = sum(native[k]['facts']['terminal_loss'] and not v2[k]['facts']['terminal_loss'] for k in v2)
            wins_lost = sum(v2[k]['facts']['terminal_win'] and not native[k]['facts']['terminal_win'] for k in v2)
            report['cases'].append({'id': case['id'], 'status': 'probed', 'native_status': trace['status'],
                'reason': trace['reason'], 'admitted_worlds': trace['admitted_worlds'], 'v2_action': incumbent,
                'native_requested_action': selected, 'changed': incumbent != selected, 'matched_scenarios': len(v2),
                'native_additional_terminal_wins': wins, 'native_avoided_terminal_losses': losses_avoided,
                'native_additional_terminal_losses': losses_added, 'native_lost_terminal_wins': wins_lost})
            raw.append({'case': case['id'], 'public_root': public, 'decision': trace, 'samples': samples})
            print(case['id'], trace['status'], trace['reason'], 'changed', incumbent != selected, flush=True)
    report['summary'] = {'statuses': dict(Counter(c['status'] for c in report['cases'])),
        'native_statuses': dict(Counter(c['native_status'] for c in report['cases'] if c['status'] == 'probed')),
        'changed_positions': sum(c.get('changed', False) for c in report['cases']),
        'no_optimality_or_strength_claim': True}
    args.report.write_text(json.dumps(report, indent=2)+'\n')
    (args.output/'results.json.gz').write_bytes(gzip.compress(json.dumps({'report': report, 'raw': raw}).encode()))
    print(json.dumps(report['summary']))


if __name__ == '__main__':
    main()
