import pytest

from champions_practice.belief_search import (
    BeliefChoiceScore,
    BeliefPruningResult,
    BeliefPruningScore,
    BeliefSearchResult,
    BeliefSearchTiming,
    BeliefWorldOutcome,
)
from champions_practice.exact_search import ExactScoreBreakdown
from champions_practice.position_report import (
    build_public_battle_position,
    format_belief_search_evidence,
    format_public_battle_position,
)


def _view() -> dict:
    return {
        "turn": 4,
        "phase": "move",
        "field": {
            "weather": "raindance",
            "terrain": "psychicterrain",
            "pseudo_weather": ["trickroom"],
        },
        "player": {
            "name": "Practice AI",
            "side_conditions": ["reflect"],
            "active_details": [
                {
                    "species": "Indeedee-F",
                    "hp_percent": 42.4,
                    "status": None,
                    "boosts": {"spa": 1, "spe": 0},
                    "fainted": False,
                },
                {
                    "species": "Sneasler",
                    "hp_percent": 100,
                    "status": "par",
                    "boosts": {"atk": -1},
                    "fainted": False,
                },
            ],
        },
        "opponent": {
            "name": "Human",
            "side_conditions": ["tailwind"],
            "active": [
                {
                    "species": "Rillaboom",
                    "base_species": "Rillaboom",
                    "hp_percent": 67,
                    "status": None,
                    "boosts": {},
                    "fainted": False,
                },
                {
                    "species": "Metagross-Mega",
                    "base_species": "Metagross",
                    "hp_percent": 88,
                    "status": None,
                    "boosts": {"def": 2},
                    "fainted": False,
                },
            ],
        },
    }


def test_public_position_includes_field_actives_status_and_boosts() -> None:
    position = build_public_battle_position(_view())

    assert position.turn == 4
    assert position.player.active[0].boosts == (("spa", 1),)
    assert position.opponent.active[1].boosts == (("def", 2),)

    rendered = format_public_battle_position(position)
    assert "terrain Psychic Terrain" in rendered
    assert "weather Rain" in rendered
    assert "other Trick Room" in rendered
    assert "Sneasler — 100%; status paralyzed; boosts Atk -1" in rendered
    assert "Metagross-Mega — 88%; status none; boosts Def +2" in rendered
    assert "Human: side conditions Tailwind" in rendered


def _recommendation() -> tuple[BeliefSearchResult, BeliefPruningResult]:
    breakdown = ExactScoreBreakdown(80.0, 0.0, 70.0, 8.0, 2.0)
    result_summary = {
        "field": {
            "weather": None,
            "terrain": "psychicterrain",
            "pseudoWeather": [],
        },
        "p1": {
            "name": "Human",
            "active": [
                {
                    "species": "Metagross-Mega",
                    "hp": 80,
                    "maxhp": 100,
                    "fainted": False,
                    "status": None,
                    "boosts": {},
                }
            ],
            "sideConditions": [],
        },
        "p2": {
            "name": "Practice AI",
            "active": [
                {
                    "species": "Sneasler",
                    "hp": 90,
                    "maxhp": 100,
                    "fainted": False,
                    "status": None,
                    "boosts": {"spd": 1},
                }
            ],
            "sideConditions": [],
        },
    }
    outcomes = (
        BeliefWorldOutcome("likely", 0.75, 120.0, 150.0, "move protect", 8),
        BeliefWorldOutcome(
            "rare",
            0.25,
            80.0,
            100.0,
            "move attack",
            8,
            breakdown,
            75.0,
            result_summary,
        ),
    )
    first = BeliefChoiceScore("move psychic", 80.0, 110.0, 100.0, outcomes)
    second = BeliefChoiceScore("move protect", 70.0, 115.0, 95.0, outcomes)
    timing = BeliefSearchTiming(1, 0, 0, 0, 1, 0, 0, 1)
    recommendation = BeliefSearchResult(
        side="p2",
        chosen=first,
        ranking=(first, second),
        world_count=2,
        evaluated_choices=(first.choice, second.choice),
        branch_count=32,
        response_screening_branch_count=8,
        timing=timing,
    )
    pruning = BeliefPruningResult(
        174,
        58,
        (first.choice, second.choice),
        20,
        0.1,
        ("move psychic",),
        (
            BeliefPruningScore("move psychic", 80, 90, 100),
            BeliefPruningScore(
                "move followme, move direclaw +2",
                -1000,
                -900,
                -800,
                "move psychicfangs +2 mega, move expandingforce +2",
                breakdown,
                -1010,
                result_summary,
            ),
        ),
        (),
    )
    return recommendation, pruning


def test_search_evidence_states_scope_and_ranks_alternatives() -> None:
    recommendation, pruning = _recommendation()

    rendered = format_belief_search_evidence(recommendation, pruning)

    assert (
        "best of 2 shortlisted actions from 174 legal choices / 58 strategic families" in rendered
    )
    assert "not a proof of optimal play" in rendered
    assert "1. [CHOSEN] move psychic" in rendered
    assert "rare (weight 0.250) vs move attack" in rendered
    assert "material +70.0, position +8.0, speed +2.0" in rendered
    assert "Chosen action's worst sampled resulting board (hypothetical belief world)" in rendered
    assert "Metagross-Mega — 80.0%" in rendered
    assert "Pruning audit" in rendered
    assert "move followme, move direclaw +2" in rendered
    assert "AI [Sneasler 90.0%]; Human [Metagross-Mega 80.0%]" in rendered


def test_search_evidence_rejects_empty_limit() -> None:
    recommendation, pruning = _recommendation()

    with pytest.raises(ValueError, match="positive"):
        format_belief_search_evidence(recommendation, pruning, limit=0)
