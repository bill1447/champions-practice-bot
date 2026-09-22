"""Tests for replay-based midgame belief reconstruction."""

from champions_practice.belief_worlds import (
    PublicTurnChoice,
    reconstruct_midgame_belief_worlds,
)


class FakeWorker:
    def __init__(self):
        self.created = []
        self.branches = []

    def create_state(self, **kwargs):
        self.created.append(kwargs)
        return {"team": kwargs["p1_team"], "turn": 1}

    def branch_many(self, *, state, branches):
        self.branches.append((state, branches))
        next_state = dict(state)
        next_state["turn"] += 1
        next_state["last"] = branches[0]
        return [{"state": next_state}]


def test_public_turn_choice_is_immutable():
    turn = PublicTurnChoice("move a, move b", "move c, move d", "seed")
    assert turn.p1_choice == "move a, move b"
    assert turn.rng_seed == "seed"
