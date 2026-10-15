from champions_practice.plan_consequences import (
    exact_log_lines, measure_transition, move_evidence, route_command_counts, summarize_opportunities,
)


class Catalog:
    moves = {'hypervoice': {'category': 'Special'}, 'ironhead': {'category': 'Physical'},
             'protect': {'category': 'Status'}}


def views():
    return ({'player': {'active_details': [{'species': 'Gardevoir-Mega'}], 'team': [{}]}},
            {'player': {'active_details': [{'species': 'Excadrill'}], 'team': [{}]}})


def test_exact_split_messages_are_not_counted_twice():
    lines = ['|move|p1a: Gardevoir|Hyper Voice|p2a: Excadrill', '|split|p2',
             '|-damage|p2a: Excadrill|50/187', '|-damage|p2a: Excadrill|26/100']
    assert list(exact_log_lines(lines)) == [lines[0], lines[2]]


def test_legal_command_coverage_distinguishes_absent_attacker_from_probe_omission():
    own, _ = views()
    menu = ['move protect', 'move hypervoice +1']
    assert route_command_counts(own, menu, Catalog())['Gardevoir'] == 1
    assert route_command_counts(own, menu[:1], Catalog())['Gardevoir'] == 0
    assert route_command_counts(own, menu, Catalog())['Metagross'] == 0


def test_direct_attack_is_distinguished_from_protect_and_residual_damage():
    own, enemy = views()
    parent = {'log': ['|turn|1']}
    child = {'log': parent['log']+['|move|p1a: Gardevoir|Protect|p1a: Gardevoir',
        '|move|p2a: Excadrill|Iron Head|p1a: Gardevoir',
        '|-activate|p1a: Gardevoir|move: Protect',
        '|-weather|Sandstorm|[upkeep]',
        '|-damage|p1a: Gardevoir|100/147|[from] Sandstorm']}
    evidence = move_evidence(parent, child, own, enemy, 'p1', Catalog())
    assert [a['move'] for a in evidence] == ['protect', 'ironhead']
    assert all(not a['direct_damage_targets'] for a in evidence)


def test_native_damage_and_order_preserve_mega_route_identity():
    own, enemy = views()
    parent = {'log': []}
    child = {'log': ['|move|p2a: Excadrill|Iron Head|p1a: Gardevoir',
        '|-damage|p1a: Gardevoir|20/147',
        '|move|p1a: Gardevoir|Hyper Voice|p2a: Excadrill',
        '|split|p2', '|-damage|p2a: Excadrill|0 fnt', '|-damage|p2a: Excadrill|0 fnt']}
    mon = {'species': 'Gardevoir-Mega', 'hp': 20, 'maxhp': 147, 'fainted': False,
           'speed': 130, 'grounded': True}
    foe = {**mon, 'species': 'Excadrill', 'hp': 0, 'maxhp': 187, 'fainted': True}
    summary = {'ended': False, 'winner': None, 'turn': 3, 'field': {},
        'p1': {'pokemon': [mon], 'active': [mon]},
        'p2': {'pokemon': [foe], 'active': [foe]}}
    measured = measure_transition(parent, {'state': child, 'summary': summary}, own, enemy, 'p1', Catalog())
    route = measured['routes']['Gardevoir']
    assert route['productive_surviving_attack']
    assert not route['acted_before_enemy_damage_move']
    assert measured['enemy_fainted_total'] == 1
    assert measured['routes']['Metagross']['selected'] is False
    assert measured['blockers']['Excadrill'] == 0


def test_common_action_requires_one_command_that_works_against_every_reply():
    def probe(action, reply, works):
        return {'action': action, 'reply': reply, 'measurement': {'routes': {
            name: {'productive_surviving_attack': works if name == 'Gardevoir' else False}
            for name in ('Gardevoir', 'Metagross', 'Armarouge')}}}
    rows = [probe('attack a', 'reply a', True), probe('attack a', 'reply b', False),
            probe('attack b', 'reply a', False), probe('attack b', 'reply b', True)]
    assert summarize_opportunities(rows)['Gardevoir']['sampled_common_actions'] == []
    rows[1] = probe('attack a', 'reply b', True)
    assert summarize_opportunities(rows)['Gardevoir']['sampled_common_actions'] == ['attack a']
    assert summarize_opportunities([])['Gardevoir']['witness'] is None
