"""Legal native move controls for effective Speed versus action ordering."""

from dataclasses import asdict
import hashlib
import json
from time import perf_counter

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.diversity_league import team_text
from champions_practice.exact_search import score_exact_summary_breakdown
from champions_practice.plan_consequences import exact_log_lines
from champions_practice.search_worker import HypotheticalSearchWorker, TeamValidationWorker
from champions_practice.strategy_evidence import _favorable_speed_control
from tactical_consequences_evaluation import ROOT


def seed(label):
    return 'sodium,'+hashlib.sha256(label.encode()).hexdigest()


def main():
    text = team_text(('Gardevoir', 'Indeedee-F', 'Pelipper', 'Dragonite', 'Rotom-Wash', 'Metagross'))
    text = '\n\n'.join(chunk.replace('- Stomping Tantrum', '- Dragon Dance') if chunk.startswith('Dragonite') else chunk
                        for chunk in text.split('\n\n'))
    text = text.replace('- Imprison', '- Protect')
    text = text.replace('- Will-O-Wisp', '- Thunder Wave')
    with TeamValidationWorker(ROOT, startup_deadline=perf_counter()+60) as validator:
        result = validator.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=text)
        assert result['valid'], result
    cases = (
        ('normal', 'team 1263', 'team 4521', None),
        ('trick-room', 'team 1263', 'team 4521', ('move protect, move trickroom', 'move protect, move protect')),
        ('tailwind', 'team 1324', 'team 4521', ('move protect, move tailwind', 'move protect, move protect')),
        ('paralysis', 'team 1263', 'team 5421', ('move mysticalfire +2, move protect', 'move thunderwave +1, move protect')),
        ('boost', 'team 4261', 'team 1263', ('move dragondance, move protect', 'move protect, move protect')),
        ('mega', 'team 1263', 'team 4521', ('move protect mega, move protect', 'move protect, move protect')),
        ('tailwind-room', 'team 1324', 'team 4521', ('move protect, move tailwind', 'move protect, move protect')),
    )
    report = {'team_validated': True, 'team_sha256': hashlib.sha256(text.encode()).hexdigest(),
        'controls': [], 'source_sha256': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in (
            'scripts/native_speed_controls.py', 'tools/showdown-search-worker.js',
            'src/champions_practice/exact_search.py', 'src/champions_practice/native_speed.py',
            'src/champions_practice/strategy_evidence.py')}}
    with HypotheticalSearchWorker(ROOT, startup_deadline=perf_counter()+60) as worker:
        def branch(state, p1, p2, label):
            for side, action in (('p1', p1), ('p2', p2)):
                assert action in worker.legal_choices(state=state, side=side), (side, action)
            return worker.branch_many(state=state, branches=[{'p1_choice': p1, 'p2_choice': p2,
                'rng_seed': seed(label), 'include_state': True}])[0]

        for name, own_preview, foe_preview, setup in cases:
            state = worker.create_state(battle_format=CHAMPIONS_FORMAT, p1_team=text, p2_team=text,
                p1_preview=own_preview, p2_preview=foe_preview, seed=seed(name), p1_name='P1', p2_name='P2')
            initial = branch(state, 'move protect, move protect', 'move protect, move protect', name+':initial')
            current = initial
            if setup:
                for sample in range(16):
                    current = branch(initial['state'], *setup, f'{name}:setup:{sample}')
                    if name != 'paralysis' or current['summary']['p1']['active'][0]['status'] == 'par':
                        break
                else:
                    raise AssertionError('native paralysis control did not activate')
            if name == 'tailwind-room':
                # Indeedee enters via native switching, then establishes Room.
                current = branch(current['state'], 'move protect, switch 3', 'move protect, move protect', name+':switch')
                current = branch(current['state'], 'move protect, move trickroom', 'move protect, move protect', name+':room')
            summary = current['summary']
            own, foe = summary['p1']['active'][0], summary['p2']['active'][0]
            base = initial['summary']['p1']['active'][0]['effectiveSpeed']
            expected = {'normal': base, 'trick-room': base, 'tailwind': base*2,
                'tailwind-room': base*2, 'paralysis': base//2,
                'boost': base*3//2, 'mega': 150}[name]
            assert own['effectiveSpeed'] == expected, (name, own, expected)
            room = 'trickroom' in summary['field']['pseudoWeather']
            for side in ('p1', 'p2'):
                for mon in summary[side]['active']:
                    assert mon['actionOrderSpeed'] == (-mon['effectiveSpeed'] if room else mon['effectiveSpeed'])
                    assert mon['speed'] == mon['cachedActionOrderSpeed']
            commands = ('move dragonclaw +1, move protect', 'move mysticalfire +1, move protect') if name == 'boost' else (
                'move mysticalfire +1, move protect',
                'move thunderbolt +1, move protect' if name == 'paralysis' else 'move dragonclaw +1, move protect')
            for sample in range(16):
                probe = branch(current['state'], *commands, f'{name}:order:{sample}')
                order = []
                for line in exact_log_lines(probe['state']['log'][len(current['state']['log']):]):
                    parts = line.split('|')
                    if len(parts) > 2 and parts[1] in {'move', 'cant'}:
                        actor = parts[2].split(':')[0]
                        if actor in {'p1a', 'p2a'} and actor not in order:
                            order.append(actor)
                if len(order) == 2:
                    break
            assert len(order) == 2
            assert own['actionOrderSpeed'] != foe['actionOrderSpeed']
            assert (order[0] == 'p1a') == (own['actionOrderSpeed'] > foe['actionOrderSpeed']), (name, order)
            # Isolate one actor per side to test evaluator contract rather than team-average strategy.
            isolated = {**summary, 'p1': {**summary['p1'], 'active': [own]},
                         'p2': {**summary['p2'], 'active': [foe]}}
            score = score_exact_summary_breakdown(isolated, 'p1')
            assert (score.speed > 0) == (order[0] == 'p1a'), (name, score, order)
            assert _favorable_speed_control(isolated, 'p1') == (order[0] == 'p1a')
            report['controls'].append({'name': name, 'baseline_effective_speed': base,
                'own': own, 'foe': foe, 'actual_actor_order': order, 'score': asdict(score),
                'field': summary['field'], 'native_status': own['status'], 'boosts': own['boosts']})
            print(name, own['effectiveSpeed'], own['actionOrderSpeed'], order, 'PASS', flush=True)
    output = ROOT/'runs/v2-speed-contract/native-v1'
    output.mkdir(parents=True, exist_ok=True)
    (output/'controls.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
