from dataclasses import dataclass

from champions_practice.strategy import DesiredBoard, StrategicPlan
from champions_practice.strategy_tactics import (
    StrategicCandidateGuidance,
    choice_matches_guidance,
    guidance_from_plan,
    reserve_strategic_candidate,
)


@dataclass(frozen=True)
class Candidate:
    choice: str


def _view() -> dict:
    return {
        "player": {
            "active_details": [
                {
                    "species": "Indeedee-F",
                    "moves": ["Follow Me", "Trick Room", "Protect"],
                },
                {
                    "species": "Sneasler",
                    "moves": ["Close Combat", "Dire Claw", "Protect"],
                },
            ]
        },
        "opponent": {
            "active": [
                {"species": "Gholdengo", "base_species": "Gholdengo"},
                {"species": "Rillaboom", "base_species": "Rillaboom"},
            ]
        },
    }


def test_plan_priorities_translate_to_public_candidate_guidance() -> None:
    plan = StrategicPlan(
        name="protect-indeedee-remove-gholdengo",
        objective="preserve Indeedee while removing Gholdengo",
        desired_board=DesiredBoard(),
        tactical_priorities=(
            "preserve:Indeedee-F",
            "target:Gholdengo",
            "prefer-speed-control",
        ),
    )

    guidance = guidance_from_plan(plan, view=_view())

    assert guidance.plan_name == plan.name
    assert guidance.protected_slots == (1,)
    assert guidance.target_slots == (1,)
    assert "trickroom" in guidance.preferred_move_ids
    assert guidance.active is True


def test_choice_matching_accepts_protect_switch_target_and_speed_control_lines() -> None:
    guidance = StrategicCandidateGuidance(
        plan_name="test",
        preferred_move_ids=("trickroom",),
        prefer_switch=False,
        protected_slots=(1,),
        target_slots=(2,),
    )

    assert choice_matches_guidance(
        "move protect, move closecombat +1",
        guidance,
    )
    assert choice_matches_guidance(
        "switch 3, move closecombat +1",
        guidance,
    )
    assert choice_matches_guidance(
        "move followme, move direclaw +2",
        guidance,
    )
    assert choice_matches_guidance(
        "move trickroom, move protect",
        guidance,
    )
    assert not choice_matches_guidance(
        "move followme, move closecombat +1",
        guidance,
    )


def test_strategy_reserves_one_slot_without_displacing_tactical_top_choice() -> None:
    ranking = (
        Candidate("move attacka +1, move attackb +1"),
        Candidate("move attackc +1, move attackd +1"),
        Candidate("move protect, move attackd +1"),
    )
    original = (
        "move attacka +1, move attackb +1",
        "move attackc +1, move attackd +1",
    )
    guidance = StrategicCandidateGuidance(
        plan_name="stall",
        preferred_move_ids=("protect",),
    )

    shortlist, reserved = reserve_strategic_candidate(
        ranking,
        original,
        limit=2,
        guidance=guidance,
    )

    assert shortlist[0] == original[0]
    assert shortlist[1] == "move protect, move attackd +1"
    assert reserved == ("move protect, move attackd +1",)


def test_strategy_has_no_reservation_power_when_only_one_candidate_is_allowed() -> None:
    ranking = (
        Candidate("move attack +1, move attack +1"),
        Candidate("move protect, move protect"),
    )
    guidance = StrategicCandidateGuidance(
        plan_name="stall",
        preferred_move_ids=("protect",),
    )

    shortlist, reserved = reserve_strategic_candidate(
        ranking,
        ("move attack +1, move attack +1",),
        limit=1,
        guidance=guidance,
    )

    assert shortlist == ("move attack +1, move attack +1",)
    assert reserved == ()
