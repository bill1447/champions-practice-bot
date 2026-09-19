"""Early local players used to prove the complete battle path."""

from __future__ import annotations

from poke_env.battle import AbstractBattle, DoubleBattle, Move
from poke_env.player import MaxBasePowerPlayer
from poke_env.player.battle_order import DoubleBattleOrder

from champions_practice.teams import SMOKE_TEAM_ORDER


class IntegrationBattlePlayer(MaxBasePowerPlayer):
    """Simple aggressive player with deterministic team preview and Mega usage.

    This is not the practice AI. Its only purpose is to drive a real Champions doubles
    battle to completion while exercising team preview and Mega Evolution.
    """

    def teampreview(self, battle: AbstractBattle) -> str:
        members = list(battle.team.values())
        for index in SMOKE_TEAM_ORDER:
            members[index - 1]._selected_in_teampreview = True
        return "/team " + "".join(str(index) for index in SMOKE_TEAM_ORDER)

    def choose_move(self, battle: AbstractBattle):
        order = super().choose_move(battle)

        if not isinstance(battle, DoubleBattle) or not isinstance(order, DoubleBattleOrder):
            return order

        slot_orders = (order.first_order, order.second_order)
        for can_mega, slot_order in zip(battle.can_mega_evolve, slot_orders):
            if can_mega and isinstance(slot_order.order, Move):
                slot_order.mega = True
                break

        return order
