"""Legal action enumeration for doubles battles."""

from __future__ import annotations

from poke_env.battle import DoubleBattle
from poke_env.player.battle_order import DoubleBattleOrder


def enumerate_joint_orders(battle: DoubleBattle) -> list[DoubleBattleOrder]:
    """Return every legal joint action exposed by poke-env for this battle state.

    poke-env already expands moves across valid targets and special mechanics such as
    Mega Evolution. DoubleBattleOrder.join_orders then removes impossible combinations
    such as double-Mega and switching both slots into the same bench Pokémon.
    """
    return DoubleBattleOrder.join_orders(*battle.valid_orders)
