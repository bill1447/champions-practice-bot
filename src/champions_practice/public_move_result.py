"""Narrow public witnesses for Stomping Tantrum's previous-turn result.

No damage calculation or hidden target is inferred. Positive direct damage,
explicit failure, ordinary Protect blocking and a fresh switch have distinct
native meanings. Unrecognized/multiple actions remain unresolved.
"""

import json

from champions_practice.public_lifecycle import ordered_public_lifecycle


def sid(value):
    return ''.join(c for c in str(value or '').lower() if c.isalnum())


def public_move_result_plan(view, ledger):
    """Return certified entries only; an absent entry is NOT a success.

    The first scope is ordinary move selection after a complete public turn.
    Replacement pauses retain a separate current-turn result and remain closed.
    """
    if view.get('phase') != 'move':
        return None
    ordered = ordered_public_lifecycle(view, ledger)
    if ordered is None:
        return None
    openings = [json.loads(p) for t, p in ledger.field_snapshots if t == 1]
    if not openings or openings[0].get('phase') != 'move' or openings[0].get(
            'public_event_delta', {}).get('events'):
        return None
    previous = view['turn']-1
    events = [e for t, e, _ in ordered if t == previous]
    if previous:
        boundaries = [i for i, e in enumerate(events) if e == ['upkeep']]
        if len(boundaries) != 1 or any(e[0] in {'move', 'cant', '-mega', 'upkeep'}
                for e in events[boundaries[0]+1:]):
            return None
        # Public replacement entries may follow upkeep before endTurn. They
        # reset the incoming member; they do not erase other members' result.
    result, attempts = {}, {}
    if previous == 0:
        for side, prefix in (('player', 'p2'), ('opponent', 'p1')):
            for slot, name in enumerate(openings[0].get('active_species', {}).get(side, [])):
                if name:
                    result[prefix+chr(97+slot)] = 'undefined'
    else:
        # With complete events, no move/cant/mega entry means no move result.
        for prefix in ('p1', 'p2'):
            for suffix in ('a', 'b'):
                result[prefix+suffix] = 'undefined'
    context = None

    def finish():
        if context is None:
            return
        actor, evidence = context
        if attempts[actor] != 1:
            result[actor] = 'unresolved'
        elif 'success' in evidence:
            result[actor] = 'true'
        elif 'failure' in evidence:
            result[actor] = 'false'
        elif 'protected' in evidence:
            result[actor] = 'null'
        else:
            result[actor] = 'unresolved'

    for event in events:
        kind = event[0]
        actor = event[1] if len(event) > 1 else None
        if kind in {'move', 'cant', 'switch', 'drag', 'upkeep'}:
            finish()
            context = None
        if kind in {'switch', 'drag'}:
            result[actor] = 'undefined'
            attempts.pop(actor, None)
        elif kind == '-mega':
            result[actor] = 'true'
        elif kind == 'cant':
            attempts[actor] = attempts.get(actor, 0)+1
            result[actor] = ('false' if event[2] in {'flinch', 'par', 'frz'}
                             and attempts[actor] == 1 else 'unresolved')
        elif kind == 'move':
            attempts[actor] = attempts.get(actor, 0)+1
            context = (actor, set())
        elif kind == '-activate' and len(event) >= 3 and event[2] == 'confusion':
            # Confusion can abort before the producer emits move/cant. Its
            # counter is outside this contract; absence of move is no reset.
            finish()
            context = None
            result[actor] = 'unresolved'
        elif context:
            source, evidence = context
            # Recoil, abilities, weather, status and item HP changes cannot
            # certify that this move connected. Nested/called moves are gated
            # independently by the closed capability/support contracts.
            if kind == '-damage' and len(event) == 3:
                evidence.add('success')
            elif kind == '-singleturn' and actor == source and len(event) >= 3 and event[2].removeprefix('move:') in {
                    'protect', 'detect', 'endure', 'followme'}:
                evidence.add('success')
            elif kind in {'-fail', '-miss', '-notarget'} and actor == source:
                evidence.add('failure')
            elif kind == '-immune':
                evidence.add('failure')
            elif kind == '-activate' and len(event) >= 3 and event[2] in {'move:protect', 'move:detect'}:
                evidence.add('protected')
    finish()
    plan = []
    for side, prefix, key in (('player', 'p2', 'active_details'), ('opponent', 'p1', 'active')):
        for slot, mon in enumerate(view[side].get(key, [])):
            if not mon or mon.get('fainted'):
                continue
            actor = prefix+chr(97+slot)
            if result.get(actor) in {'undefined', 'true', 'false', 'null'}:
                plan.append({'side': side, 'slot': slot,
                    'species': mon.get('base_species', mon['species']), 'result': result[actor]})
    return plan
