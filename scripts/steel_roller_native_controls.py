"""Pinned-native Steel Roller controls with public menu and policy checks."""

import hashlib
import json
from pathlib import Path
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog, observe
from champions_practice.agent_v2.policy import rank_action
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.diversity_league import team_text
from champions_practice.search_worker import ShowdownSearchWorker, TeamValidationWorker

ROOT = Path(__file__).resolve().parents[1]


def main():
    own = team_text(('Metagross', 'Dragonite', 'Indeedee-F', 'Rotom-Wash', 'Garchomp', 'Pelipper'))
    foe = team_text(('Garchomp', 'Dragonite', 'Metagross', 'Rotom-Wash', 'Incineroar', 'Venusaur'))
    metadata = PublicCatalog.load(ROOT)
    with TeamValidationWorker(ROOT) as validator:
        for team in (own, foe):
            assert validator.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=team)['valid']
    controls = []
    with ShowdownSearchWorker(ROOT) as worker:
        for name, preview, action, damage_expected in (
            ('absent', 'team 1234', 'move steelroller +1, move protect', False),
            ('present', 'team 1324', 'move steelroller +1, move psychic +2', True),
            ('switch_sets_terrain', 'team 1234', 'move steelroller +1, switch 3', True),
        ):
            session = worker.start_session(battle_format=CHAMPIONS_FORMAT,
                p1_team=own, p2_team=foe, p1_name='P1', p2_name='P2',
                seed='sodium,' + hashlib.sha256(name.encode()).hexdigest())['session_id']
            try:
                worker.choose_session(session, p1_choice=preview, p2_choice='team 1234')
                before = worker.session_view(session, side='p1')['view']
                choices = worker.session_public_choices(session, side='p1')
                assert action in choices, (name, action)
                board = observe(before, choices, deadline=perf_counter()+8)
                score = rank_action(action, board, metadata)
                worker.choose_session(session, p1_choice=action,
                                      p2_choice='move dragonclaw +2, move protect')
                after = worker.session_view(session, side='p1')['view']
                damage = before['opponent']['active'][0]['hp_percent'] - after['opponent']['active'][0]['hp_percent']
                assert (damage > 0) == damage_expected
                assert not after['field']['terrain']
                controls.append({'name': name, 'terrain_before': before['field']['terrain'],
                    'opponent_hp_percent_lost': damage, 'terrain_after': after['field']['terrain'],
                    'action_legal': True, 'score': score.score, 'reasons': score.reasons})
                if name == 'present':
                    # After successful removal, the same legal move must fail.
                    worker.choose_session(session, p1_choice=action,
                                          p2_choice='move dragonclaw +2, move protect')
                    cleared = worker.session_view(session, side='p1')['view']
                    assert cleared['opponent']['active'][0]['hp_percent'] == after['opponent']['active'][0]['hp_percent']
                    controls.append({'name': 'removed_previous_turn', 'no_further_damage': True})
            finally:
                worker.close_session(session)
    output = ROOT/'runs/v2-loss-review/native-controls.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(controls, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(controls, indent=2))


if __name__ == '__main__':
    main()
