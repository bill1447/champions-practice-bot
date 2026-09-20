"""Transparent first-pass heuristic for legal doubles actions.

This is intentionally small and inspectable. It does not attempt to simulate the turn.
Showdown remains the authority for actual mechanics and battle resolution.
"""

from __future__ import annotations

from dataclasses import dataclass

from poke_env.battle import DoubleBattle, Field, Move, MoveCategory, Pokemon, Target
from poke_env.player.battle_order import DoubleBattleOrder, SingleBattleOrder


PROTECT_MOVES = {
    "protect",
    "detect",
    "spikyshield",
    "kingsshield",
    "banefulbunker",
    "silktrap",
    "burningbulwark",
    "obstruct",
}

SPEED_CONTROL_MOVES = {"tailwind", "trickroom"}
REDIRECTION_MOVES = {"followme", "ragepowder"}
DEFENSIVE_SPREAD_MOVES = {"wideguard", "quickguard"}

SPREAD_FOE_TARGETS = {Target.ALL_ADJACENT_FOES}
SPREAD_WITH_ALLY_TARGETS = {Target.ALL, Target.ALL_ADJACENT}
TERRAIN_FIELDS = {
    Field.ELECTRIC_TERRAIN,
    Field.GRASSY_TERRAIN,
    Field.MISTY_TERRAIN,
    Field.PSYCHIC_TERRAIN,
}


@dataclass(frozen=True)
class ScoredOrder:
    order: DoubleBattleOrder
    score: float
    reasons: tuple[str, ...] = ()


def _target_for_position(battle: DoubleBattle, position: int) -> tuple[str, Pokemon | None]:
    """Resolve a Showdown doubles target position.

    Positive positions are foes, negative positions are our own active slots, and zero
    means the move does not require an explicit target.
    """
    if position == battle.OPPONENT_1_POSITION:
        return "foe", battle.opponent_active_pokemon[0]
    if position == battle.OPPONENT_2_POSITION:
        return "foe", battle.opponent_active_pokemon[1]
    if position == battle.POKEMON_1_POSITION:
        return "ally", battle.active_pokemon[0]
    if position == battle.POKEMON_2_POSITION:
        return "ally", battle.active_pokemon[1]
    return "none", None


def _attack_value(attacker: Pokemon, move: Move, target: Pokemon) -> float:
    """Estimate offensive value without pretending to be an exact damage calculator."""
    if target.fainted:
        return 0.0

    effectiveness = target.damage_multiplier(move)
    if effectiveness == 0:
        return -35.0

    stab = 1.5 if move.type in attacker.types else 1.0
    hp_pressure = 1.0 + (1.0 - target.current_hp_fraction) * 0.4
    expected_hits = getattr(move, "expected_hits", 1.0) or 1.0

    value = (
        move.base_power
        * move.accuracy
        * expected_hits
        * effectiveness
        * stab
        * hp_pressure
    )

    # Type advantage should be tactically visible even before we have exact damage.
    if effectiveness >= 4:
        value += 70.0
    elif effectiveness >= 2:
        value += 30.0
    elif effectiveness < 1:
        value -= 12.0

    # Reward attacks into already-damaged targets because converting damage into KOs
    # matters more than distributing chip indefinitely.
    if target.current_hp_fraction <= 0.35:
        value += 35.0
    elif target.current_hp_fraction <= 0.60:
        value += 15.0

    return value


def _status_value(battle: DoubleBattle, move: Move, attacker: Pokemon) -> float:
    move_id = move.id

    if move_id == "trickroom" and Field.TRICK_ROOM in battle.fields:
        # Clicking Trick Room while it is already active ends it. That can be correct in
        # a real position, but v0 has no speed-state search yet, so don't blindly toggle it.
        return -12.0

    if move_id in PROTECT_MOVES:
        # A low-health Pokémon has a stronger reason to preserve itself, but we keep the
        # baseline low so the v0 policy does not mindlessly Protect every turn.
        return 8.0 + (28.0 if attacker.current_hp_fraction <= 0.35 else 0.0)
    if move_id in SPEED_CONTROL_MOVES:
        return 22.0
    if move_id in REDIRECTION_MOVES:
        return 16.0
    if move_id in DEFENSIVE_SPREAD_MOVES:
        return 12.0
    if move_id == "imprison":
        return 8.0
    if move_id == "helpinghand":
        return 18.0

    # Unknown status moves are not forbidden; they simply need explicit knowledge later
    # before this evaluator will strongly prefer them.
    return 3.0


def score_single_order(
    battle: DoubleBattle,
    attacker: Pokemon | None,
    order: SingleBattleOrder,
) -> tuple[float, str]:
    """Score one slot of a doubles order."""
    choice = order.order

    if isinstance(choice, Pokemon):
        # Preserve switching as a legal escape hatch, but don't pivot constantly until
        # we implement matchup-aware switch scoring.
        hp_bonus = choice.current_hp_fraction * 4.0
        return -8.0 + hp_bonus, f"switch:{choice.species}"

    if not isinstance(choice, Move) or attacker is None:
        return 0.0, "pass/default"

    if choice.category == MoveCategory.STATUS or choice.base_power <= 0:
        value = _status_value(battle, choice, attacker)
        if order.mega:
            # Never spend the once-per-battle Mega action on a status move unless the
            # engine leaves no better option.
            value -= 8.0
        return value, f"status:{choice.id}"

    # Showdown exposes Steel Roller as a legal move even when no terrain exists, but the
    # move fails in that state. A base-power heuristic otherwise becomes obsessed with it.
    if choice.id == "steelroller" and not any(
        terrain in battle.fields for terrain in TERRAIN_FIELDS
    ):
        return -800.0, "fail:steelroller-no-terrain"


    if order.move_target != battle.EMPTY_TARGET_POSITION:
        side, target = _target_for_position(battle, order.move_target)
        if target is None:
            return -25.0, f"attack:{choice.id}:empty"

        if side == "ally":
            # In Showdown doubles, negative targets are our own active slots. The v0
            # evaluator previously treated every non-positive target as a spread move,
            # which made attacks like Psychic -2 and Steel Roller -1 look excellent.
            # Do not intentionally damage our partner until we explicitly model niche
            # ally-target strategies.
            if choice.id == "pollenpuff":
                missing_hp = 1.0 - target.current_hp_fraction
                return 80.0 * missing_hp, f"heal:pollenpuff->{target.species}"
            return -500.0, f"friendly-fire:{choice.id}->{target.species}"

        value = _attack_value(attacker, choice, target)
        reason = f"attack:{choice.id}->{target.species}"
    else:
        targets = [
            mon
            for mon in battle.opponent_active_pokemon
            if mon is not None and not mon.fainted
        ]
        if not targets:
            return -25.0, f"attack:{choice.id}:no-foes"

        # For no-explicit-target attacks, score all opposing Pokémon. Standard doubles
        # spread damage is reduced, so approximate that here rather than pretending the
        # displayed BP applies in full to both targets.
        spread_factor = 0.75 if choice.target in SPREAD_FOE_TARGETS | SPREAD_WITH_ALLY_TARGETS else 1.0
        value = sum(_attack_value(attacker, choice, target) for target in targets)
        value *= spread_factor

        if choice.target in SPREAD_WITH_ALLY_TARGETS:
            # Earthquake/Surf-style moves may also hurt our partner. Exact immunity and
            # absorption logic comes later; for now make indiscriminate spread less free.
            value -= 35.0

        reason = f"spread:{choice.id}"

    if choice.id == "expandingforce" and Field.PSYCHIC_TERRAIN in battle.fields:
        value += 35.0
        reason += ":psychic-terrain"
    elif choice.id == "grassyglide" and Field.GRASSY_TERRAIN in battle.fields:
        value += 22.0
        reason += ":grassy-terrain"

    if order.mega:
        # A small proactive bonus helps exercise Mega-capable lines without making Mega
        # automatically override a much better non-Mega action.
        value += 12.0
        reason += ":mega"

    return value, reason


def score_joint_order(battle: DoubleBattle, order: DoubleBattleOrder) -> ScoredOrder:
    """Score one complete two-slot decision."""
    attackers = battle.active_pokemon
    slot_orders = (order.first_order, order.second_order)

    score = 0.0
    reasons: list[str] = []
    for attacker, slot_order in zip(attackers, slot_orders):
        slot_score, reason = score_single_order(battle, attacker, slot_order)
        score += slot_score
        reasons.append(reason)

    # Discourage blindly double-Protecting in ordinary positions. It remains legal and
    # can still win when both individual Protect values are high.
    protected = 0
    for slot_order in slot_orders:
        choice = slot_order.order
        if isinstance(choice, Move) and choice.id in PROTECT_MOVES:
            protected += 1
    if protected == 2:
        score -= 14.0
        reasons.append("double-protect-penalty")

    return ScoredOrder(order=order, score=score, reasons=tuple(reasons))
