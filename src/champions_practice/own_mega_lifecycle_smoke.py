"""Exact own Mega/ability/bench ordering through native lifecycle operations."""

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.present_mechanics import opening_terrain_plan
from champions_practice.public_lifecycle import public_protection_plan
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM


def main():
    previews = {side: ["Indeedee-F", "Sneasler", "Gardevoir", "Armarouge", "Rillaboom", "Metagross"]
                for side in ("p1", "p2")}
    with ShowdownSearchWorker() as worker:
        root = worker.create_state(battle_format=CHAMPIONS_FORMAT, p1_team=SMOKE_TEAM, p2_team=SMOKE_TEAM,
            p1_preview='team 2135', p2_preview='team 2135',
            seed='sodium,00000001000000020000000300000004')
        exercised = set()
        cases = (
            ('switch 3, move followme', 'move protect mega, move followme',
             'switch 3, move followme', 'switch 3, move followme'),
            ('move protect, switch 3', 'move protect, move protect mega',
             'move protect, switch 3', 'move protect, switch 3'),
        )
        for commands in cases:
            current = root
            ledger = PublicConstraintLedger.from_public_view(worker.state_view(state=root, side='p2', previews=previews))
            for command in commands:
                current = worker.branch_many(state=current, branches=[{
                    'p1_choice': 'move protect, move followme', 'p2_choice': command,
                    'include_state': True,
                }])[0]['state']
                view = worker.state_view(state=current, side='p2', previews=previews)
                ledger = ledger.advance(view)
                repaired = worker.materialize_present_hypotheses(state=root, current_view=view,
                    mechanics_plan=opening_terrain_plan(view, ledger),
                    protection_plan=public_protection_plan(view, ledger), limit=4)
                assert repaired['outcomes'], (command, repaired.get('reason'), repaired.get('mismatch_path'))
                for outcome in repaired['outcomes']:
                    for slot in range(2):
                        assert outcome['state']['sides'][1]['pokemon'][slot]['isStarted'] == current['sides'][1]['pokemon'][slot]['isStarted']
                    candidate = worker.state_view(state=outcome['state'], side='p2', previews=previews)
                    assert candidate['request'] == view['request']
                    assert candidate['player'] == view['player']
                    assert worker.legal_choices(state=outcome['state'], side='p2') == worker.legal_choices(state=current, side='p2')
                for mon in view['player']['team']:
                    if mon['species'] == 'Gardevoir-Mega':
                        exercised.add('active' if mon['active'] else 'bench')
                        assert mon['ability'] == 'pixilate'
        assert exercised == {'active', 'bench'}, exercised
    print('RESULT: exact own Mega evolution, bench/return, ability, reserve order and native roundtrip passed')


if __name__ == '__main__':
    main()
