from typing import Any

import pytest

from champions_practice.exact_search import ExactChoiceScore
from champions_practice.recommendations import (
    _diversified_top,
    _reference_choices,
    _strategy_families,
    _strategy_signature,
    recommend_exact_turn_perfect_information,
)


def _pokemon(hp: int) -> dict[str, Any]:
    return {
        "species": "Testmon",
        "hp": hp,
        "maxhp": 100,
        "fainted": hp == 0,
        "status": "fnt" if hp == 0 else None,
    }


def _summary(p1_hp: int, p2_hp: int) -> dict[str, Any]:
    return {
        "ended": False,
        "winner": None,
        "p1": {"name": "P1", "pokemon": [_pokemon(p1_hp)]},
        "p2": {"name": "P2", "pokemon": [_pokemon(p2_hp)]},
    }


class FakeWorker:
    choices = {
        "p1": [
            "move psychic +1, move protect",
            "move psychic +2, move protect",
            "move followme, move rockslide",
            "switch 3, move rockslide",
        ],
        "p2": [
            "move woodhammer +1, move protect",
            "move woodhammer +2, move protect",
            "move protect, move protect",
            "switch 3, move protect",
        ],
    }

    def legal_choices(self, *, state, side):
        return self.choices[side]

    def branch_many(self, *, state, branches):
        results = []
        for index, branch in enumerate(branches):
            p1_hp = 100 if "switch" in branch["p1_choice"] else 70
            p2_hp = 100 if "switch" in branch["p2_choice"] else 60
            results.append({"index": index, "summary": _summary(p1_hp, p2_hp)})
        return results


def _candidate(choice: str, score: float) -> ExactChoiceScore:
    return ExactChoiceScore(
        choice=choice,
        worst_score=score,
        mean_score=score,
        best_score=score,
        branches=(),
    )


def test_strategy_signature_ignores_targets_but_keeps_mega() -> None:
    base = _strategy_signature("move psychic +1, move steelroller +2")
    other_target = _strategy_signature("move psychic +2, move steelroller +1")
    mega = _strategy_signature("move psychic +2, move steelroller +1 mega")

    assert base == other_target
    assert base != mega


def test_strategy_families_collapse_targets_and_prefer_split_enemy_targets() -> None:
    choices = [
        "move psychic +1, move steelroller +1 mega",
        "move psychic +1, move steelroller +2 mega",
        "move psychic +2, move steelroller +1 mega",
        "move protect, move steelroller +1 mega",
    ]

    families = _strategy_families(choices)

    assert len(families) == 2
    assert len(families[0].choices) == 3
    assert families[0].representative in {
        "move psychic +1, move steelroller +2 mega",
        "move psychic +2, move steelroller +1 mega",
    }


def test_reference_choices_include_varied_action_classes() -> None:
    choices = FakeWorker.choices["p1"] + [
        "move psychic +1, move rockslide mega"
    ]

    selected = _reference_choices(choices, 3)

    assert len(selected) == 3
    assert any("switch" in choice for choice in selected)
    assert any("protect" in choice or "followme" in choice for choice in selected)
    assert any("mega" in choice for choice in selected)


def test_diversified_top_adds_a_distinct_strategy() -> None:
    ranking = (
        _candidate("move psychic +1, move protect", 10),
        _candidate("move psychic +2, move protect", 9),
        _candidate("switch 3, move protect", 8),
    )

    selected = _diversified_top(ranking, 2)

    assert selected == [
        "move psychic +1, move protect",
        "switch 3, move protect",
    ]


def test_perfect_information_recommendation_is_bounded() -> None:
    recommendation = recommend_exact_turn_perfect_information(
        FakeWorker(),
        state={"exact": "snapshot"},
        side="p1",
        candidate_limit=3,
        response_limit=3,
        reference_limit=2,
    )

    assert recommendation.mode == "perfect_information"
    assert recommendation.legal_choice_count == 4
    assert recommendation.legal_response_count == 4
    assert recommendation.strategic_choice_count == 3
    assert recommendation.strategic_response_count == 3
    assert len(recommendation.candidate_shortlist) == 3
    assert len(recommendation.response_shortlist) == 3
    assert recommendation.rng_sample_count == 3
    assert recommendation.final_branch_count == 27
    assert recommendation.result.chosen.choice in recommendation.candidate_shortlist


@pytest.mark.parametrize(
    ("limit_name", "limit_value"),
    [
        ("candidate_limit", 0),
        ("response_limit", 0),
        ("family_limit", 0),
        ("reference_limit", 0),
    ],
)
def test_perfect_information_recommendation_rejects_nonpositive_limits(
    limit_name: str,
    limit_value: int,
) -> None:
    limits = {limit_name: limit_value}

    with pytest.raises(ValueError, match="limit must be positive"):
        recommend_exact_turn_perfect_information(
            FakeWorker(),
            state={"exact": "snapshot"},
            side="p1",
            **limits,
        )
