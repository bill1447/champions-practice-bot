"""Evaluation-only bridge to poke-env's independently implemented doubles baseline.

No V2 scoring imports, native state, enemy set, enemy command or battle RNG inputs.
Champions static metadata replaces vanilla metadata; upstream decisions are unmodified.
"""

from copy import deepcopy
import hashlib
from importlib.metadata import version
import inspect
import json
import logging
from pathlib import Path
import random
import subprocess

from poke_env.battle.double_battle import DoubleBattle
from poke_env.battle.effect import Effect
from poke_env.battle.field import Field
from poke_env.battle.move import Move
from poke_env.battle.pokemon import Pokemon
from poke_env.battle.pokemon_type import PokemonType
from poke_env.battle.side_condition import SideCondition
from poke_env.battle.weather import Weather
from poke_env.player.baselines import SimpleHeuristicsPlayer
from poke_env.player.battle_order import DoubleBattleOrder, PassBattleOrder


def ident(value):
    return ''.join(c for c in str(value).lower() if c.isalnum())


class ChampionsMove(Move):
    def __init__(self, move_id, dex):
        self._champions_entry = dex['moves'][ident(move_id)]
        super().__init__(ident(move_id), gen=9)

    @property
    def entry(self):
        return self._champions_entry


class ChampionsPokemon(Pokemon):
    def __init__(self, dex, **kwargs):
        self._champions_dex = dex
        super().__init__(gen=9, **kwargs)

    def _update_from_pokedex(self, species, store_species=True):
        species = ident(species)
        data = self._champions_dex['species'][species]
        if store_species:
            self._species = species
        self._base_stats = dict(data['baseStats'])
        self._type_1 = PokemonType.from_name(data['types'][0])
        self._type_2 = PokemonType.from_name(data['types'][1]) if len(data['types']) > 1 else None
        self._possible_abilities = [ident(a) for a in data['abilities'].values()]
        self._heightm, self._weightkg = data['heightm'], data['weightkg']
        self._learnset = frozenset()  # Only actual owned requests authorize moves.

    def _add_move(self, move_id):
        move_id = ident(move_id)
        if move_id not in self.moves:
            self.base_moves[move_id] = ChampionsMove(move_id, self._champions_dex)
        return self.moves[move_id]


def load_dex(root):
    text = subprocess.run(['node', str(root/'tools/independent-opponent-dex.js')],
                          capture_output=True, text=True, encoding='utf-8', check=True, timeout=30).stdout
    return json.loads(text)


def _public_mon(data, dex):
    # Deliberate allowlist: opponent injected hp/stats/item/ability/moves are ignored.
    mon = ChampionsPokemon(dex, species=data['species'], name=data['species'])
    mon._level = 50
    percent = data.get('hp_percent')
    percent = 100 if percent is None else percent
    mon.set_hp_status('0 fnt' if data.get('fainted') else f"{round(percent*100)}/10000")
    mon.status = 'fnt' if data.get('fainted') else data.get('status')
    mon._boosts.update({k: int(v) for k, v in data.get('boosts', {}).items() if k in mon._boosts})
    return mon


def make_battle(view, choices, dex):
    request = view['request']
    side = request['side']['id']
    other = 'p2' if side == 'p1' else 'p1'
    battle = DoubleBattle('offline-control', view['player']['name'], logging.getLogger('independent-control'), 9)
    battle._player_role = side
    battle._turn = view['turn']
    battle._max_team_size = 4
    battle._last_request = {}  # Never retain unrecognized request/root fields.
    own = []
    for entry in request['side']['pokemon']:
        # Own request is authorized, but unknown root keys never enter the policy.
        allowed = {k: deepcopy(entry[k]) for k in ('ident', 'details', 'condition', 'active',
                   'baseAbility', 'ability', 'item', 'moves', 'stats') if k in entry}
        mon = ChampionsPokemon(dex, request_pokemon=allowed)
        own.append(mon)
        battle._team[entry['ident']] = mon
    for slot, data in enumerate(view['player']['active_details']):
        if data:
            mon = next(m for m in own if m.species == ident(data['species']))
            mon._boosts.update({k: int(v) for k, v in data.get('boosts', {}).items() if k in mon._boosts})
            mon._active = True
            battle._active_pokemon[side+chr(97+slot)] = mon
    for data in view['opponent'].get('revealed', []):
        if data.get('seen'):
            mon = _public_mon(data, dex)
            battle._opponent_team[ident(dex['species'][mon.species]['baseSpecies'])] = mon
    for slot, data in enumerate(view['opponent']['active']):
        if data:
            mon = _public_mon(data, dex)
            mon._active = True
            battle._opponent_active_pokemon[other+chr(97+slot)] = mon
            battle._opponent_team[ident(dex['species'][mon.species]['baseSpecies'])] = mon
    battle._force_switch = list(request.get('forceSwitch', [False, False]))
    for slot in range(2):
        active = request.get('active', [])
        item = active[slot] if slot < len(active) else {}
        battle._can_mega_evolve[slot] = bool(item.get('canMegaEvo'))
        battle._trapped[slot] = bool(item.get('trapped'))
        for move in item.get('moves', []):
            if not move.get('disabled'):
                value = ChampionsMove(move['id'], dex)
                if 'target' in move:
                    value.request_target = move['target']
                battle._available_moves[slot].append(value)
        switch_indices = set()
        for choice in choices:
            parts = choice.split(',')
            command = parts[slot].strip().split() if slot < len(parts) else []
            if len(command) == 2 and command[0] == 'switch':
                switch_indices.add(int(command[1])-1)
        battle._available_switches[slot] = [own[i] for i in sorted(switch_indices)]
    field = view.get('field', {})
    if field.get('weather'):
        battle._weather = {Weather.from_showdown_message(field['weather']): view['turn']}
    for value in [field.get('terrain'), *field.get('pseudo_weather', [])]:
        if value:
            battle._fields[Field.from_showdown_message(value)] = view['turn']
    for label, target in [('player', battle._side_conditions), ('opponent', battle._opponent_side_conditions)]:
        for condition in view[label].get('side_conditions', []):
            target[SideCondition.from_showdown_message(condition)] = 1
    for slot, entry in enumerate(request['side']['pokemon'][:2]):
        if entry.get('commanding') and slot < len(battle.active_pokemon) and battle.active_pokemon[slot]:
            battle.active_pokemon[slot]._effects[Effect.COMMANDER] = 1
    return battle, own


def canonical_order(order, own):
    if not isinstance(order, DoubleBattleOrder):
        raise ValueError('upstream returned no doubles order')
    commands = []
    for part in (order.first_order, order.second_order):
        if isinstance(part, PassBattleOrder):
            commands.append('pass')
        elif isinstance(part.order, Move):
            value = 'move '+part.order.id
            if part.move_target:
                value += ' '+('+' if part.move_target > 0 else '')+str(part.move_target)
            if part.mega:
                value += ' mega'
            commands.append(value)
        elif isinstance(part.order, Pokemon):
            commands.append('switch '+str(next(i+1 for i, mon in enumerate(own) if mon is part.order)))
        else:
            raise ValueError('upstream requested default transport order')
    return ', '.join(commands)


class IndependentOpponent:
    def __init__(self, dex, seed):
        self.dex = dex
        self.rng = random.Random(seed)
        # No Player initialization, websocket client, account or live server.
        self.policy = object.__new__(SimpleHeuristicsPlayer)

    def choose(self, view, choices):
        if choices == ['wait']:
            return 'wait', {'mode': 'forced-wait', 'fallback': False}
        battle, own = make_battle(view, choices, self.dex)
        saved = random.getstate()
        random.setstate(self.rng.getstate())
        proposal, failure = None, None
        try:
            try:
                proposal = canonical_order(self.policy.choose_move(battle), own)
                if proposal not in choices:
                    failure = 'proposal-outside-authoritative-menu'
            except (ValueError, IndexError) as error:
                failure = type(error).__name__
            self.rng.setstate(random.getstate())
        finally:
            random.setstate(saved)
        action = self.rng.choice(choices) if failure else proposal
        assert action in choices
        return action, {'mode': 'adapted-upstream-simple-heuristics', 'proposal': proposal,
                        'fallback': bool(failure), 'fallback_reason': failure,
                        'upstream_policy_modified': False, 'mega_augmentation': False}


def identity(dex):
    path = Path(inspect.getsourcefile(SimpleHeuristicsPlayer))
    return {'package': 'poke-env', 'version': version('poke-env'),
            'upstream_baselines_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'champions_dex_sha256': hashlib.sha256(json.dumps(dex, sort_keys=True).encode()).hexdigest(),
            'adapter_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
