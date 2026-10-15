"""A scarce reserve permits one vacancy, not skipping every replacement."""

from pathlib import Path
from time import perf_counter

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.diversity_league import team_text
from champions_practice.search_worker import ShowdownSearchWorker


def test_two_fainted_actives_one_reserve_requires_exactly_one_switch():
    own = team_text(('Indeedee-F', 'Gardevoir', 'Metagross', 'Venusaur', 'Armarouge', 'Sneasler')).replace('Stomping Tantrum', 'Earthquake')
    enemy = team_text(('Tyranitar', 'Excadrill', 'Rotom-Wash', 'Incineroar', 'Garchomp', 'Dragonite')).replace('Stomping Tantrum', 'Earthquake')
    enemy = enemy.replace('Protect', 'Substitute').replace('Life Orb', 'Sitrus Berry')
    commands = [
        ('move rockslide, move rockslide', 'move trickroom, move protect mega'),
        ('move rockslide, move rockslide', 'switch 3, move mysticalfire +2'),
        ('wait', 'pass, switch 4'),
        ('move rockslide, move rockslide', 'move steelroller +1, move energyball +1'),
        ('switch 3, switch 4', 'wait'),
        ('move earthquake, move earthquake', 'move psychicfangs +1, move energyball +1'),
        ('pass, move earthquake', 'move psychicfangs +2, move sludgebomb +2'),
    ]
    root = Path(__file__).resolve().parents[1]
    with ShowdownSearchWorker(root, startup_deadline=perf_counter()+30) as worker:
        session = worker.start_session(battle_format=CHAMPIONS_FORMAT, p1_team=enemy, p2_team=own,
            p1_name='P1', p2_name='P2',
            seed='sodium,08cbefab711c912b392ce2f6d4a08ac80777c0941f407692da664af96162c717')['session_id']
        try:
            worker.choose_session(session, p1_choice='team 1256', p2_choice='team 1234')
            for first, second in commands:
                worker.choose_session(session, p1_choice=first, p2_choice=second)
            view = worker.session_view(session, side='p2')['view']
            assert view['request']['forceSwitch'] == [True, True]
            menu = worker.session_public_choices(session, side='p2')
            assert menu == ['pass, switch 3', 'switch 3, pass']
            worker.choose_session(session, p1_choice='wait', p2_choice=menu[0])
        finally:
            worker.close_session(session)
