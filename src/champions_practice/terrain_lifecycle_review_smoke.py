"""Additional terrain source/reactivation controls against offline native oracles."""

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.present_mechanics import opening_terrain_plan
from champions_practice.public_lifecycle import public_protection_plan
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM


def main():
    previews = {side: ["Indeedee-F", "Sneasler", "Gardevoir", "Armarouge", "Rillaboom", "Metagross"]
                for side in ('p1', 'p2')}
    cases = (
        ('same-terrain-no-refresh', SMOKE_TEAM, 'team 5231',
         ['switch 3, move protect', 'switch 3, move protect']),
        ('overwrite-and-reactivate', SMOKE_TEAM, 'team 2145',
         ['switch 4, switch 3', 'switch 3, move protect', 'switch 3, move protect']),
        ('retained-extender', SMOKE_TEAM.replace('Colbur Berry', 'Terrain Extender'), 'team 2135',
         ['move protect, move followme', 'move protect, move followme']),
    )
    with ShowdownSearchWorker() as worker:
        for name, team, preview, commands in cases:
            root = worker.create_state(battle_format=CHAMPIONS_FORMAT, p1_team=team, p2_team=team,
                p1_preview=preview, p2_preview=preview,
                seed='sodium,00000001000000020000000300000004')
            current = root
            ledger = PublicConstraintLedger.from_public_view(worker.state_view(state=root, side='p2', previews=previews))
            durations = []
            for command in commands:
                current = worker.branch_many(state=current, branches=[{
                    'p1_choice': command, 'p2_choice': command, 'include_state': True,
                }])[0]['state']
                view = worker.state_view(state=current, side='p2', previews=previews)
                ledger = ledger.advance(view)
                plan = opening_terrain_plan(view, ledger)
                assert plan is not None, (name, view['public_event_delta'])
                repaired = worker.materialize_present_hypotheses(state=root, current_view=view,
                    mechanics_plan=plan, protection_plan=public_protection_plan(view, ledger), limit=4)
                assert repaired['outcomes'], (name, repaired.get('reason'), repaired.get('mismatch_path'))
                expected = current['field']['terrainState']['duration']
                durations.append(expected)
                assert all(entry['state']['field']['terrainState']['duration'] == expected
                           for entry in repaired['outcomes'])
            assert durations == ({'same-terrain-no-refresh': [4, 3],
                                  'overwrite-and-reactivate': [4, 4, 4],
                                  'retained-extender': [7, 6]}[name]), (name, durations)
            print(f'Pinned terrain review {name}: {durations}')
    print('RESULT: same-terrain entry, overwrite/reactivation and retained-extension native controls passed')


if __name__ == '__main__':
    main()
