"""Lightweight opponent-response awareness.

This layer does not clone or simulate battle states. It reranks our legal actions by the
best *revealed* damaging responses the opposing active Pokemon could plausibly make.

Only information already exposed by poke-env is used. Unrevealed moves, items, spreads,
and bench Pokemon are not guessed here.
"""

from __future__ import annotations

from poke_env.battle import DoubleBattle, Move, MoveCategory, Pokemon, Target
from poke_env.player.battle_order import DoubleBattleOrder, SingleBattleOrder

from champions_practice.opponent.evaluator import (
    PROTECT_MOVES,
    ScoredOrder,
    _attack_value,
    score_joint_order,
)


def _revealed_damaging_moves(mon: Pokemon) -> list[Move]:
    return [
        move
        for move in mon.moves.values()
        if move.category != MoveCategory.STATUS and move.base_power > 0
    ]


def _resulting_slot_target(
    current: Pokemon | None,
    order: SingleBattleOrder,
) -> Pokemon | None:
    """Return the Pokemon expected to occupy a slot after an immediate switch."""
    if isinstance(order.order, Pokemon):
        return order.order
    return current


def _is_protecting(order: SingleBattleOrder) -> bool:
    return isinstance(order.order, Move) and order.order.id in PROTECT_MOVES


def _foe_position(battle: DoubleBattle, foe_index: int) -> int:
    return (
        battle.OPPONENT_1_POSITION
        if foe_index == 0
        else battle.OPPONENT_2_POSITION
    )


def _pressure_on_foe(
    battle: DoubleBattle,
    order: DoubleBattleOrder,
    foe_index: int,
) -> float:
    """Estimate how much immediate pressure our order puts on one active foe."""
    foe = battle.opponent_active_pokemon[foe_index]
    if foe is None or foe.fainted:
        return 0.0

    foe_position = _foe_position(battle, foe_index)
    pressure = 0.0

    for attacker, slot_order in zip(
        battle.active_pokemon,
        (order.first_order, order.second_order),
    ):
        if attacker is None or not isinstance(slot_order.order, Move):
            continue

        move = slot_order.order
        if move.category == MoveCategory.STATUS or move.base_power <= 0:
            continue

        if slot_order.move_target == foe_position:
            pressure += max(0.0, _attack_value(attacker, move, foe))
            continue

        if (
            slot_order.move_target == battle.EMPTY_TARGET_POSITION
            and move.target == Target.ALL_ADJACENT_FOES
        ):
            pressure += 0.75 * max(0.0, _attack_value(attacker, move, foe))

    return pressure


def _revealed_response_risk(
    battle: DoubleBattle,
    order: DoubleBattleOrder,
) -> tuple[float, tuple[str, ...]]:
    """Estimate downside against each foe's strongest currently revealed attack."""
    slot_orders = (order.first_order, order.second_order)
    resulting_targets = [
        _resulting_slot_target(current, slot_order)
        for current, slot_order in zip(battle.active_pokemon, slot_orders)
    ]

    total_risk = 0.0
    reasons: list[str] = []

    for foe_index, foe in enumerate(battle.opponent_active_pokemon):
        if foe is None or foe.fainted:
            continue

        revealed_moves = _revealed_damaging_moves(foe)
        if not revealed_moves:
            continue

        best_threat = 0.0
        best_label = ""

        for slot_index, target in enumerate(resulting_targets):
            if target is None or target.fainted:
                continue

            slot_threat = max(
                max(0.0, _attack_value(foe, move, target))
                for move in revealed_moves
            )

            # Protect is not guaranteed to be strategically correct, but against a
            # revealed high-damage response it should materially reduce immediate risk.
            if _is_protecting(slot_orders[slot_index]):
                slot_threat *= 0.15

            # Losing a low-HP Pokemon is more consequential than taking the same nominal
            # pressure at full health.
            slot_threat *= 1.0 + (1.0 - target.current_hp_fraction) * 0.35

            if slot_threat > best_threat:
                best_threat = slot_threat
                best_label = f"{foe.species}->{target.species}"

        if best_threat <= 0:
            continue

        # If our chosen order heavily pressures this foe, discount—but never erase—its
        # projected response. This is intentionally conservative because the attack may
        # miss, be Protected, or fail to KO.
        pressure = _pressure_on_foe(battle, order, foe_index)
        mitigation = min(0.65, pressure / 1400.0)
        adjusted = best_threat * (1.0 - mitigation)

        total_risk += adjusted
        reasons.append(
            f"response:{best_label}:{adjusted:.1f}"
        )

    return total_risk, tuple(reasons)


def score_response_aware_order(
    battle: DoubleBattle,
    order: DoubleBattleOrder,
    risk_weight: float = 0.28,
) -> ScoredOrder:
    """Blend immediate heuristic value with downside from revealed responses."""
    base = score_joint_order(battle, order)
    risk, response_reasons = _revealed_response_risk(battle, order)

    if risk <= 0:
        return base

    return ScoredOrder(
        order=order,
        score=base.score - risk_weight * risk,
        reasons=base.reasons
        + (f"response-risk:{risk:.1f}",)
        + response_reasons,
    )
