from champions_practice.belief_search import ExactBeliefWorldState
from champions_practice.strategy import (
    DesiredBoard,
    FieldControlAssessment,
    PosteriorAssessment,
    ResourceAssessment,
    SpeedControlAssessment,
    StrategicAssessment,
    StrategicPlan,
)
from champions_practice.strategy_evidence import (
    format_strategic_plan_probe,
    probe_strategic_plan,
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
    assert probe.proven_robust is True


def test_unresolved_failure_condition_blocks_proven_robust_status() -> None:
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
    assert probe.proven_robust is False
    assert probe.unresolved_failure_conditions == ("unmodeled-catastrophe",)

    rendered = format_strategic_plan_probe(probe)
    assert "Evidence status: incomplete/fragile" in rendered
    assert "Unresolved failure conditions: unmodeled-catastrophe" in rendered
