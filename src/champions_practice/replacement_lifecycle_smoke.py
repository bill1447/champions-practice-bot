"""Native replacement, post-upkeep terrain and last living member controls."""

from copy import deepcopy

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.demo_fixture import DEMO_AI_TEAM, DEMO_AI_PREVIEW_CHOICE
from champions_practice.present_mechanics import opening_terrain_plan, unsupported_present_mechanics
from champions_practice.public_lifecycle import public_protection_plan
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.uncertain_fixture import opponent_team


def main():
    # Frozen public choices from the recovery regression, independent of the
    # bot's current search and wall-clock budget. Native state is an offline
    # oracle only; constructors receive a fresh root and sanitized public view.
    commands = (
        ('move rockslide, move psychic +2', 'move protect, switch 4'),
        ('move rockslide, move psychic +2', 'switch 4, move woodhammer +1'),
        ('move rockslide, move psychic +2', 'move psychic +1, switch 3'),
        ('move rockslide, move psychic +2', 'move psychic +1, move hypervoice mega'),
        ('switch 4, pass', 'pass, switch 4'),
        ('move woodhammer +2, move psychic +2', 'move followme, move closecombat +1'),
        ('wait', 'switch 3, pass'),
        ('move woodhammer +2, move psychic +2', 'move grassyglide +2, move direclaw +2'),
        ('pass, switch 3', 'wait'),
        ('move woodhammer +2, move mysticalfire +2 mega', 'move protect, move protect'),
        ('move woodhammer +2, move mysticalfire +2', 'move protect, move protect'),
        ('move woodhammer +2, move mysticalfire +2', 'move woodhammer +2, pass'),
    )
    previews = {side: ['Indeedee-F', 'Sneasler', 'Gardevoir', 'Armarouge', 'Rillaboom', 'Metagross']
                for side in ('p1', 'p2')}
    with ShowdownSearchWorker() as worker:
        root = worker.create_state(battle_format=CHAMPIONS_FORMAT,
            p1_team=opponent_team(15601, 7), p2_team=DEMO_AI_TEAM,
            p1_preview=DEMO_AI_PREVIEW_CHOICE, p2_preview=DEMO_AI_PREVIEW_CHOICE,
            seed='sodium,c296fd46143d1aa91c244db38094c5af21075ee8d730fa84924fac4931967e73')
        current = root
        ledger = None
        confirmed = set()
        for index, (p1, p2) in enumerate(commands):
            view = worker.state_view(state=current, side='p2', previews=previews)
            ledger = PublicConstraintLedger.from_public_view(view) if ledger is None else ledger.advance(view)
            branch = {'p1_choice': p1, 'p2_choice': p2, 'include_state': True}
            following = worker.branch_many(state=current, branches=[branch])[0]['state']
            if index in {4, 6, 11}:
                assert unsupported_present_mechanics(view, ledger) is None
                rebuilt = worker.materialize_present_hypotheses(state=root, current_view=view,
                    protection_plan=public_protection_plan(view, ledger),
                    mechanics_plan=opening_terrain_plan(view, ledger))
                assert rebuilt['outcomes'], (index, rebuilt.get('reason'), rebuilt.get('mismatch_path'))
                for outcome in rebuilt['outcomes']:
                    candidate = outcome['state']
                    projected = worker.state_view(state=candidate, side='p2', previews=previews)
                    assert projected['player'] == view['player']
                    assert projected['request'] == view['request']
                    assert worker.legal_choices(state=candidate, side='p2') == worker.legal_choices(state=current, side='p2')
                    assert candidate['field']['terrainState']['duration'] == current['field']['terrainState']['duration']
                    if index in {4, 6}:
                        assert candidate['midTurn'] and candidate['queue'] == []
                        resumed = worker.branch_many(state=candidate, branches=[branch])[0]['state']
                        assert resumed['turn'] == following['turn'] == view['turn'] + 1
                        assert resumed['field']['terrainState']['duration'] == following['field']['terrainState']['duration']
                        for side in (0, 1):
                            for slot in (0, 1):
                                actual = resumed['sides'][side]['pokemon'][slot]['volatiles'].get('stall')
                                expected = following['sides'][side]['pokemon'][slot]['volatiles'].get('stall')
                                assert bool(actual) == bool(expected)
                    else:
                        assert sum(mon['hp'] > 0 for mon in view['player']['team']) == 1
                        assert not candidate['sides'][1]['pokemon'][1]['isActive']
                confirmed.add(index)
                if index == 4:
                    incomplete = deepcopy(view)
                    incomplete['public_event_delta']['events'].pop()
                    rejected = worker.materialize_present_hypotheses(state=root, current_view=incomplete)
                    assert not rejected['outcomes']
                    assert unsupported_present_mechanics(incomplete, ledger) == 'unsupported-public-switch-boundary'
            current = following
        assert confirmed == {4, 6, 11}
    print('RESULT: native replacements, single residual, post-upkeep terrain, fainted Mega and last living member passed')


if __name__ == '__main__':
    main()
