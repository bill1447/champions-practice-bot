"""Champions reorders queued attacks after same-turn speed changes."""

from pathlib import Path
import re
from time import perf_counter

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.diversity_league import team_text
from champions_practice.plan_consequences import exact_log_lines
from champions_practice.search_worker import HypotheticalSearchWorker, TeamValidationWorker


def test_same_turn_tailwind_reorders_remaining_attacks():
    root = Path(__file__).resolve().parents[1]
    text = team_text(('Pelipper', 'Gardevoir', 'Rotom-Wash', 'Metagross', 'Indeedee-F', 'Venusaur'))
    chunks = text.strip().split('\n\n')
    for index in (1, 2):
        chunks[index] = re.sub(r'\d+ Spe', '0 Spe', chunks[index])
    text = '\n\n'.join(chunks)+'\n'
    with TeamValidationWorker(root, startup_deadline=perf_counter()+30) as validator:
        validated = validator.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=text)
        assert validated['valid'], validated
    with HypotheticalSearchWorker(root, startup_deadline=perf_counter()+30) as worker:
        state = worker.create_state(battle_format=CHAMPIONS_FORMAT, p1_team=text, p2_team=text,
            p1_preview='team 1256', p2_preview='team 3465', seed='sodium,'+'12345678'*8)
        for setup, expected in (
            ('tailwind', ['p1b', 'p2a']),
            ('protect', ['p2a', 'p1b']),
        ):
            own, foe = f'move {setup}, move mysticalfire +1', 'move thunderbolt +1, move protect'
            assert own in worker.legal_choices(state=state, side='p1')
            assert foe in worker.legal_choices(state=state, side='p2')
            result = worker.branch_many(state=state, branches=[{'p1_choice': own, 'p2_choice': foe,
                'rng_seed': 'sodium,'+'12345678'*8, 'include_state': True}])[0]
            events = [line.split('|') for line in exact_log_lines(result['state']['log'][len(state['log']):])
                      if line.startswith('|move|')]
            assert any(event[2].startswith('p1a:') and event[3].lower() == setup for event in events)
            order = [event[2].split(':')[0] for event in events if event[2].split(':')[0] in ('p1b', 'p2a')]
            assert order == expected
