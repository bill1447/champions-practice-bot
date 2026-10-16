"""Two retained actions x two public continuation policies; unchanged weights."""

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
from statistics import fmean
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog, observe
from champions_practice.competitive_evaluation import canonical_view
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.diversity_league import catalog as public_priors, team_text
from champions_practice.exact_search import score_exact_summary_breakdown
from champions_practice.experimental_native_player import ExperimentalNativePlayer
from champions_practice.search_worker import HypotheticalSearchWorker
from champions_practice.tactical_consequences import observation_key
from fresh_tactical_benchmark import seed
from tactical_consequences_evaluation import frozen_policy


ROOT = Path(__file__).resolve().parents[1]
INPUT = 'runs/fresh-tactical/v1/results.json.gz'
FRESH_MANIFEST = 'reviews/fresh-tactical-manifest-v2-2026-10-15.json'
CASES = (
    ('speed-control-warmup-2', 'move protect, move steelroller +1'),
    ('trade-and-spread-warmup-2', 'move earthquake, move expandingforce +2 mega'),
    ('alternative-attacker-warmup-0', 'move hypervoice mega, move steelroller +2'),
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(gzip.decompress((ROOT/path).read_bytes()))


def public_key(view):
    # Include public event deltas used by the ledger, not just the tactical board.
    return digest(json.dumps(view, sort_keys=True).encode())


def facts(summary):
    return {'turn': summary['turn'], 'ended': summary['ended'],
        'terminal_win': summary['ended'] and summary['winner'] == summary['p1']['name'],
        'terminal_loss': summary['ended'] and summary['winner'] == summary['p2']['name'],
        'own_living': [m['species'] for m in summary['p1']['pokemon'] if m['hp'] > 0 and not m['fainted']],
        'enemy_living': [m['species'] for m in summary['p2']['pokemon'] if m['hp'] > 0 and not m['fainted']],
        'utility': asdict(score_exact_summary_breakdown(summary, 'p1'))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('freeze', 'evaluate'))
    parser.add_argument('--manifest', type=Path, default=ROOT/'reviews/paired-continuation-manifest-2026-10-16.json')
    parser.add_argument('--output', type=Path, default=ROOT/'runs/paired-continuation/v1')
    args = parser.parse_args()
    source = read(INPUT)
    fresh = json.loads((ROOT/FRESH_MANIFEST).read_text())
    sources = [Path(__file__).resolve(), *ROOT.joinpath('src/champions_practice').rglob('*.py'),
               ROOT/'tools/showdown-search-worker.js', ROOT/'scripts/fresh_tactical_benchmark.py']
    hashes = {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in sources}
    if args.phase == 'freeze':
        assert not args.manifest.exists(), 'Never replace frozen inputs'
        cases = []
        for name, alternative in CASES:
            raw = next(c for c in source['raw'] if c['case'] == name)
            saved = next(c for c in source['report']['cases'] if c['id'] == name)
            ranking = {r['action']: r for r in raw['ranking']}
            floors = {}
            for action in (saved['selected'], alternative):
                row = ranking[action]
                samples = [(reply, sample) for w in row['worlds'] for reply, sample in w['sampled_responses'].items()]
                floors[action] = {'worst': row['worst_world_utility'],
                    'equal_reply_mean': fmean(sample['leaf_utility'] for _, sample in samples),
                    'controlling_responses': [{'reply': reply, **sample} for reply, sample in samples
                        if sample['leaf_utility'] == row['worst_world_utility']]}
            cases.append({'id': name, 'selected': saved['selected'], 'alternative': alternative,
                'replies': saved['replies'], 'root_floor_attribution': floors})
        args.manifest.write_text(json.dumps({'cases': cases,
            'input_sha256': digest((ROOT/INPUT).read_bytes()), 'fresh_manifest_sha256': digest((ROOT/FRESH_MANIFEST).read_bytes()),
            'source_sha256': hashes, 'rng_labels': fresh['protocol']['rng'],
            'protocol': {'priority': 'speed-control first; all three retained cases; no outcome-based exclusions',
                'factorial': 'Two fixed root commands x frozen V2 or deployed public-only native continuation.',
                'root': 'Reproduce exact fresh-benchmark roots, initial replies and four coupled RNG labels.',
                'public': 'Both continuations receive full public six-mon previews, owned requests and public history only.',
                'native': 'Existing ExperimentalNativePlayer; shared eight-second preparation/search budget per decision; no carried exact states.',
                'priors': 'Existing diversity catalog, unchanged; no actual opponent team passed to native continuation.',
                'opposition': 'V2 reference replies replayed at matching turn/phase/occurrence if legal. Missing/illegal schedules explicitly unmatched; use public V2 and separate strict-paired analyses.',
                'rng': 'Exact original root labels; same phase and next-turn seed derivation as fresh benchmark.',
                'horizon': 'Through root turn + 2, at most six decision checkpoints per turn.',
                'fallback': 'Admission failures, deadlines, native errors and forced waits reported separately; none counted as successful search.',
                'cache': 'Decision memoization keyed only by full public observation/action history and legal menu; occurrences and unique computations reported separately.',
                'limits': 'Retained diagnostics, not game win probabilities. Full-preview V2 replay may differ from earlier exact-world probe. Nonterminal survival is not a proven win route.'}}, indent=2)+'\n')
        print('Frozen paired comparison for', len(cases), 'cases')
        return
    manifest = json.loads(args.manifest.read_text())
    assert manifest['source_sha256'] == hashes
    assert manifest['input_sha256'] == digest((ROOT/INPUT).read_bytes())
    assert manifest['fresh_manifest_sha256'] == digest((ROOT/FRESH_MANIFEST).read_bytes())
    assert not args.output.exists(), 'Choose a fresh run directory'
    args.output.mkdir(parents=True)
    policy, policy_identity = frozen_policy('e0ae723')
    catalog = PublicCatalog.load(ROOT)
    report = {'manifest_sha256': digest(args.manifest.read_bytes()), 'baseline': policy_identity, 'cases': []}
    cache = {}
    with HypotheticalSearchWorker(ROOT, startup_deadline=perf_counter()+60) as worker:
        def v2(state, side, previews=None):
            view = worker.state_view(state=state, side=side, previews=previews)
            menu = worker.legal_choices(state=state, side=side)
            return policy(observe(view, menu, deadline=perf_counter()+8), catalog).action

        def branch(state, own, enemy, rng):
            assert own in worker.legal_choices(state=state, side='p1')
            assert enemy in worker.legal_choices(state=state, side='p2')
            return worker.branch_many(state=state, branches=[{'p1_choice': own, 'p2_choice': enemy,
                'rng_seed': rng, 'include_state': True}])[0]

        for spec in manifest['cases']:
            case = next(c for c in fresh['cases'] if c['id'] == spec['id'])
            raw = next(c for c in source['raw'] if c['case'] == spec['id'])
            previews = {'p1': case['own_roster'], 'p2': case['enemy_roster']}
            state = worker.create_state(battle_format=CHAMPIONS_FORMAT, p1_team=case['own_team'],
                p2_team=case['enemy_team'], p1_preview=case['preview'], p2_preview=case['preview'], seed=case['seed'])
            history = []
            for step in range(case['warmup_completed_turns']):
                goal = worker.state_view(state=state, side='p1')['turn']+1
                for phase in range(7):
                    assert phase < 6
                    public = canonical_view(worker.state_view(state=state, side='p1', previews=previews), 'p1')
                    own = v2(state, 'p1')  # Reproduce the already frozen prefix exactly.
                    history.append((public, own))
                    outcome = branch(state, own, v2(state, 'p2'), seed(case['id']+f':prefix:{step}') if phase == 0
                        else seed(case['id']+f':prefix-complete:{step}'))
                    state = outcome['state']
                    if outcome['summary']['ended'] or outcome['summary']['turn'] >= goal:
                        break
            root_view = worker.state_view(state=state, side='p1')
            assert observation_key(root_view) == observation_key(raw['root_view']), 'Exact frozen root changed'
            root_public = canonical_view(worker.state_view(state=state, side='p1', previews=previews), 'p1')
            root_turn = root_view['turn']
            prefix_ledger = None
            for view, _ in [*history, (root_public, '')]:
                prefix_ledger = PublicConstraintLedger.from_public_view(view) if prefix_ledger is None else prefix_ledger.advance(view)
            rows = []
            for role, action in (('selected', spec['selected']), ('alternative', spec['alternative'])):
                for reply in spec['replies']:
                    for roll, rng in enumerate(manifest['rng_labels']):
                        initial = branch(state, action, reply, rng)
                        reference_replies = {}
                        for mode in ('v2', 'native'):
                            player = ExperimentalNativePlayer(ROOT, own_team=case['own_team'],
                                opening_prior=team_text(case['enemy_roster']), priors=public_priors(),
                                catalog=catalog, incumbent_policy=policy) if mode == 'native' else None
                            if player:
                                player.ledger = prefix_ledger
                            outcome = initial
                            observed = [(public_key(v), a) for v, a in history]+[(public_key(root_public), action)]
                            first = facts(initial['summary']) if initial['summary']['ended'] or initial['summary']['turn'] >= root_turn+1 else None
                            decisions, occurrences = [], Counter()
                            for _ in range(13):
                                summary = outcome['summary']
                                if summary['ended'] or summary['turn'] >= root_turn+2:
                                    break
                                assert len(decisions) < 12, 'Incomplete continuation; never discard silently'
                                parent = outcome['state']
                                public = canonical_view(worker.state_view(state=parent, side='p1', previews=previews), 'p1')
                                menu = worker.legal_choices(state=parent, side='p1')
                                key = digest(json.dumps([case['own_team'], observed, public_key(public), menu], sort_keys=True).encode())
                                cached = (mode, key) in cache
                                if cached:
                                    own, trace = deepcopy(cache[mode, key])
                                    if player:
                                        try:
                                            player.ledger = player.ledger.advance(public)
                                        except ValueError:
                                            assert trace['reason'] == 'public-ledger-rejected'
                                        player.previous_plan = trace.get('strategy')
                                elif player:
                                    own, trace = player.decide(public, menu)
                                else:
                                    own = policy(observe(public, menu, deadline=perf_counter()+8), catalog).action
                                    trace = {'status': 'v2', 'action': own}
                                cache[mode, key] = deepcopy((own, trace))
                                observed.append((public_key(public), own))
                                enemy_menu = worker.legal_choices(state=parent, side='p2')
                                event = (public['turn'], public['phase'])
                                schedule_key = (*event, occurrences[event])
                                occurrences[event] += 1
                                if mode == 'v2':
                                    enemy = v2(parent, 'p2', previews)
                                    reference_replies[schedule_key] = enemy
                                    matched = True
                                else:
                                    reference = reference_replies.get(schedule_key)
                                    matched = reference in enemy_menu
                                    enemy = reference if matched else v2(parent, 'p2', previews)
                                decisions.append({'turn': public['turn'], 'phase': public['phase'], 'own_action': own,
                                    'enemy_action': enemy, 'opposing_reply_matched': matched, 'trace': trace,
                                    'cached': cached, 'information_key': key})
                                outcome = branch(parent, own, enemy, seed(rng+(':phase' if public['turn'] < root_turn+1 else ':next')))
                                if first is None and (outcome['summary']['ended'] or outcome['summary']['turn'] >= root_turn+1):
                                    first = facts(outcome['summary'])
                            assert first is not None
                            original = next(m for m in raw['measurements'] if m['action'] == action and m['reply'] == reply and m['rng'] == roll)
                            final = facts(outcome['summary'])
                            parity = all(first[k] == original['first'][k] and final[k] == original['second'][k]
                                for k in ('turn', 'terminal_win', 'terminal_loss', 'own_living', 'enemy_living', 'utility')) if mode == 'v2' else None
                            rows.append({'root_role': role, 'root_action': action, 'reply': reply, 'rng': roll,
                                'policy': mode, 'first': first, 'second': final, 'decisions': decisions,
                                'strict_opposition_match': all(d['opposing_reply_matched'] for d in decisions),
                                'historical_v2_probe_parity': parity})
            report['cases'].append({'id': spec['id'], 'rows': rows})
            (args.output/'results.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
            counts = Counter(d['trace']['status'] for row in rows if row['policy'] == 'native' for d in row['decisions'])
            print(spec['id'], 'trajectories', len(rows), 'native statuses', dict(counts), flush=True)
    report['decision_cache_entries'] = len(cache)
    (args.output/'results.json.gz').write_bytes(gzip.compress(json.dumps(report).encode()))
    print('Complete:', len(report['cases']), 'cases')


if __name__ == '__main__':
    main()
