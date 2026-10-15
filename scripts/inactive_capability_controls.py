"""Native switch-reset controls for dormant Stomping Tantrum and Unburden."""

import hashlib
import json
from time import perf_counter

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.diversity_league import team_text
from champions_practice.search_worker import HypotheticalSearchWorker, TeamValidationWorker
from tactical_consequences_evaluation import ROOT


def main():
    own = team_text(('Indeedee-F', 'Sneasler', 'Dragonite', 'Rotom-Wash', 'Gardevoir', 'Metagross'))
    foe = team_text(('Indeedee-F', 'Metagross', 'Rotom-Wash', 'Gardevoir', 'Incineroar', 'Dragonite'))
    foe = foe.replace('- Imprison', '- Protect')
    with TeamValidationWorker(ROOT, startup_deadline=perf_counter()+60) as validator:
        for text in (own, foe):
            result = validator.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=text)
            assert result['valid'], result
    rng = 'sodium,'+'12345678'*8
    report = {'legal_teams': True, 'controls': [], 'source_sha256': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
        for p in ('scripts/inactive_capability_controls.py', 'src/champions_practice/persistent_support.py',
                  'src/champions_practice/present_rebase.py', 'tools/showdown-search-worker.js')}}
    with HypotheticalSearchWorker(ROOT, startup_deadline=perf_counter()+60) as worker:
        state = worker.create_state(battle_format=CHAMPIONS_FORMAT, p1_team=foe, p2_team=own,
            p1_preview='team 1324', p2_preview='team 3214', seed=rng)

        def mon(state, species):
            return next(m for m in state['sides'][1]['pokemon'] if m['set']['species'] == species)

        def advance(p1, p2):
            nonlocal state
            assert p1 in worker.legal_choices(state=state, side='p1')
            assert p2 in worker.legal_choices(state=state, side='p2')
            output = worker.branch_many(state=state, branches=[{'p1_choice': p1,
                'p2_choice': p2, 'rng_seed': rng, 'include_state': True}])[0]
            state = output['state']
            return output['summary']

        assert 'unburden' in mon(state, 'Sneasler')['volatiles']
        first = advance('move protect, move willowisp +2', 'move stompingtantrum +2, move protect')
        assert mon(state, 'Dragonite')['moveLastTurnResult'] is False
        boosted_speed = next(m['effectiveSpeed'] for m in first['p2']['active'] if m['species'] == 'Sneasler')
        advance('move followme, move thunderbolt +1', 'switch 3, switch 4')
        dragon, sneasler = mon(state, 'Dragonite'), mon(state, 'Sneasler')
        assert not dragon['isActive'] and dragon.get('moveLastTurnResult') is None
        assert not sneasler['isActive'] and 'unburden' not in sneasler['volatiles'] and not sneasler['item']
        report['controls'].append({'name': 'native-switch-out-reset', 'prior_stomping_failure': True,
            'benched_last_result_unset': True, 'benched_unburden_absent': True})
        returned = advance('move protect, move protect', 'switch 3, switch 4')
        assert mon(state, 'Dragonite').get('moveLastTurnResult') is None
        assert 'unburden' not in mon(state, 'Sneasler')['volatiles']
        returned_speed = next(m['effectiveSpeed'] for m in returned['p2']['active'] if m['species'] == 'Sneasler')
        assert boosted_speed == returned_speed*2
        report['controls'].append({'name': 'native-reentry-without-item', 'stomping_failure_not_carried': True,
            'unburden_not_reactivated': True, 'boosted_speed': boosted_speed, 'returned_speed': returned_speed})
    output = ROOT/'runs/v2-midgame-admission/inactive-controls-v1'
    output.mkdir(parents=True, exist_ok=True)
    (output/'controls.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
