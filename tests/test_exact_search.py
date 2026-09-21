from typing import Any

import pytest

from champions_practice.exact_search import score_exact_summary, search_exact_turn


def _pokemon(hp: int, maxhp: int = 100) -> dict[str, Any]:
    return {
        "species": "Testmon",
        "hp": hp,
        "maxhp": maxhp,
        "fainted": hp == 0,
        "status": "fnt" if hp == 0 else None,
    }


def _summary(
    p1_hp: list[int],
    p2_hp: list[int],
    *,
    ended: bool = False,
    winner: str | None = None,
) -> dict[str, Any]:
    return {
        "ended": ended,
        "winner": winner,
        "p1": {"name": "Player One", "pokemon": [_pokemon(hp) for hp in p1_hp]},
        "p2": {"name": "Player Two", "pokemon": [_pokemon(hp) for hp in p2_hp]},
    }


class FakeWorker:
    def __init__(self, outcomes: dict[tuple[str, str], dict[str, Any]]):
        self.outcomes = outcomes
        self.requested: list[dict[str, str]] = []

    def branch_many(self, *, state, branches):
        self.requested = branches
        return [
            {
                "index": index,
                "summary": self.outcomes[(branch["p1_choice"], branch["p2_choice"])],
            }
            for index, branch in enumerate(branches)
        ]


def test_material_score_values_preserving_a_low_hp_pokemon() -> None:
    sacrificed = _summary([0, 70, 100, 100], [25, 0, 0, 0])
    preserved = _summary([15, 70, 100, 78], [24, 0, 0, 0])

    assert score_exact_summary(preserved, "p1") > score_exact_summary(
        sacrificed, "p1"
    )


def test_terminal_result_overrides_material() -> None:
    p1_win = _summary(
        [1, 0, 0, 0],
        [100, 100, 100, 100],
        ended=True,
        winner="Player One",
    )

    assert score_exact_summary(p1_win, "p1") == 1_000_000
    assert score_exact_summary(p1_win, "p2") == -1_000_000


def test_search_uses_worst_opponent_response_before_average() -> None:
    attack = "move psychic 1, move psychicfangs 1"
    switch = "switch 4, move psychicfangs 1"
    wood_hammer = "move woodhammer 1, pass"
    protect = "move protect, pass"

    outcomes = {
        (attack, wood_hammer): _summary([0, 70, 100, 100], [25, 0, 0, 0]),
        (attack, protect): _summary([15, 70, 100, 100], [70, 0, 0, 0]),
        (switch, wood_hammer): _summary([78, 70, 100, 15], [24, 0, 0, 0]),
        (switch, protect): _summary([100, 70, 100, 15], [70, 0, 0, 0]),
    }
    worker = FakeWorker(outcomes)

    result = search_exact_turn(
        worker,
        state={"exact": "snapshot"},
        side="p1",
        choices=[attack, switch],
        opponent_responses=[wood_hammer, protect],
    )

    assert result.chosen.choice == switch
    assert len(worker.requested) == 4
    assert result.ranking[0].worst_score > result.ranking[1].worst_score


def test_search_maps_ai_side_to_p2() -> None:
    ai_choice = "move psychic 1, move psychicfangs 1"
    human_response = "move protect, move protect"
    outcome = _summary([50, 50, 0, 0], [100, 100, 100, 100])
    worker = FakeWorker({(human_response, ai_choice): outcome})

    result = search_exact_turn(
        worker,
        state={},
        side="p2",
        choices=[ai_choice],
        opponent_responses=[human_response],
    )

    assert result.chosen.choice == ai_choice
    assert worker.requested == [
        {"p1_choice": human_response, "p2_choice": ai_choice}
    ]


@pytest.mark.parametrize(
    ("choices", "responses", "message"),
    [([], ["response"], "choices"), (["choice"], [], "opponent_responses")],
)
def test_search_rejects_empty_inputs(choices, responses, message) -> None:
    with pytest.raises(ValueError, match=message):
        search_exact_turn(
            FakeWorker({}),
            state={},
            side="p1",
            choices=choices,
            opponent_responses=responses,
        )
