"""First independently choosing doubles opponent."""

from __future__ import annotations

import logging

from poke_env.battle import AbstractBattle, DoubleBattle
from poke_env.player import Player

from champions_practice.opponent.actions import enumerate_joint_orders
from champions_practice.opponent.evaluator import score_joint_order


class HeuristicOpponent(Player):
    """Choose the highest-scoring legal joint doubles action.

    Version 0 is deliberately transparent rather than clever. It only consumes the
    public battle state exposed by poke-env, enumerates legal joint actions, and scores
    them with a small tactical heuristic.
    """

    def __init__(self, *args, trace_choices: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.trace_choices = trace_choices
        self.choice_logger = logging.getLogger("champions_practice.opponent")

    def choose_move(self, battle: AbstractBattle):
        if not isinstance(battle, DoubleBattle):
            return self.choose_random_move(battle)

        joint_orders = enumerate_joint_orders(battle)
        if not joint_orders:
            return self.choose_random_move(battle)

        scored = [score_joint_order(battle, order) for order in joint_orders]
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
