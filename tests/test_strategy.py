from dataclasses import dataclass

import pytest

from champions_practice.strategy import (
    BeliefBoardOutcome,
    DesiredBoard,
    FieldControlAssessment,
    PlanWorldOutcome,
    PosteriorAssessment,
    ResourceAssessment,
    ResourcePurpose,
    SpeedControlAssessment,
    StrategicAssessment,
    StrategicPlan,
    ThreatAssessment,
    WinCondition,
    assess_strategic_position,
    assess_trade_against_win_condition,
    evaluate_strategic_plan,
    format_strategic_assessment,
    format_strategic_plan_ranking,
    generate_strategic_plans,
    rank_strategic_plans,
    strategic_plan_from_win_condition,
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



def test_plan_generation_turns_assessment_into_inspectable_objectives() -> None:
    assessment = assess_strategic_position(
        _view(),
        particles=(Particle(0.7, "world-a"), Particle(0.3, "world-b")),
    )

    plans = generate_strategic_plans(assessment)
    names = {plan.name for plan in plans}

    assert "exploit-trick-room" in names
    assert "stall-opponent-tailwind" in names
    assert "neutralize-boosted-gholdengo" in names
    assert "preserve-indeedeef" in names

    exploit = next(plan for plan in plans if plan.name == "exploit-trick-room")
    assert "Trick Room" in exploit.objective
    assert "trickroom-reversed" in exploit.failure_conditions

    preserve = next(plan for plan in plans if plan.name == "preserve-indeedeef")
    assert preserve.preserve == ("Indeedee-F",)
    assert preserve.required_resources == ("Indeedee-F",)


def test_positioning_generation_keeps_immediate_threats_ahead_of_board_setup() -> None:
    assessment = StrategicAssessment(
        turn=6,
        phase="move",
        threats=(
            ThreatAssessment(
                species="BoostedFoe",
                urgency="immediate",
                hp_percent=100.0,
                reasons=("currently active", "positive boosts: atk"),
            ),
        ),
        resources=(
            ResourceAssessment(
                species="Anchor",
                hp_percent=100.0,
                active=True,
                fainted=False,
                strategic_roles=("field-control",),
                preservation_priority="high",
                reasons=("only living field-control provider",),
            ),
            ResourceAssessment(
                species="Partner",
                hp_percent=100.0,
                active=True,
                fainted=False,
                strategic_roles=(),
                preservation_priority="unassigned",
                reasons=(),
            ),
            ResourceAssessment(
                species="BenchKey",
                hp_percent=100.0,
                active=False,
                fainted=False,
                strategic_roles=("speed-control",),
                preservation_priority="high",
                reasons=("only living speed-control provider",),
            ),
        ),
        speed_control=SpeedControlAssessment(
            trick_room_active=False,
            our_tailwind=False,
            opponent_tailwind=False,
            available_our_tools=("BenchKey",),
        ),
        field_control=FieldControlAssessment(
            terrain=None,
            weather=None,
            our_side_conditions=(),
            opponent_side_conditions=(),
            available_our_setters=("Anchor",),
        ),
        posterior=PosteriorAssessment(
            particle_count=0,
            world_count=0,
            world_mass=(),
        ),
        key_resources=("Anchor", "BenchKey"),
        notes=(),
    )

    plans = generate_strategic_plans(assessment, limit=None)
    names = [plan.name for plan in plans]

    threat_index = names.index("neutralize-boosted-boostedfoe")
    pair_index = names.index("create-benchkey-anchor-board")
    preserve_index = names.index("preserve-anchor")

    assert threat_index < pair_index < preserve_index

    pairing = plans[pair_index]
    assert pairing.desired_board.required_active_pair == ("BenchKey", "Anchor")
    assert pairing.desired_board.safe_entry_resources == ("BenchKey",)
    assert pairing.preserve == ("Anchor", "BenchKey")


def test_win_condition_can_be_promoted_to_plan_without_losing_trade_semantics() -> None:
    win_condition = WinCondition(
        name="trick-room-sweep",
        objective="establish Trick Room and bring Torkoal in safely",
        desired_board=DesiredBoard(
            required_conditions=("trickroom", "sweeper-safe-entry"),
            required_resources=("Torkoal",),
            minimum_effective_turns=2,
        ),
        preserve=("Torkoal",),
        acceptable_losses=("Indeedee-F", "Porygon2"),
        failure_conditions=("trickroom-reversed",),
    )

    plan = strategic_plan_from_win_condition(
        win_condition,
        rationale=("The opposing side is faster outside Trick Room.",),
    )

    assert plan.name == win_condition.name
    assert plan.required_resources == ("Torkoal",)
    assert plan.preserve == ("Torkoal",)
    assert plan.acceptable_losses == ("Indeedee-F", "Porygon2")
    assert plan.rationale == ("The opposing side is faster outside Trick Room.",)


def test_plan_evaluation_distinguishes_same_sacrifice_by_endgame_coverage() -> None:
    plan = StrategicPlan(
        name="commit-trick-room",
        objective="trade the support pair for a Torkoal Trick Room endgame",
        desired_board=DesiredBoard(
            required_conditions=("trickroom", "sweeper-safe-entry"),
            required_resources=("Torkoal",),
            minimum_effective_turns=2,
        ),
        required_resources=("Torkoal",),
        preserve=("Torkoal",),
        acceptable_losses=("Indeedee-F", "Porygon2"),
        failure_conditions=("trickroom-reversed", "sweeper-denied"),
    )
    same_losses = ("Indeedee-F", "Porygon2")

    good = evaluate_strategic_plan(
        plan,
        outcomes=(
            PlanWorldOutcome(
                "standard",
                0.7,
                ("trickroom", "sweeper-safe-entry"),
                ("Torkoal",),
                3,
                same_losses,
            ),
            PlanWorldOutcome(
                "alternate",
                0.3,
                ("trickroom", "sweeper-safe-entry"),
                ("Torkoal",),
                2,
                same_losses,
            ),
        ),
    )
    bad = evaluate_strategic_plan(
        plan,
        outcomes=(
            PlanWorldOutcome(
                "reverse-room",
                0.6,
                ("trickroom", "sweeper-safe-entry"),
                ("Torkoal",),
                3,
                same_losses,
                ("trickroom-reversed",),
            ),
            PlanWorldOutcome(
                "clean-line",
                0.4,
                ("trickroom", "sweeper-safe-entry"),
                ("Torkoal",),
                3,
                same_losses,
            ),
        ),
    )

    assert good.robust is True
    assert good.viable_belief_mass == 1.0
    assert bad.robust is False
    assert bad.viable_belief_mass == 0.4
    assert good.plan.acceptable_losses == bad.plan.acceptable_losses


def test_plan_ranking_prefers_robust_coverage_without_fixed_species_values() -> None:
    trick_room = StrategicPlan(
        name="trick-room-endgame",
        objective="convert two support pieces into a Torkoal endgame",
        desired_board=DesiredBoard(
            required_conditions=("trickroom",),
            required_resources=("Torkoal",),
            minimum_effective_turns=2,
        ),
        preserve=("Torkoal",),
        acceptable_losses=("Indeedee-F", "Porygon2"),
        failure_conditions=("trickroom-reversed",),
    )
    slow_reset = StrategicPlan(
        name="preserve-and-reset",
        objective="preserve resources and reset positioning",
        desired_board=DesiredBoard(
            required_conditions=("safe-reset",),
            required_resources=("Torkoal",),
        ),
        preserve=("Torkoal",),
        acceptable_losses=(),
        failure_conditions=("reset-denied",),
    )

    ranking = rank_strategic_plans(
        (slow_reset, trick_room),
        outcomes_by_plan={
            "trick-room-endgame": (
                PlanWorldOutcome(
                    "likely",
                    0.85,
                    ("trickroom",),
                    ("Torkoal",),
                    3,
                    ("Indeedee-F", "Porygon2"),
                ),
                PlanWorldOutcome(
                    "reverse",
                    0.15,
                    ("trickroom",),
                    ("Torkoal",),
                    3,
                    ("Indeedee-F", "Porygon2"),
                    ("trickroom-reversed",),
                ),
            ),
            "preserve-and-reset": (
                PlanWorldOutcome(
                    "works",
                    0.75,
                    ("safe-reset",),
                    ("Torkoal",),
                    0,
                ),
                PlanWorldOutcome(
                    "pressure",
                    0.25,
                    (),
                    ("Torkoal",),
                    0,
                    (),
                    ("reset-denied",),
                ),
            ),
        },
    )

    assert ranking.chosen.plan.name == "trick-room-endgame"
    assert ranking.chosen.robust is True
    assert ranking.chosen.viable_belief_mass == 0.85
    assert ranking.ranking[1].viable_belief_mass == 0.75

    rendered = format_strategic_plan_ranking(ranking)
    assert "[TOP PLAN] trick-room-endgame" in rendered
    assert "coverage 85.0%" in rendered
    assert "live move selection is unchanged" in rendered



def test_cleanup_purpose_is_more_specific_than_merely_living() -> None:
    plan = StrategicPlan(
        name="preserve-sneasler-cleanup",
        objective="hold Sneasler for late-game cleanup",
        desired_board=DesiredBoard(
            resource_purposes=(
                ResourcePurpose(
                    species="Sneasler",
                    purpose="cleanup",
                    position="bench",
                ),
            ),
        ),
    )

    preserved_for_cleanup = evaluate_strategic_plan(
        plan,
        outcomes=(
            PlanWorldOutcome(
                label="held-back",
                weight=1.0,
                conditions=(),
                living_resources=("Sneasler", "Indeedee-F", "Gardevoir"),
                effective_turns=0,
                active_resources=("Indeedee-F", "Gardevoir"),
            ),
        ),
    )
    spent_on_board = evaluate_strategic_plan(
        plan,
        outcomes=(
            PlanWorldOutcome(
                label="prematurely-active",
                weight=1.0,
                conditions=(),
                living_resources=("Sneasler", "Indeedee-F", "Gardevoir"),
                effective_turns=0,
                active_resources=("Sneasler", "Indeedee-F"),
            ),
        ),
    )

    assert preserved_for_cleanup.robust is True
    assert preserved_for_cleanup.purpose_failure_mass == 0.0
    assert spent_on_board.robust is False
    assert spent_on_board.purpose_failure_mass == 1.0


def test_desired_active_pair_and_safe_entry_are_independent_requirements() -> None:
    plan = StrategicPlan(
        name="gard-rilla-board",
        objective="bring Gardevoir in safely beside Rillaboom",
        desired_board=DesiredBoard(
            required_active_pair=("Gardevoir", "Rillaboom"),
            safe_entry_resources=("Gardevoir",),
        ),
    )

    evaluation = evaluate_strategic_plan(
        plan,
        outcomes=(
            PlanWorldOutcome(
                label="clean-entry",
                weight=0.5,
                conditions=(),
                living_resources=("Gardevoir", "Rillaboom", "Sneasler"),
                effective_turns=0,
                active_resources=("Gardevoir", "Rillaboom"),
                newly_active_resources=("Gardevoir",),
            ),
            PlanWorldOutcome(
                label="wrong-partner",
                weight=0.25,
                conditions=(),
                living_resources=("Gardevoir", "Rillaboom", "Sneasler"),
                effective_turns=0,
                active_resources=("Gardevoir", "Sneasler"),
                newly_active_resources=("Gardevoir",),
            ),
            PlanWorldOutcome(
                label="already-exposed",
                weight=0.25,
                conditions=(),
                living_resources=("Gardevoir", "Rillaboom", "Sneasler"),
                effective_turns=0,
                active_resources=("Gardevoir", "Rillaboom"),
                newly_active_resources=(),
            ),
        ),
    )

    assert evaluation.viable_belief_mass == 0.5
    assert evaluation.robust is False
    assert evaluation.active_pair_failure_mass == 0.25
    assert evaluation.safe_entry_failure_mass == 0.25



def test_trade_evaluation_respects_positioning_and_resource_purpose() -> None:
    win_condition = WinCondition(
        name="positioned-endgame",
        objective="enter Gardevoir beside Rillaboom and keep Sneasler in reserve",
        desired_board=DesiredBoard(
            required_active_pair=("Gardevoir", "Rillaboom"),
            safe_entry_resources=("Gardevoir",),
            resource_purposes=(
                ResourcePurpose(
                    species="Sneasler",
                    purpose="cleanup",
                    position="bench",
                ),
            ),
        ),
    )

    good = assess_trade_against_win_condition(
        win_condition,
        lost_resources=(),
        outcomes=(
            BeliefBoardOutcome(
                label="good",
                weight=1.0,
                conditions=(),
                living_resources=("Gardevoir", "Rillaboom", "Sneasler"),
                effective_turns=0,
                active_resources=("Gardevoir", "Rillaboom"),
                newly_active_resources=("Gardevoir",),
            ),
        ),
    )
    wrong_board = assess_trade_against_win_condition(
        win_condition,
        lost_resources=(),
        outcomes=(
            BeliefBoardOutcome(
                label="wrong",
                weight=1.0,
                conditions=(),
                living_resources=("Gardevoir", "Rillaboom", "Sneasler"),
                effective_turns=0,
                active_resources=("Gardevoir", "Sneasler"),
                newly_active_resources=("Gardevoir",),
            ),
        ),
    )

    assert good.supports_win_condition is True
    assert wrong_board.supports_win_condition is False
    assert any("pairing" in reason for reason in wrong_board.reasons)
