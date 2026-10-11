"""Public Trace and Trick Room plans against pinned native lifecycle oracles."""

from copy import deepcopy

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.present_mechanics import (
    opening_terrain_plan, public_trick_room_plan, unsupported_present_mechanics,
)
from champions_practice.public_lifecycle import (
    public_opponent_mega_plan, public_protection_plan, public_trace_plan,
)
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM
from champions_practice.uncertain_fixture import opponent_team


PREVIEWS = {side: ['Indeedee-F', 'Sneasler', 'Gardevoir', 'Armarouge', 'Rillaboom', 'Metagross']
            for side in ('p1', 'p2')}
SEED = 'sodium,00000001000000020000000300000004'


def plans(view, ledger):
    return dict(mechanics_plan=opening_terrain_plan(view, ledger),
                trick_room_plan=public_trick_room_plan(view, ledger),
                trace_plan=public_trace_plan(view, ledger),
                opponent_mega_plan=public_opponent_mega_plan(view, ledger),
                protection_plan=public_protection_plan(view, ledger))


def check(worker, root, current, view, ledger):
    assert unsupported_present_mechanics(view, ledger) is None, (view['turn'], view['phase'], unsupported_present_mechanics(view, ledger), view['public_event_delta'])
    result = worker.materialize_present_hypotheses(state=root, current_view=view, **plans(view, ledger))
    assert result['outcomes'], (view['turn'], result.get('reason'), result.get('mismatch_path'))
    for entry in result['outcomes']:
        state = entry['state']
        projected = worker.state_view(state=state, side='p2', previews=PREVIEWS)
        assert projected['player'] == view['player']
        assert projected['request'] == view['request']
        assert projected['field'] == view['field']
        assert worker.legal_choices(state=state, side='p2') == worker.legal_choices(state=current, side='p2')
        for key in ('terrainState',):
            if view['field']['terrain']:
                assert state['field'][key]['duration'] == current['field'][key]['duration']
        expected = current['field']['pseudoWeather'].get('trickroom')
        actual = state['field']['pseudoWeather'].get('trickroom')
        assert bool(expected) == bool(actual)
        if expected:
            assert actual['duration'] == expected['duration']
        # All exact-set abilities and Mega forms here are offline controls.
        # Neither these native values nor native counters enter public plans.
        for side in (0, 1):
            for slot in (0, 1):
                assert state['sides'][side]['pokemon'][slot]['ability'] == current['sides'][side]['pokemon'][slot]['ability']
        for entry in public_opponent_mega_plan(view, ledger) or []:
            mon = next(mon for mon in state['sides'][0]['pokemon']
                       if mon['set']['species'].lower() == entry['species'])
            assert mon['ability'] == 'pixilate'
            assert mon['species'] == '[Species:gardevoirmega]'
    return result


def main():
    with ShowdownSearchWorker() as worker:
        for subject in ('p1', 'p2'):
            root = worker.create_state(battle_format=CHAMPIONS_FORMAT,
                p1_team=SMOKE_TEAM, p2_team=SMOKE_TEAM,
                p1_preview='team 2135', p2_preview='team 2135', seed=SEED)
            current = root
            ledger = PublicConstraintLedger.from_public_view(worker.state_view(state=root, side='p2', previews=PREVIEWS))
            for index, command in enumerate(('switch 4, move followme', 'switch 3, move followme',
                    'move protect mega, move followme', 'switch 4, move followme',
                    'switch 4, move followme', 'move protect, move followme')):
                other = 'p2' if subject == 'p1' else 'p1'
                current = worker.branch_many(state=current, branches=[{
                    subject + '_choice': command, other + '_choice': 'move protect, move followme',
                    'include_state': True,
                }])[0]['state']
                view = worker.state_view(state=current, side='p2', previews=PREVIEWS)
                ledger = ledger.advance(view)
                check(worker, root, current, view, ledger)
                terrain = opening_terrain_plan(view, ledger)
                if index in {1, 2, 3, 4}:
                    assert terrain['source_origin_ability'] == 'trace'
                    assert terrain['residual_turns'] == index
                if index == 2:
                    assert not public_trace_plan(view, ledger)
                    invalid = deepcopy(terrain)
                    del invalid['source_origin_ability']
                    rejected = worker.materialize_present_hypotheses(state=root, current_view=view,
                        **{**plans(view, ledger), 'mechanics_plan': invalid})
                    assert not rejected['outcomes'] and rejected['reason'] == 'unsupported-terrain-source'
                if index == 5:
                    assert view['field']['terrain'] is None
            print(f'Pinned Trace {subject}: copy, Mega, bench/return and terrain expiration passed')

        for subject in ('p1', 'p2'):
            root = worker.create_state(battle_format=CHAMPIONS_FORMAT,
                p1_team=SMOKE_TEAM, p2_team=SMOKE_TEAM,
                p1_preview='team 2135', p2_preview='team 2135', seed=SEED)
            current = root
            ledger = PublicConstraintLedger.from_public_view(worker.state_view(state=root, side='p2', previews=PREVIEWS))
            durations = []
            for command in ('move protect, move trickroom', 'move protect, move trickroom',
                    'move protect, move trickroom', 'move protect, switch 4',
                    'move protect, move protect', 'move protect, move protect',
                    'move protect, move protect'):
                other = 'p2' if subject == 'p1' else 'p1'
                current = worker.branch_many(state=current, branches=[{
                    subject + '_choice': command, other + '_choice': 'move protect, move followme',
                    'include_state': True,
                }])[0]['state']
                view = worker.state_view(state=current, side='p2', previews=PREVIEWS)
                ledger = ledger.advance(view)
                check(worker, root, current, view, ledger)
                effect = current['field']['pseudoWeather'].get('trickroom')
                durations.append(effect['duration'] if effect else None)
            assert durations == [4, None, 4, 3, 2, 1, None], durations
            print(f'Pinned Trick Room {subject}: toggle, reactivation, source switch, joint terrain age and expiration passed')

        root = worker.create_state(battle_format=CHAMPIONS_FORMAT,
            p1_team=opponent_team(15601, 7), p2_team=SMOKE_TEAM,
            p1_preview='team 2135', p2_preview='team 2135',
            seed='sodium,c296fd46143d1aa91c244db38094c5af21075ee8d730fa84924fac4931967e73')
        current = root
        ledger = PublicConstraintLedger.from_public_view(worker.state_view(state=root, side='p2', previews=PREVIEWS))
        commands = (
            ('move rockslide, move psychic +2', 'move protect, switch 4'),
            ('move rockslide, move psychic +2', 'switch 4, move woodhammer +1'),
            ('move rockslide, move psychic +2', 'move psychic +1, switch 3'),
            ('move rockslide, move psychic +2', 'move psychic +1, move hypervoice mega'),
            ('switch 4, pass', 'pass, switch 3'),
            ('move woodhammer +2, move psychic +2', 'move trickroom, move woodhammer +2'),
            ('wait', 'pass, switch 4'),
            ('move woodhammer +2, move psychic +2', 'move psychic +2, move rockslide'),
            ('move woodhammer +2, move psychic +2', 'move psychic +2, pass'),
        )
        for index, (p1, p2) in enumerate(commands):
            current = worker.branch_many(state=current, branches=[{
                'p1_choice': p1, 'p2_choice': p2, 'include_state': True,
            }])[0]['state']
            view = worker.state_view(state=current, side='p2', previews=PREVIEWS)
            ledger = ledger.advance(view)
            if index >= 5 and view['phase'] != 'ended':
                check(worker, root, current, view, ledger)
        print('Pinned Trick Room: measured forced-replacement regression passed')

        team = SMOKE_TEAM.replace('Gardevoirite', 'Terrain Extender')
        root = worker.create_state(battle_format=CHAMPIONS_FORMAT, p1_team=team, p2_team=team,
            p1_preview='team 2135', p2_preview='team 2135', seed=SEED)
        current = root
        ledger = PublicConstraintLedger.from_public_view(worker.state_view(state=root, side='p2', previews=PREVIEWS))
        for command in ('switch 4, move followme', 'switch 3, move followme'):
            current = worker.branch_many(state=current, branches=[{
                'p1_choice': 'move protect, move followme', 'p2_choice': command, 'include_state': True,
            }])[0]['state']
            view = worker.state_view(state=current, side='p2', previews=PREVIEWS)
            ledger = ledger.advance(view)
            check(worker, root, current, view, ledger)
        assert current['field']['terrainState']['duration'] == 7
        print('Pinned Trace: retained extender duration passed')
    print('RESULT: Trace and Trick Room public/native lifecycle controls passed')


if __name__ == '__main__':
    main()
