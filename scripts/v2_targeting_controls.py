"""Offline native counterfactuals for two frozen loss-review leads; no policy input."""

import gzip
import hashlib
import json
from pathlib import Path

from champions_practice.competitive_evaluation import fixtures
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import ShowdownSearchWorker

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT/'reviews/competitive-evaluation-2026-10-12.json.gz'
    archive = json.loads(gzip.decompress(source.read_bytes()))
    _, teams = fixtures()
    report = {'archive_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'scope': 'Actual archived hidden state used only after decisions; not deployable inputs or win probabilities.',
              'cases': []}
    with ShowdownSearchWorker(ROOT) as worker:
        for game_id in ('pressure-0-0-p1-v2', 'pressure-0-0-p2-v2'):
            game = next(g for g in archive['games'] if g['id'] == game_id)
            side = next(s for s, a in game['agents'].items() if a == 'v2')
            other = 'p2' if side == 'p1' else 'p1'
            row = game['rows'][2]
            selected = row['sides'][side]['action']
            alternative = row['sides'][side]['tactical_diagnostic']['improving_alternatives'][0]
            session = worker.start_session(battle_format=CHAMPIONS_FORMAT,
                p1_team=teams[game['teams']['p1']], p2_team=teams[game['teams']['p2']],
                p1_name='P1', p2_name='P2', seed=game['battle_seed'])['session_id']
            try:
                worker.choose_session(session, p1_choice='team 1234', p2_choice='team 1234')
                for previous in game['rows'][:2]:
                    worker.choose_session(session, p1_choice=previous['sides']['p1']['action'],
                                          p2_choice=previous['sides']['p2']['action'])
                assert worker.session_view(session, side=side)['view'] == row['sides'][side]['view']
                state = worker.session_snapshot(session)['state']
                enemy_action = row['sides'][other]['action']
                parts = enemy_action.split(', ')
                replies = {'recorded': enemy_action, 'shield_slot_1': 'move protect, '+parts[1],
                           'shield_slot_2': parts[0]+', move protect', 'shield_both': 'move protect, move protect'}
                legal = worker.session_public_choices(session, side=other)
                case = {'id': game_id, 'turn': row['turn'], 'selected': selected,
                        'alternative': alternative, 'contexts': []}
                for context, reply in replies.items():
                    if reply not in legal:
                        continue
                    stats = {}
                    for label, command in [('selected', selected), ('alternative', alternative)]:
                        branches = []
                        for sample in range(8):
                            seed = 'sodium,'+hashlib.sha256(f'v2-targeting-control:{sample}'.encode()).hexdigest()
                            commands = {side: command, other: reply}
                            branches.append({'p1_choice': commands['p1'], 'p2_choice': commands['p2'],
                                             'rng_seed': seed, 'include_state': True})
                        outcomes = worker.branch_many(state=state, branches=branches)
                        material = []
                        for result in outcomes:
                            sides = result['state']['sides']
                            own = sides[0 if side == 'p1' else 1]['pokemon']
                            foe = sides[1 if side == 'p1' else 0]['pokemon']
                            material.append({'own_survivors': sum(m['hp'] > 0 for m in own),
                                             'foe_survivors': sum(m['hp'] > 0 for m in foe),
                                             'own_total_hp': sum(m['hp'] for m in own),
                                             'foe_total_hp': sum(m['hp'] for m in foe)})
                        stats[label] = material
                    case['contexts'].append({'context': context, 'reply': reply, 'samples': stats})
                report['cases'].append(case)
            finally:
                worker.close_session(session)
    output = ROOT/'runs/v2-loss-review/targeting-controls.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    for case in report['cases']:
        print(case['id'], case['selected'], 'versus', case['alternative'])
        for context in case['contexts']:
            print(context['context'], {label: {
                key: sum(s[key] for s in samples)/len(samples) for key in samples[0]}
                for label, samples in context['samples'].items()})


if __name__ == '__main__':
    main()
