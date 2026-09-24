from champions_practice.belief_search import ExactBeliefWorldState
from champions_practice.strategy import (
    DesiredBoard,
    FieldControlAssessment,
    PosteriorAssessment,
    ResourceAssessment,
    ResourcePurpose,
    SpeedControlAssessment,
    StrategicAssessment,
    StrategicPlan,
)
from dataclasses import replace

from champions_practice.strategy_evidence import (
    filter_supported_plans,
    format_strategic_plan_probe,
    probe_strategic_plan,
    select_supported_plan,
)


def _mon(species: str, hp: int) -> dict:
    return {
        "species": species,
        "hp": hp,
        "maxhp": 100,
        "fainted": hp == 0,
        "status": None,
        "boosts": {},
        "speed": 100,
        "grounded": True,
        "moveTypes": ["normal"],
    }


def _summary(*, keeper_hp: int, partner_hp: int, foe_a_hp: int, foe_b_hp: int) -> dict:
    return {
        "ended": False,
        "winner": None,
        "requestState": "move",
        "field": {
            "weather": None,
            "terrain": None,
            "pseudoWeather": [],
        },
        "p1": {
            "name": "Practice AI",
            "pokemon": [
                _mon("Keeper", keeper_hp),
                _mon("Partner", partner_hp),
            ],
            "active": [
                _mon("Keeper", keeper_hp),
                _mon("Partner", partner_hp),
            ],
            "sideConditions": [],
        },
        "p2": {
            "name": "Human",
            "pokemon": [
                _mon("FoeA", foe_a_hp),
                _mon("FoeB", foe_b_hp),
            ],
            "active": [
                _mon("FoeA", foe_a_hp),
                _mon("FoeB", foe_b_hp),
            ],
            "sideConditions": [],
        },
    }


def _assessment() -> StrategicAssessment:
    return StrategicAssessment(
        turn=4,
        phase="move",
        threats=(),
        resources=(
            ResourceAssessment(
                species="Keeper",
                hp_percent=100,
                active=True,
                fainted=False,
                strategic_roles=("protect",),
                preservation_priority="high",
                reasons=("only living cleanup resource",),
            ),
            ResourceAssessment(
                species="Partner",
                hp_percent=100,
                active=True,
                fainted=False,
                strategic_roles=(),
                preservation_priority="unassigned",
                reasons=(),
            ),
        ),
        speed_control=SpeedControlAssessment(
            trick_room_active=False,
            our_tailwind=False,
            opponent_tailwind=False,
            available_our_tools=(),
        ),
        field_control=FieldControlAssessment(
            terrain=None,
            weather=None,
            our_side_conditions=(),
            opponent_side_conditions=(),
            available_our_setters=(),
        ),
        posterior=PosteriorAssessment(
            particle_count=1,
            world_count=1,
            world_mass=(("world-a", 1.0),),
        ),
        key_resources=("Keeper",),
        notes=(),
    )


def _view() -> dict:
    return {
        "player": {
            "active_details": [
                {
                    "species": "Keeper",
                    "moves": ["Attack", "Protect"],
                },
                {
                    "species": "Partner",
                    "moves": ["Attack", "Protect"],
                },
            ]
        },
        "opponent": {
            "active": [
                {"species": "FoeA", "base_species": "FoeA"},
                {"species": "FoeB", "base_species": "FoeB"},
            ]
        },
    }


class PlanProbeWorker:
    choices = (
        "move attack +1, move attack +2",
        "move protect, move protect",
    )
    response = "move counter +1, move counter +2"

    def legal_choices(self, *, state, side):
        return list(self.choices) if side == "p1" else [self.response]

    def branch_many(self, *, state, branches):
        results = []
        for index, branch in enumerate(branches):
            choice = branch["p1_choice"]
            if choice == self.choices[0]:
                # Generic material scoring likes this line: we lose Keeper but KO both foes.
                summary = _summary(
                    keeper_hp=0,
                    partner_hp=100,
                    foe_a_hp=0,
                    foe_b_hp=0,
                )
            else:
                # The strategic plan likes this line: Keeper survives, but foes remain.
                summary = _summary(
                    keeper_hp=100,
                    partner_hp=100,
                    foe_a_hp=100,
                    foe_b_hp=100,
                )
            results.append({"index": index, "summary": summary})
        return results


def test_plan_probe_can_reject_generic_material_winner_to_preserve_required_resource() -> None:
    plan = StrategicPlan(
        name="preserve-keeper",
        objective="keep Keeper alive for the endgame",
        desired_board=DesiredBoard(required_resources=("Keeper",)),
        required_resources=("Keeper",),
        preserve=("Keeper",),
        acceptable_losses=("Partner",),
        failure_conditions=("critical-resource-lost:Keeper",),
        tactical_priorities=("preserve:Keeper",),
    )

    probe = probe_strategic_plan(
        PlanProbeWorker(),
        worlds=(ExactBeliefWorldState(state={"id": "A"}, weight=1.0, label="world-a"),),
        assessment=_assessment(),
        view=_view(),
        side="p1",
        plan=plan,
        candidate_limit=2,
        response_limit=1,
        rng_seeds=("low",),
    )

    assert probe.pruning.expanded_ranking[0].choice == PlanProbeWorker.choices[0]
    assert probe.chosen.choice == PlanProbeWorker.choices[1]
    assert probe.chosen.evaluation.viable_belief_mass == 1.0
    assert probe.chosen.evaluation.robust is True
    assert probe.sampled_robust is True


def test_unresolved_failure_condition_blocks_sampled_robust_status() -> None:
    plan = StrategicPlan(
        name="unknown-risk",
        objective="preserve Keeper while avoiding an unmodeled strategic failure",
        desired_board=DesiredBoard(required_resources=("Keeper",)),
        required_resources=("Keeper",),
        preserve=("Keeper",),
        failure_conditions=("unmodeled-catastrophe",),
        tactical_priorities=("preserve:Keeper",),
    )

    probe = probe_strategic_plan(
        PlanProbeWorker(),
        worlds=(ExactBeliefWorldState(state={"id": "A"}, weight=1.0, label="world-a"),),
        assessment=_assessment(),
        view=_view(),
        side="p1",
        plan=plan,
        candidate_limit=2,
        response_limit=1,
        rng_seeds=("low",),
    )

    assert probe.chosen.evaluation.robust is True
    assert probe.sampled_robust is False
    assert probe.unresolved_failure_conditions == ("unmodeled-catastrophe",)

    rendered = format_strategic_plan_probe(probe)
    assert "Evidence status: incomplete/fragile" in rendered
    assert "RNG futures sampled per reply/world: 1" in rendered
    assert "Unresolved failure conditions: unmodeled-catastrophe" in rendered



def _speed_summary(*, trick_room: bool, foe_a_hp: int) -> dict:
    indeedee = _mon("Indeedee-F", 100)
    indeedee["speed"] = 80
    sneasler = _mon("Sneasler", 100)
    sneasler["speed"] = 190
    foe_a = _mon("FoeA", foe_a_hp)
    foe_a["speed"] = 120
    foe_b = _mon("FoeB", 100)
    foe_b["speed"] = 110
    return {
        "ended": False,
        "winner": None,
        "requestState": "move",
        "field": {
            "weather": None,
            "terrain": "psychicterrain",
            "pseudoWeather": ["trickroom"] if trick_room else [],
        },
        "p1": {
            "name": "Practice AI",
            "pokemon": [indeedee, sneasler],
            "active": [indeedee, sneasler],
            "sideConditions": [],
        },
        "p2": {
            "name": "Human",
            "pokemon": [foe_a, foe_b],
            "active": [foe_a, foe_b],
            "sideConditions": [],
        },
    }


def _sneasler_assessment() -> StrategicAssessment:
    return StrategicAssessment(
        turn=2,
        phase="move",
        threats=(),
        resources=(
            ResourceAssessment(
                species="Indeedee-F",
                hp_percent=100,
                active=True,
                fainted=False,
                strategic_roles=("protect", "speed-control"),
                preservation_priority="high",
                reasons=("only living speed-control provider",),
            ),
            ResourceAssessment(
                species="Sneasler",
                hp_percent=100,
                active=True,
                fainted=False,
                strategic_roles=("protect",),
                preservation_priority="contextual",
                reasons=(),
            ),
        ),
        speed_control=SpeedControlAssessment(
            trick_room_active=False,
            our_tailwind=False,
            opponent_tailwind=False,
            available_our_tools=("Indeedee-F",),
        ),
        field_control=FieldControlAssessment(
            terrain="psychicterrain",
            weather=None,
            our_side_conditions=(),
            opponent_side_conditions=(),
            available_our_setters=("Indeedee-F",),
        ),
        posterior=PosteriorAssessment(
            particle_count=1,
            world_count=1,
            world_mass=(("world-a", 1.0),),
        ),
        key_resources=("Indeedee-F",),
        notes=(),
    )


def _sneasler_view() -> dict:
    return {
        "player": {
            "active_details": [
                {
                    "species": "Indeedee-F",
                    "moves": ["Psychic", "Trick Room", "Protect"],
                },
                {
                    "species": "Sneasler",
                    "moves": ["Close Combat", "Dire Claw", "Protect"],
                },
            ]
        },
        "opponent": {
            "active": [
                {"species": "FoeA", "base_species": "FoeA"},
                {"species": "FoeB", "base_species": "FoeB"},
            ]
        },
    }


class SneaslerRegressionWorker:
    psychic = "move psychic +1, move protect"
    trick_room = "move trickroom, move protect"
    response = "move attack +1, move attack +2"

    def legal_choices(self, *, state, side):
        if side == "p1":
            return [self.psychic, self.trick_room]
        return [self.response]

    def branch_many(self, *, state, branches):
        results = []
        for index, branch in enumerate(branches):
            choice = branch["p1_choice"]
            summary = (
                _speed_summary(trick_room=False, foe_a_hp=60)
                if choice == self.psychic
                else _speed_summary(trick_room=True, foe_a_hp=100)
            )
            results.append({"index": index, "summary": summary})
        return results


def test_sneasler_psychic_protect_regression_does_not_reward_neutral_trick_room() -> None:
    speed_plan = StrategicPlan(
        name="establish-speed-control-indeedeef",
        objective="establish favorable speed control",
        desired_board=DesiredBoard(
            required_conditions=("favorable-speed-control",),
            required_resources=("Indeedee-F",),
        ),
        required_resources=("Indeedee-F",),
        failure_conditions=("speed-control-denied",),
        tactical_priorities=("prefer-speed-control",),
    )
    preserve_plan = StrategicPlan(
        name="preserve-indeedeef",
        objective="preserve Indeedee while making progress",
        desired_board=DesiredBoard(required_resources=("Indeedee-F",)),
        required_resources=("Indeedee-F",),
        preserve=("Indeedee-F",),
        failure_conditions=("critical-resource-lost:indeedeef",),
        tactical_priorities=("preserve:Indeedee-F",),
    )
    worker = SneaslerRegressionWorker()
    worlds = (
        ExactBeliefWorldState(state={"id": "sneasler"}, weight=1.0, label="world-a"),
    )
    assessment = _sneasler_assessment()
    view = _sneasler_view()

    speed_probe = probe_strategic_plan(
        worker,
        worlds=worlds,
        assessment=assessment,
        view=view,
        side="p1",
        plan=speed_plan,
        candidate_limit=2,
        response_limit=1,
        rng_seeds=("low",),
    )
    preserve_probe = probe_strategic_plan(
        worker,
        worlds=worlds,
        assessment=assessment,
        view=view,
        side="p1",
        plan=preserve_plan,
        candidate_limit=2,
        response_limit=1,
        rng_seeds=("low",),
    )

    selected = select_supported_plan((speed_probe, preserve_probe))

    assert speed_probe.sampled_robust is False
    assert preserve_probe.sampled_robust is True
    assert preserve_probe.chosen.choice == worker.psychic
    assert selected is preserve_probe
    assert selected.chosen.choice == "move psychic +1, move protect"


def test_unsupported_plans_are_filtered_before_plan_budget() -> None:
    unsupported_room = StrategicPlan(
        name="exploit-trick-room",
        objective="use Trick Room",
        desired_board=DesiredBoard(required_conditions=("trickroom-progress",)),
        failure_conditions=("trickroom-reversed",),
    )
    unsupported_threat = StrategicPlan(
        name="neutralize-boosted-threat",
        objective="stop a boosted threat",
        desired_board=DesiredBoard(required_conditions=("threat-neutralized:foe",)),
        failure_conditions=("threat-snowballs:foe",),
    )
    supported_preserve = StrategicPlan(
        name="preserve-sneasler",
        objective="preserve Sneasler",
        desired_board=DesiredBoard(required_resources=("Sneasler",)),
        preserve=("Sneasler",),
        failure_conditions=("critical-resource-lost:sneasler",),
    )

    filtered = filter_supported_plans(
        (unsupported_room, unsupported_threat, supported_preserve),
        limit=2,
    )

    assert filtered == (supported_preserve,)


def test_cross_plan_board_utility_beats_alphabetical_tie_break() -> None:
    plan_a = StrategicPlan(
        name="aaa-worse-plan",
        objective="worse exact board",
        desired_board=DesiredBoard(required_resources=("Keeper",)),
        required_resources=("Keeper",),
        preserve=("Keeper",),
        failure_conditions=("critical-resource-lost:Keeper",),
    )
    plan_z = replace(plan_a, name="zzz-better-plan", objective="better exact board")

    base_probe = probe_strategic_plan(
        PlanProbeWorker(),
        worlds=(ExactBeliefWorldState(state={"id": "A"}, weight=1.0, label="world-a"),),
        assessment=_assessment(),
        view=_view(),
        side="p1",
        plan=plan_a,
        candidate_limit=2,
        response_limit=1,
        rng_seeds=("low",),
    )
    robust_evaluation = replace(
        base_probe.chosen.evaluation,
        viable_belief_mass=1.0,
        robust=True,
        failed_worlds=0,
        preserve_failure_mass=0.0,
        required_resource_failure_mass=0.0,
        condition_failure_mass=0.0,
        timing_failure_mass=0.0,
        declared_failure_mass=0.0,
        unacceptable_loss_mass=0.0,
    )
    robust_choice = replace(
        base_probe.chosen,
        evaluation=robust_evaluation,
        failure_penalty=0.0,
    )
    worse = replace(
        base_probe,
        plan=plan_a,
        chosen=replace(
            robust_choice,
            worst_board_score=10.0,
            weighted_board_score=10.0,
        ),
        sampled_robust=True,
    )
    better = replace(
        base_probe,
        plan=plan_z,
        chosen=replace(
            robust_choice,
            worst_board_score=20.0,
            weighted_board_score=20.0,
        ),
        sampled_robust=True,
    )

    selected = select_supported_plan((worse, better))

    assert worse.sampled_robust is True
    assert better.sampled_robust is True
    assert selected is better



def _positioning_summary(*, gardevoir_active: bool) -> dict:
    lead = _mon("LeadA", 100)
    rillaboom = _mon("Rillaboom", 100)
    gardevoir = _mon("Gardevoir", 100)
    sneasler = _mon("Sneasler", 100)
    active = (
        [gardevoir, rillaboom]
        if gardevoir_active
        else [lead, rillaboom]
    )
    return {
        "ended": False,
        "winner": None,
        "requestState": "move",
        "field": {
            "weather": None,
            "terrain": None,
            "pseudoWeather": [],
        },
        "p1": {
            "name": "Practice AI",
            "pokemon": [lead, rillaboom, gardevoir, sneasler],
            "active": active,
            "sideConditions": [],
        },
        "p2": {
            "name": "Human",
            "pokemon": [_mon("FoeA", 100), _mon("FoeB", 100)],
            "active": [_mon("FoeA", 100), _mon("FoeB", 100)],
            "sideConditions": [],
        },
    }


def _positioning_assessment() -> StrategicAssessment:
    return StrategicAssessment(
        turn=5,
        phase="move",
        threats=(),
        resources=(
            ResourceAssessment(
                species="LeadA",
                hp_percent=100,
                active=True,
                fainted=False,
                strategic_roles=("protect",),
                preservation_priority="unassigned",
                reasons=(),
            ),
            ResourceAssessment(
                species="Rillaboom",
                hp_percent=100,
                active=True,
                fainted=False,
                strategic_roles=("protect",),
                preservation_priority="contextual",
                reasons=(),
            ),
            ResourceAssessment(
                species="Gardevoir",
                hp_percent=100,
                active=False,
                fainted=False,
                strategic_roles=("protect",),
                preservation_priority="contextual",
                reasons=(),
            ),
            ResourceAssessment(
                species="Sneasler",
                hp_percent=100,
                active=False,
                fainted=False,
                strategic_roles=("protect",),
                preservation_priority="contextual",
                reasons=(),
            ),
        ),
        speed_control=SpeedControlAssessment(
            trick_room_active=False,
            our_tailwind=False,
            opponent_tailwind=False,
            available_our_tools=(),
        ),
        field_control=FieldControlAssessment(
            terrain=None,
            weather=None,
            our_side_conditions=(),
            opponent_side_conditions=(),
            available_our_setters=(),
        ),
        posterior=PosteriorAssessment(
            particle_count=1,
            world_count=1,
            world_mass=(("world-a", 1.0),),
        ),
        key_resources=(),
        notes=(),
    )


def _positioning_view() -> dict:
    return {
        "player": {
            "active_details": [
                {"species": "LeadA", "moves": ["Protect"]},
                {"species": "Rillaboom", "moves": ["Protect"]},
            ]
        },
        "opponent": {
            "active": [
                {"species": "FoeA", "base_species": "FoeA"},
                {"species": "FoeB", "base_species": "FoeB"},
            ]
        },
    }


class PositioningWorker:
    switch = "switch 3, move protect"
    stay = "move protect, move protect"
    response = "move protect, move protect"

    def legal_choices(self, *, state, side):
        return [self.switch, self.stay] if side == "p1" else [self.response]

    def branch_many(self, *, state, branches):
        return [
            {
                "index": index,
                "summary": _positioning_summary(
                    gardevoir_active=branch["p1_choice"] == self.switch,
                ),
            }
            for index, branch in enumerate(branches)
        ]


def test_exact_probe_values_pairing_safe_entry_and_cleanup_position() -> None:
    plan = StrategicPlan(
        name="gard-rilla-with-sneasler-cleanup",
        objective="enter Gardevoir beside Rillaboom while holding Sneasler for cleanup",
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
        tactical_priorities=("prefer-switch",),
    )

    probe = probe_strategic_plan(
        PositioningWorker(),
        worlds=(
            ExactBeliefWorldState(
                state={"id": "positioning"},
                weight=1.0,
                label="world-a",
            ),
        ),
        assessment=_positioning_assessment(),
        view=_positioning_view(),
        side="p1",
        plan=plan,
        candidate_limit=2,
        response_limit=1,
        rng_seeds=("low",),
    )

    assert probe.chosen.choice == PositioningWorker.switch
    assert probe.chosen.evaluation.robust is True
    assert probe.sampled_robust is True
    outcome = probe.chosen.worst_world_outcomes[0]
    assert set(outcome.active_resources) == {"Gardevoir", "Rillaboom"}
    assert outcome.newly_active_resources == ("Gardevoir",)
    assert "Sneasler" in outcome.living_resources

    rendered = format_strategic_plan_probe(probe)
    assert "Desired active pair: Gardevoir + Rillaboom" in rendered
    assert "Safe entry: Gardevoir" in rendered
    assert "Sneasler=cleanup (bench)" in rendered
