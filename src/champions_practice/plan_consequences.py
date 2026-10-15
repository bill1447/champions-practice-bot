"""Measurements of hypothetical native outcomes, without plan utility weights."""

from .strategic_diagnostic import ident, resource_id


ROUTES = ('Gardevoir', 'Metagross', 'Armarouge')
BLOCKERS = ('Tyranitar', 'Excadrill')


def route_command_counts(view, menu, catalog):
    """Count legal damaging commands, independently of bounded probe coverage."""
    counts = {}
    active = view['player']['active_details']
    for route in ROUTES:
        def attacks(command):
            for slot, part in enumerate(command.split(',')):
                words = part.strip().split()
                if slot < len(active) and active[slot] and resource_id(active[slot]['species']) == resource_id(route):
                    if len(words) > 1 and words[0] == 'move' and catalog.moves.get(ident(words[1]), {}).get('category') in {'Physical', 'Special'}:
                        return True
            return False
        counts[route] = sum(attacks(command) for command in menu)
    return counts


def exact_log_lines(lines):
    """Use each native exact split message once, excluding its public duplicate."""
    index = 0
    while index < len(lines):
        if lines[index].startswith('|split|'):
            yield lines[index+1]
            index += 3
        else:
            yield lines[index]
            index += 1


def move_evidence(parent, child, own_view, enemy_view, side, catalog):
    """Attribute direct enemy damage to observed moves within supplied hypotheses.

    These are execution events, not inferred speed, damage ranges or live truth.
    Residual/recoil damage is excluded by native [from] provenance.
    """
    other = 'p2' if side == 'p1' else 'p1'
    slots = {}
    for prefix, view in ((side, own_view), (other, enemy_view)):
        for index, mon in enumerate(view['player']['active_details']):
            if mon:
                slots[prefix+chr(97+index)] = mon['species']
    actions, context = [], None
    for line in exact_log_lines(child['log'][len(parent['log']):]):
        parts = line.split('|')
        event = parts[1] if len(parts) > 1 else ''
        slot = parts[2].split(':')[0] if len(parts) > 2 else ''
        if event in {'switch', 'drag', 'detailschange', '-formechange'}:
            slots[slot] = parts[3].split(',')[0]
            context = None
        elif event == 'move':
            move = ident(parts[3])
            context = {'actor': slots.get(slot, slot), 'side': slot[:2], 'move': move,
                'damaging': catalog.moves.get(move, {}).get('category') in {'Physical', 'Special'},
                'direct_damage_targets': []}
            actions.append(context)
        elif event == '-damage' and context and context['damaging']:
            if slot[:2] != context['side'] and not any(p.startswith('[from]') for p in parts[4:]):
                context['direct_damage_targets'].append(slots.get(slot, slot))
        elif event in {'upkeep', 'turn', '-weather'}:
            context = None
    return actions


def measure_board(summary, side):
    other = 'p2' if side == 'p1' else 'p1'
    result = {'ended': summary['ended'], 'winner': summary['winner'], 'turn': summary['turn'],
        'field': summary['field'], 'routes': {}, 'blockers': {}}
    for label, prefix in (('own', side), ('enemy', other)):
        roster = summary[prefix]['pokemon']
        result[label+'_living'] = [m['species'] for m in roster if m['hp'] > 0 and not m['fainted']]
        result[label+'_hp'] = {resource_id(m['species']): m['hp']/max(1, m['maxhp']) for m in roster}
        result[label+'_active'] = [{k: m[k] for k in ('species', 'hp', 'maxhp', 'speed', 'grounded')}
                                  for m in summary[prefix]['active'] if m and m['hp'] > 0]
    for route in ROUTES:
        key = resource_id(route)
        result['routes'][route] = {'selected': key in result['own_hp'],
            'living': result['own_hp'].get(key, 0) > 0,
            'hp_fraction': result['own_hp'].get(key),
            'active': any(resource_id(m['species']) == key for m in result['own_active'])}
    for blocker in BLOCKERS:
        result['blockers'][blocker] = result['enemy_hp'].get(resource_id(blocker))
    return result


def measure_transition(parent, outcome, own_view, enemy_view, side, catalog):
    board = measure_board(outcome['summary'], side)
    actions = move_evidence(parent, outcome['state'], own_view, enemy_view, side, catalog)
    board['move_order'] = actions
    for route, status in board['routes'].items():
        own_moves = [(i, a) for i, a in enumerate(actions)
                     if a['side'] == side and resource_id(a['actor']) == resource_id(route) and a['damaging']]
        enemy_moves = [i for i, a in enumerate(actions) if a['side'] != side and a['damaging']]
        status.update(damaging_move_executed=bool(own_moves),
            direct_enemy_damage=any(a['direct_damage_targets'] for _, a in own_moves),
            acted_before_enemy_damage_move=bool(own_moves) and (not enemy_moves or own_moves[0][0] < min(enemy_moves)))
        status['productive_surviving_attack'] = status['living'] and status['direct_enemy_damage']
    initial_enemy = len(enemy_view['player']['team'])
    initial_own = len(own_view['player']['team'])
    board['enemy_fainted_total'] = initial_enemy-len(board['enemy_living'])
    board['own_fainted_total'] = initial_own-len(board['own_living'])
    return board


def summarize_opportunities(probes):
    """Report existence within a bounded probe; never treat absence as impossibility."""
    report = {}
    for route in ROUTES:
        actions = sorted({p['action'] for p in probes})
        productive = [p for p in probes if p['measurement']['routes'][route]['productive_surviving_attack']]
        common = [a for a in actions if all(p['measurement']['routes'][route]['productive_surviving_attack']
                                           for p in probes if p['action'] == a)]
        report[route] = {'productive_samples': len(productive),
            'sampled_common_actions': common,
            'witness': {'action': productive[0]['action'], 'reply': productive[0]['reply']} if productive else None,
            'interpretation': 'Bounded native samples only; no proof of plan viability or impossibility.'}
    return report
