"""Public protection inference versus pinned native offline lifecycle oracles."""

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.present_mechanics import opening_terrain_plan, unsupported_present_mechanics
from champions_practice.public_lifecycle import public_protection_plan
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM


def main():
    confirmed = set()
    previews = {side: ["Indeedee-F", "Sneasler", "Gardevoir", "Armarouge", "Rillaboom", "Metagross"]
                for side in ("p1", "p2")}
    with ShowdownSearchWorker() as worker:
        for guard, preview in (("protect", "team 2135"), ("endure", "team 2135"),
                               ("wideguard", "team 4135")):
            team = SMOKE_TEAM.replace('- Protect', '- Endure') if guard == 'endure' else SMOKE_TEAM
            for seed in range(1, 5):
                root = worker.create_state(battle_format=CHAMPIONS_FORMAT, p1_team=team, p2_team=team,
                    p1_preview=preview, p2_preview=preview,
                    seed=f'sodium,{seed:08x}000000020000000300000004')
                current = root
                ledger = PublicConstraintLedger.from_public_view(worker.state_view(
                    state=current, side='p2', previews=previews))
                commands = ([f'move {guard}, move followme'] * (8 if guard == 'wideguard' and seed == 1 else 2)
                            + ['switch 3, move followme', 'switch 3, move followme'])
                for command in commands:
                    current = worker.branch_many(state=current, branches=[{
                        'p1_choice': command, 'p2_choice': command, 'include_state': True,
                    }])[0]['state']
                    view = worker.state_view(state=current, side='p2', previews=previews)
                    ledger = ledger.advance(view)
                    plan = public_protection_plan(view, ledger)
                    assert plan is not None, (guard, seed, view['public_event_delta'])
                    assert unsupported_present_mechanics(view, ledger) is None
                    repaired = worker.materialize_present_hypotheses(state=root, current_view=view,
                        protection_plan=plan, mechanics_plan=opening_terrain_plan(view, ledger), limit=4)
                    assert repaired['outcomes'], repaired.get('reason')
                    for entry in repaired['outcomes']:
                        candidate = entry['state']
                        for side_index in (0, 1):
                            for position in range(2):
                                expected = current['sides'][side_index]['pokemon'][position]['volatiles'].get('stall')
                                actual = candidate['sides'][side_index]['pokemon'][position]['volatiles'].get('stall')
                                assert bool(expected) == bool(actual), (guard, seed, position)
                                if expected:
                                    assert (actual['counter'], actual['duration']) == (expected['counter'], expected['duration'])
                                    confirmed.add('chain' if expected['counter'] > 3 else 'success')
                                elif view['turn'] == 3:
                                    confirmed.add('failed-attempt')
                    if command.startswith('switch'):
                        confirmed.add('switch-reset')
        assert {'success', 'chain', 'failed-attempt', 'switch-reset'} <= confirmed, confirmed
    print('RESULT: Protect/Endure/Wide Guard success, failure, repeat, switch/reset and native roundtrip passed')


if __name__ == '__main__':
    main()
