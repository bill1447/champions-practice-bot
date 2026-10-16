"""Permanent conditional witnesses; reconstruct mechanics, never load raw archives."""

import hashlib
import json
from pathlib import Path
from time import perf_counter

import pytest

from champions_practice.agent_v2 import PublicCatalog, observe
from champions_practice.competitive_evaluation import canonical_view
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.diversity_league import team_text
from champions_practice.experimental_native_player import ExperimentalNativePlayer
from champions_practice.search_worker import HypotheticalSearchWorker


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT/'tests/fixtures/native_continuation_regressions.json').read_text())


def seed(label):
    return 'sodium,'+hashlib.sha256(label.encode()).hexdigest()


@pytest.mark.parametrize('spec', FIXTURE['cases'], ids=[s['case']['id'] for s in FIXTURE['cases']])
def test_public_native_continuation_preserves_terminal_capability(spec, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    from paired_native_continuation import continuation_priors, facts
    from tactical_consequences_evaluation import frozen_policy
    policy, _ = frozen_policy('e0ae723')
    catalog = PublicCatalog.load(ROOT)
    case = spec['case']
    previews = {'p1': case['own_roster'], 'p2': case['enemy_roster']}
    with HypotheticalSearchWorker(ROOT, startup_deadline=perf_counter()+60) as worker:
        def view(state, side='p1', full=True):
            return worker.state_view(state=state, side=side, previews=previews if full else None)

        def v2(state, side='p1', full=True):
            return policy(observe(view(state, side, full), worker.legal_choices(state=state, side=side),
                                  deadline=perf_counter()+8), catalog).action

        def branch(state, own, enemy, rng):
            assert own in worker.legal_choices(state=state, side='p1')
            assert enemy in worker.legal_choices(state=state, side='p2')
            return worker.branch_many(state=state, branches=[{'p1_choice': own, 'p2_choice': enemy,
                'rng_seed': rng, 'include_state': True}])[0]

        state = worker.create_state(battle_format=CHAMPIONS_FORMAT, p1_team=case['own_team'],
            p2_team=case['enemy_team'], p1_preview=case['preview'], p2_preview=case['preview'], seed=case['seed'])
        ledger = None
        for step in range(case['warmup_completed_turns']):
            goal = view(state)['turn']+1
            for phase in range(6):
                public = canonical_view(view(state), 'p1')
                ledger = PublicConstraintLedger.from_public_view(public) if ledger is None else ledger.advance(public)
                result = branch(state, v2(state, full=False), v2(state, 'p2', full=False),
                                seed(case['id']+(f':prefix:{step}' if phase == 0 else f':prefix-complete:{step}')))
                state = result['state']
                if result['summary']['ended'] or result['summary']['turn'] >= goal:
                    break
            else:
                pytest.fail('Prefix did not complete')
        public = canonical_view(view(state), 'p1')
        ledger = PublicConstraintLedger.from_public_view(public) if ledger is None else ledger.advance(public)
        root_turn = public['turn']
        initial = branch(state, spec['root_action'], spec['reply'], spec['rng_label'])
        for mode in ('v2', 'native'):
            player = ExperimentalNativePlayer(ROOT, own_team=case['own_team'],
                opening_prior=team_text(case['enemy_roster']), priors=continuation_priors(FIXTURE['prior_profile']),
                catalog=catalog, incumbent_policy=policy)
            player.ledger = ledger
            result, searches, disagreements = initial, 0, 0
            for index in range(12):
                if result['summary']['ended'] or result['summary']['turn'] >= root_turn+2:
                    break
                state = result['state']
                public = canonical_view(view(state), 'p1')
                if mode == 'native':
                    own, trace = player.decide(public, worker.legal_choices(state=state, side='p1'))
                    searches += trace['status'] == 'search'
                    disagreements += trace['disagreement']
                else:
                    own = v2(state)
                scheduled = spec['opposition_schedule'][index]
                assert (public['turn'], public['phase']) == (scheduled['turn'], scheduled['phase'])
                result = branch(state, own, scheduled['action'], seed(spec['rng_label']+(
                    ':phase' if public['turn'] < root_turn+1 else ':next')))
            else:
                pytest.fail('Continuation did not complete')
            final = facts(result['summary'])
            assert {k: final[k] for k in spec['expected'][mode]} == spec['expected'][mode]
            if mode == 'native':
                assert searches > 0 and disagreements > 0
