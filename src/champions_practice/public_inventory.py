"""Bounded opposing consumption history; no transfer/removal inference."""

from .public_lifecycle import ordered_public_lifecycle


def ident(value):
    return ''.join(c for c in str(value or '').lower() if c.isalnum())


def public_inventory_plan(view, ledger):
    """None means unresolved; [] means no public opposing inventory lifecycle.

    Resistance berries emit an eat/weaken pair for ONE consumption. Missing,
    duplicated, transferred or unknown item events do not license restoration.
    Flags at the supported boundary follow native endTurn/switch-out semantics.
    """
    ordered = ordered_public_lifecycle(view, ledger)
    if ordered is None:
        return None
    consumed, skipped = {}, set()
    for index, (turn, event, actors) in enumerate(ordered):
        if index in skipped:
            continue
        kind = event[0]
        if kind in {'switch', 'drag'}:
            for entry in consumed.values():
                if entry['actor'] == event[1]:
                    entry['used_this_turn'] = False
        if kind not in {'-item', '-enditem'} or not event[1].startswith('p1'):
            continue
        if kind != '-enditem' or len(event) < 3:
            return None
        actor, item = event[1:3]
        species = actors.get(actor)
        key = ident(species)
        if not key or key in consumed:
            return None
        if item == 'focussash':
            if len(event) != 3:
                return None
        elif item == 'sitrusberry':
            if event[3:] != ['[eat]']:
                return None
        elif item in {'shucaberry', 'colburberry'}:
            if event[3:] != ['[eat]'] or index+1 >= len(ordered):
                return None
            next_turn, next_event, next_actors = ordered[index+1]
            if (next_turn != turn or next_event != ['-enditem', actor, item, '[weaken]']
                    or ident(next_actors.get(actor)) != key):
                return None
            skipped.add(index+1)
        else:
            return None
        consumed[key] = {'species': species, 'item': item, 'ate_berry': item != 'focussash',
                         'used_this_turn': turn == view['turn'], 'actor': actor}
    return [{k: v for k, v in entry.items() if k != 'actor'} for entry in consumed.values()]


def native_inventory_rejection(state, plan):
    """Independent serialized-state checks; projection equality cannot prove this."""
    if plan is None:
        return 'unsupported-persistent:opponent-inventory'
    expected = {ident(entry['species']): entry for entry in plan}
    members = state['sides'][0]['pokemon']
    if not set(expected) <= {ident(mon['set']['species']) for mon in members}:
        return 'unsupported-persistent:inventory-member'
    for index, mon in enumerate(members):
        entry = expected.get(ident(mon['set']['species']))
        if entry:
            if (ident(mon['set']['item']) != entry['item'] or mon['item'] != ''
                    or mon['lastItem'] != entry['item'] or mon['ateBerry'] is not entry['ate_berry']
                    or mon['usedItemThisTurn'] is not entry['used_this_turn']):
                return 'unsupported-persistent:inventory-state'
            effect = mon['itemState']
            target = f"[Pokemon:{state['sides'][0].get('id', 'p1')}{chr(97+index)}]"
            if (effect.get('id') != '' or effect.get('target') != target
                    or any(k not in {'id', 'target', 'effectOrder'} for k in effect)
                    or effect.get('effectOrder', 0) != 0):
                return 'unsupported-persistent:inventory-effect-state'
        elif (ident(mon['item']) != ident(mon['set'].get('item')) or mon.get('lastItem')
              or mon.get('ateBerry') or mon.get('usedItemThisTurn')):
            return 'unsupported-persistent:unobserved-inventory-change'
    return None
