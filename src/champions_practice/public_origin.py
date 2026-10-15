"""Read-only public origin for already admitted hypothetical native roots.

Construction logs are not observed battle history. This adapter changes views,
never native states, admission, legal menus, summaries or branch mechanics.
"""

from copy import deepcopy
import hashlib
import json
from math import floor

from .beliefs import build_public_opponent_belief
from .current_state_proposals import _require_current_public_input
from .present_rebase import _positive_mechanics_rejection
from .public_lifecycle import ordered_public_lifecycle
from .strategic_diagnostic import ident, resource_id


def state_key(state):
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


class PublicOriginWorker:
    def __init__(self, worker, *, states, current_view, ledger, previews, legal_actions):
        # Fresh admission uses the canonical p2 own-side layout.
        if current_view['request']['side']['id'] != 'p2':
            raise ValueError('public-origin adapter requires canonical p2 admission')
        build_public_opponent_belief(current_view)
        _require_current_public_input(ledger, current_view)
        ordered = ordered_public_lifecycle(current_view, ledger)
        if ordered is None:
            raise ValueError('complete public lifecycle required')
        self.worker, self.previews, self.origins = worker, previews, {}
        public_own = {}
        for species in previews['p2']:
            public_own[resource_id(species)] = {'species': species, 'moves': [], 'items': [],
                'abilities': [], 'hp_percent': None, 'status': None, 'fainted': False, 'seen': False}
        # Derive what our opponent has seen from the actual public channel,
        # never from our private move list or helper construction messages.
        for _, event, actors in ordered:
            for actor, species in actors.items():
                if actor.startswith('p2') and resource_id(species) in public_own:
                    public_own[resource_id(species)]['seen'] = True
            if len(event) > 2 and event[1].startswith('p2'):
                known = public_own.get(resource_id(actors.get(event[1], '')))
                key = {'move': 'moves', '-item': 'items', '-enditem': 'items', '-ability': 'abilities'}.get(event[0])
                if known is not None and key:
                    known[key] = sorted(set(known[key]) | {ident(event[2])})
        own_active = []
        for mon in current_view['player']['active_details']:
            if not mon:
                own_active.append(None)
                continue
            base = public_own[resource_id(mon['species'])]['species']
            hp = 0 if mon['fainted'] else max(1, floor(mon['hp']*100/mon['maxhp']))
            own_active.append({'species': mon['species'], 'base_species': base, 'hp_percent': hp,
                'fainted': mon['fainted'], 'status': mon['status'], 'boosts': deepcopy(mon['boosts'])})
        for mon in current_view['player']['team']:
            known = public_own[resource_id(mon['species'])]
            if known['seen']:
                known.update(hp_percent=0 if mon['fainted'] else max(1, floor(mon['hp']*100/mon['maxhp'])),
                             status=mon['status'], fainted=mon['fainted'])
        for state in states:
            focal = worker.state_view(state=state, side='p2', previews=previews)
            issue = _positive_mechanics_rejection(state, focal, current_view=current_view,
                ledger=ledger, legal_live=tuple(legal_actions),
                hypothetical_legal=worker.legal_choices(state=state, side='p2'))
            if issue:
                raise ValueError('public origin cannot bypass native admission: '+issue)
            reverse = worker.state_view(state=state, side='p1', previews=previews)
            reverse['opponent'] = {'name': current_view['player']['name'], 'preview_species': previews['p2'],
                'active': own_active, 'revealed': list(public_own.values()),
                'side_conditions': deepcopy(current_view['player']['side_conditions'])}
            reverse['public_event_delta'] = deepcopy(current_view['public_event_delta'])
            reverse['public_execution_delta'] = deepcopy(current_view['public_execution_delta'])
            for action in reverse['public_execution_delta'].get('actions', []):
                action['side'] = {'player': 'opponent', 'opponent': 'player'}[action['side']]
            reverse['opponent_last_actions'] = []
            self.origins[state_key(state)] = {side: {'log_offset': len(state['log']), 'view': deepcopy(view)}
                for side, view in (('p2', current_view), ('p1', reverse))}

    def state_view(self, *, state, side):
        origin = self.origins[state_key(state)][side]
        return self.worker.state_view(state=state, side=side, previews=self.previews, public_origin=origin)

    def legal_choices(self, **kwargs):
        return self.worker.legal_choices(**kwargs)

    def branch_many(self, *, state, branches):
        parent_key = state_key(state)
        origin = self.origins[parent_key]
        outcomes = self.worker.branch_many(state=state, branches=branches)
        if state_key(state) != parent_key:
            raise ValueError('native branch mutated parent state')
        for outcome in outcomes:
            if 'state' in outcome:
                self.origins[state_key(outcome['state'])] = origin
        return outcomes
