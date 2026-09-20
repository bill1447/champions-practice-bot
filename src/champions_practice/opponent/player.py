"""First independently choosing doubles opponent."""

from __future__ import annotations

import logging

from poke_env.battle import AbstractBattle, DoubleBattle
from poke_env.player import Player

from champions_practice.opponent.actions import enumerate_joint_orders
from champions_practice.opponent.response import score_response_aware_order
from champions_practice.opponent.preview import choose_team_preview


class HeuristicOpponent(Player):
    """Choose team preview and turns from public battle information.

    The policy remains deliberately transparent. It does not inspect hidden opponent
    moves, items, abilities, spreads, or unrevealed bench information. Revealed opposing
    attacks are used to penalize fragile lines before the final action is selected.
    """

    def __init__(self, *args, trace_choices: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.trace_choices = trace_choices
        self.choice_logger = logging.getLogger("champions_practice.opponent")

    def teampreview(self, battle: AbstractBattle) -> str:
        team = list(battle.team.values())
        opponents = list(battle.teampreview_opponent_team)

        best, ranking = choose_team_preview(team, opponents)

        for index in best.order:
            team[index - 1]._selected_in_teampreview = True

        if self.trace_choices:
            self.choice_logger.warning(
                "preview chosen=%s score=%.3f reasons=%s top5=%s",
                best.order,
                best.score,
                best.reasons,
                [
                    (choice.order, round(choice.score, 3), choice.reasons)
                    for choice in ranking[:5]
                ],
            )

        return "/team " + "".join(str(index) for index in best.order)

    def choose_move(self, battle: AbstractBattle):
        if not isinstance(battle, DoubleBattle):
            return self.choose_random_move(battle)

        joint_orders = enumerate_joint_orders(battle)
        if not joint_orders:
            return self.choose_random_move(battle)

        scored = [score_response_aware_order(battle, order) for order in joint_orders]
        best = max(scored, key=lambda candidate: (candidate.score, candidate.order.message))

        if self.trace_choices:
            leaders = sorted(
                scored,
                key=lambda candidate: candidate.score,
                reverse=True,
            )[:5]
            self.choice_logger.warning(
                "turn=%s candidates=%s chosen=%.2f %s reasons=%s top5=%s",
                battle.turn,
                len(scored),
                best.score,
                best.order.message,
                best.reasons,
                [
                    (round(candidate.score, 2), candidate.order.message)
                    for candidate in leaders
                ],
            )

        return best.order
