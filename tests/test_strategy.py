from dataclasses import dataclass

import pytest

from champions_practice.strategy import (
    BeliefBoardOutcome,
    DesiredBoard,
    WinCondition,
    assess_strategic_position,
    assess_trade_against_win_condition,
    format_strategic_assessment,
)


@dataclass(frozen=True)
class Particle:
    weight: float
    world_id: str


def _view() -> dict:
    return {
        "turn": 3,
        "phase": "move",
        "field": {
            "weather": None,
            "terrain": "psychicterrain",
            "pseudo_weather": ["trickroom"],
        },
        "player": {
            "name": "Practice AI",
            "side_conditions": [],
            "team": [
                {
                    "species": "Indeedee-F",
                    "hp_percent": 35,
                    "fainted": False,
                    "active": True,
                    "ability": "Psychic Surge",
                    "moves": ["Follow Me", "Trick Room", "Helping Hand", "Protect"],
                },
                {
                    "species": "Sneasler",
                    "hp_percent": 100,
                    "fainted": False,
                    "active": False,
                    "ability": "Unburden",
                    "moves": ["Close Combat", "Dire Claw", "Rock Slide", "Protect"],
                },
                {
                    "species": "Gardevoir-Mega",
                    "hp_percent": 100,
                    "fainted": False,
                    "active": True,
                    "ability": "Pixilate",
                    "moves": ["Hyper Voice", "Expanding Force", "Mystical Fire", "Protect"],
                },
            ],
        },
        "opponent": {
            "name": "Human",
            "preview_species": ["Rillaboom", "Gholdengo", "Incineroar", "Torkoal"],
            "side_conditions": ["tailwind"],
            "active": [
                {
                    "species": "Gholdengo",
                    "base_species": "Gholdengo",
                    "hp_percent": 82,
                    "status": None,
                    "boosts": {"spa": 1},
                    "fainted": False,
                },
                {
                    "species": "Rillaboom",
                    "base_species": "Rillaboom",
                    "hp_percent": 100,
                    "status": None,
                    "boosts": {},
                    "fainted": False,
                },
            ],
            "revealed": [
                {
                    "species": "Incineroar",
                    "hp_percent": 70,
                    "fainted": False,
                    "seen": True,
                }
            ],
        },
    }


def test_strategic_assessment_uses_public_state_own_private_team_and_posterior() -> None:
    assessment = assess_strategic_position(
        _view(),
        particles=(
            Particle(0.6, "world-a"),
            Particle(0.25, "world-b"),
            Particle(0.15, "world-a"),
        ),
    )

    assert assessment.turn == 3
    assert assessment.speed_control.trick_room_active is True
    assert assessment.speed_control.opponent_tailwind is True
    assert assessment.posterior.particle_count == 3
    assert assessment.posterior.world_count == 2
    assert assessment.posterior.world_mass[0] == ("world-a", 0.75)
    assert assessment.threats[0].urgency == "immediate"
    assert "positive boosts: spa" in assessment.threats[0].reasons
    indeedee = next(
        resource
        for resource in assessment.resources
        if resource.species == "Indeedee-F"
    )
    assert "redirection" in indeedee.strategic_roles
    assert "speed-control" in indeedee.strategic_roles
    assert "field-control" in indeedee.strategic_roles
    assert indeedee.preservation_priority == "high"
    assert "Indeedee-F" in assessment.key_resources

    rendered = format_strategic_assessment(assessment)
    assert "Immediate threats: Gholdengo, Rillaboom" in rendered
    assert "opponent Tailwind active" in rendered
    assert "world-a 75.0%" in rendered


def test_same_material_sacrifice_can_be_good_or_bad_based_on_resulting_win_condition() -> None:
    win_condition = WinCondition(
        name="trick-room-sweep",
        objective="convert the setter and redirector into a safe Trick Room endgame",
        desired_board=DesiredBoard(
            required_conditions=("trickroom", "sweeper-safe-entry"),
            required_resources=("Torkoal",),
            minimum_effective_turns=2,
        ),
        preserve=("Torkoal",),
        acceptable_losses=("Indeedee-F", "Porygon2"),
        failure_conditions=("trickroom-reversed", "sweeper-denied"),
    )
    losses = ("Indeedee-F", "Porygon2")

    good = assess_trade_against_win_condition(
        win_condition,
        lost_resources=losses,
        outcomes=(
            BeliefBoardOutcome(
                "likely-set",
                0.7,
                ("trickroom", "sweeper-safe-entry"),
                ("Torkoal",),
                3,
            ),
            BeliefBoardOutcome(
                "alternate-set",
                0.3,
                ("trickroom", "sweeper-safe-entry"),
                ("Torkoal",),
                2,
            ),
        ),
    )
    bad = assess_trade_against_win_condition(
        win_condition,
        lost_resources=losses,
        outcomes=(
            BeliefBoardOutcome(
                "can-reverse-room",
                0.6,
                ("trickroom", "sweeper-safe-entry"),
                ("Torkoal",),
                3,
                ("trickroom-reversed",),
            ),
            BeliefBoardOutcome(
                "clean-line",
                0.4,
                ("trickroom", "sweeper-safe-entry"),
                ("Torkoal",),
                3,
            ),
        ),
    )

    assert good.lost_resources == bad.lost_resources
    assert good.supports_win_condition is True
    assert good.viable_belief_mass == 1.0
    assert bad.supports_win_condition is False
    assert bad.viable_belief_mass == 0.4


def test_losing_a_preserve_resource_invalidates_trade_even_with_good_board() -> None:
    win_condition = WinCondition(
        name="late-game-cleanup",
        objective="preserve Sneasler for cleanup",
        desired_board=DesiredBoard(required_resources=("Sneasler",)),
        preserve=("Sneasler",),
        acceptable_losses=("Indeedee-F",),
    )

    result = assess_trade_against_win_condition(
        win_condition,
        lost_resources=("Sneasler",),
        outcomes=(
            BeliefBoardOutcome("world", 1.0, (), ("Sneasler",), 0),
        ),
    )

    assert result.supports_win_condition is False
    assert result.preserve_losses == ("Sneasler",)


def test_strategy_reuses_public_information_boundary() -> None:
    view = _view()
    view["opponent"]["active"][0]["item"] = "Choice Specs"

    with pytest.raises(ValueError, match="non-public"):
        assess_strategic_position(view)
