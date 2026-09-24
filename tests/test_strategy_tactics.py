from dataclasses import dataclass

from champions_practice.strategy import DesiredBoard, ResourcePurpose, StrategicPlan
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
            "team": [
                {"species": "Indeedee-F"},
                {"species": "Sneasler"},
                {"species": "Gardevoir"},
                {"species": "Rillaboom"},
            ],
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



def test_bench_resource_purpose_reserves_candidates_that_keep_it_back() -> None:
    plan = StrategicPlan(
        name="reserve-gardevoir",
        objective="keep Gardevoir for later",
        desired_board=DesiredBoard(
            resource_purposes=(
                ResourcePurpose(
                    species="Gardevoir",
                    purpose="cleanup",
                    position="bench",
                ),
            ),
        ),
    )

    guidance = guidance_from_plan(plan, view=_view())

    assert guidance.active is True
    assert guidance.reserved_bench_slots == (3,)
    assert choice_matches_guidance(
        "move psychic +1, move closecombat +1",
        guidance,
    )
    assert not choice_matches_guidance(
        "switch 3, move closecombat +1",
        guidance,
    )


def test_bench_resource_guidance_reserves_non_switch_family() -> None:
    ranking = (
        Candidate("switch 3, move attack +1"),
        Candidate("move attack +1, move attack +2"),
    )
    guidance = StrategicCandidateGuidance(
        plan_name="reserve-cleaner",
        reserved_bench_slots=(3,),
    )

    shortlist, reserved = reserve_strategic_candidate(
        ranking,
        ("switch 3, move attack +1",),
        limit=2,
        guidance=guidance,
    )

    assert shortlist == (
        "switch 3, move attack +1",
        "move attack +1, move attack +2",
    )
    assert reserved == ("move attack +1, move attack +2",)



def test_safe_entry_guidance_targets_the_intended_bench_resource() -> None:
    plan = StrategicPlan(
        name="create-gardevoir-sneasler-board",
        objective="bring Gardevoir in beside Sneasler",
        desired_board=DesiredBoard(
            required_active_pair=("Gardevoir", "Sneasler"),
            safe_entry_resources=("Gardevoir",),
        ),
        tactical_priorities=("preserve:Sneasler",),
    )

    guidance = guidance_from_plan(plan, view=_view())

    assert guidance.stay_active_slots == (2,)
    assert guidance.switch_in_slots == (3,)
    assert guidance.active is True
    assert choice_matches_guidance(
        "switch 3, move closecombat +1",
        guidance,
    )
    assert not choice_matches_guidance(
        "switch 4, move closecombat +1",
        guidance,
    )
    assert not choice_matches_guidance(
        "move followme, switch 3",
        guidance,
    )
    assert not choice_matches_guidance(
        "move followme, move closecombat +1",
        guidance,
    )


def test_safe_entry_guidance_reserves_exact_switch_family() -> None:
    ranking = (
        Candidate("switch 4, move attack +1"),
        Candidate("move attack +1, move attack +2"),
        Candidate("switch 3, move attack +1"),
    )
    guidance = StrategicCandidateGuidance(
        plan_name="create-target-board",
        switch_in_slots=(3,),
    )

    shortlist, reserved = reserve_strategic_candidate(
        ranking,
        (
            "switch 4, move attack +1",
            "move attack +1, move attack +2",
        ),
        limit=2,
        guidance=guidance,
    )

    assert shortlist == (
        "switch 4, move attack +1",
        "switch 3, move attack +1",
    )
    assert reserved == ("switch 3, move attack +1",)
