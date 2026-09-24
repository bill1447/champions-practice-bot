from types import SimpleNamespace

from champions_practice.belief_search import ExactBeliefWorldState
from champions_practice.strategic_benchmarks import (
    STRATEGIC_BENCHMARKS,
    StrategicBenchmarkObservation,
    evaluate_strategic_benchmark,
    evaluate_strategic_benchmark_suite,
    format_strategic_benchmark_report,
    observation_from_plan,
    observation_from_probe,
    run_generated_strategy_benchmark,
)
from champions_practice.strategy import DesiredBoard, ResourcePurpose, StrategicPlan


def _case(case_id: str):
    return next(case for case in STRATEGIC_BENCHMARKS if case.case_id == case_id)


def test_benchmark_catalog_has_unique_ids_and_expected_known_gap() -> None:
    ids = [case.case_id for case in STRATEGIC_BENCHMARKS]

    assert len(ids) == len(set(ids))
    assert len(STRATEGIC_BENCHMARKS) >= 11

    known_gaps = [case for case in STRATEGIC_BENCHMARKS if case.known_gap]
    assert [case.case_id for case in known_gaps] == [
        "auto-generate-sacrifice-endgame",
        "auto-generate-cleanup-purpose",
    ]


def test_observation_from_probe_preserves_plan_choice_and_robustness() -> None:
    plan = StrategicPlan(
        name="preserve-keeper",
        objective="preserve Keeper",
        desired_board=DesiredBoard(required_resources=("Keeper",)),
        preserve=("Keeper",),
    )
    probe = SimpleNamespace(
        plan=plan,
        chosen=SimpleNamespace(choice="move protect, move protect"),
        sampled_robust=True,
    )

    observation = observation_from_probe(probe)

    assert observation.plan_name == "preserve-keeper"
    assert observation.choice == "move protect, move protect"
    assert observation.robust is True
    assert observation.preserve == ("Keeper",)


def test_richer_positioning_expectation_detects_wrong_board() -> None:
    case = _case("gard-rilla-safe-entry-cleanup")
    wrong = StrategicPlan(
        name="gard-rilla-with-sneasler-cleanup",
        objective="wrong positioning",
        desired_board=DesiredBoard(
            required_active_pair=("Gardevoir", "Sneasler"),
            resource_purposes=(
                ResourcePurpose(
                    species="Sneasler",
                    purpose="cleanup",
                    position="active",
                ),
            ),
        ),
    )

    result = evaluate_strategic_benchmark(
        case,
        observation_from_plan(
            wrong,
            choice="switch 3, move protect",
            robust=True,
        ),
    )

    assert result.passed is False
    assert result.status == "fail"
    assert any("desired active pair" in failure for failure in result.failures)
    assert any("safe-entry resources" in failure for failure in result.failures)
    assert any("missing resource purposes" in failure for failure in result.failures)


def test_known_generation_gap_is_not_reported_as_regression() -> None:
    case = _case("auto-generate-cleanup-purpose")

    result = evaluate_strategic_benchmark(
        case,
        StrategicBenchmarkObservation(
            plan_name=None,
            choice=None,
            robust=None,
            desired_board=None,
        ),
    )

    assert result.passed is False
    assert result.status == "known-gap"
    assert result.failures == ("selected result has no DesiredBoard",)


def test_baseline_suite_separates_known_gap_from_regressions() -> None:
    observations = {
        "sneasler-neutral-trick-room": observation_from_plan(
            StrategicPlan(
                name="preserve-indeedeef",
                objective="preserve Indeedee and make progress",
                desired_board=DesiredBoard(required_resources=("Indeedee-F",)),
                preserve=("Indeedee-F",),
            ),
            choice="move psychic +1, move protect",
            robust=True,
        ),
        "sneasler-neutral-trick-room-showdown": observation_from_plan(
            StrategicPlan(
                name="preserve-indeedeef",
                objective="preserve Indeedee",
                desired_board=DesiredBoard(required_resources=("Indeedee-F",)),
                preserve=("Indeedee-F",),
            ),
            robust=True,
        ),
        "critical-resource-over-material": observation_from_plan(
            StrategicPlan(
                name="preserve-keeper",
                objective="preserve Keeper",
                desired_board=DesiredBoard(required_resources=("Keeper",)),
                preserve=("Keeper",),
            ),
            choice="move protect, move protect",
            robust=True,
        ),
        "gard-rilla-safe-entry-cleanup": observation_from_plan(
            StrategicPlan(
                name="gard-rilla-with-sneasler-cleanup",
                objective="build the desired board",
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
            ),
            choice="switch 3, move protect",
            robust=True,
        ),
        "support-sacrifice-for-trick-room-endgame": observation_from_plan(
            StrategicPlan(
                name="trick-room-sweep",
                objective="convert supports into Torkoal endgame",
                desired_board=DesiredBoard(required_resources=("Torkoal",)),
                preserve=("Torkoal",),
                acceptable_losses=("Indeedee-F", "Porygon2"),
            ),
            robust=True,
        ),
        "protect-unique-resource": observation_from_plan(
            StrategicPlan(
                name="preserve-anchor",
                objective="preserve Anchor with Protect",
                desired_board=DesiredBoard(required_resources=("Anchor",)),
                preserve=("Anchor",),
            ),
            choice="move protect, move attack +1",
            robust=True,
        ),
        "switch-unique-resource": observation_from_plan(
            StrategicPlan(
                name="preserve-anchor",
                objective="preserve Anchor by switching",
                desired_board=DesiredBoard(required_resources=("Anchor",)),
                preserve=("Anchor",),
            ),
            choice="switch 3, move attack +1",
            robust=True,
        ),
        "boosted-threat-targeting-evidence": observation_from_plan(
            StrategicPlan(
                name="neutralize-boosted-boostedfoe",
                objective="remove the boosted immediate threat",
                desired_board=DesiredBoard(
                    required_conditions=("threat-neutralized:boostedfoe",),
                ),
                failure_conditions=("threat-snowballs:boostedfoe",),
                tactical_priorities=("target:BoostedFoe",),
            ),
            choice="move attack +1, move attack +1",
            robust=True,
        ),
        "auto-generate-active-pair": observation_from_plan(
            StrategicPlan(
                name="create-gardevoir-rillaboom-board",
                objective="combine two unique strategic resources",
                desired_board=DesiredBoard(
                    required_resources=("Rillaboom", "Gardevoir"),
                    required_active_pair=("Gardevoir", "Rillaboom"),
                    safe_entry_resources=("Gardevoir",),
                ),
                required_resources=("Rillaboom", "Gardevoir"),
                preserve=("Rillaboom", "Gardevoir"),
                tactical_priorities=("prefer-switch", "preserve:Rillaboom"),
            ),
            choice="switch 3, move attack +1",
            robust=True,
        ),
    }

    suite = evaluate_strategic_benchmark_suite(
        STRATEGIC_BENCHMARKS,
        observations,
    )

    assert suite.passed is True
    assert suite.regressions == ()
    assert [result.case.case_id for result in suite.known_gaps] == [
        "auto-generate-sacrifice-endgame",
        "auto-generate-cleanup-purpose",
    ]

    report = format_strategic_benchmark_report(suite)
    assert "pass 9 | known-gap 2 | fail 0" in report
    assert "[KNOWN-GAP] auto-generate-cleanup-purpose" in report


def test_resolved_case_failure_is_a_regression() -> None:
    case = _case("sneasler-neutral-trick-room")
    bad_plan = StrategicPlan(
        name="establish-speed-control-indeedeef",
        objective="set Trick Room because it exists",
        desired_board=DesiredBoard(
            required_conditions=("favorable-speed-control",),
        ),
    )

    suite = evaluate_strategic_benchmark_suite(
        (case,),
        {
            case.case_id: observation_from_plan(
                bad_plan,
                choice="move trickroom, move protect",
                robust=True,
            )
        },
    )

    assert suite.passed is False
    assert len(suite.regressions) == 1
    result = suite.regressions[0]
    assert result.status == "fail"
    assert any("forbidden plan" in failure for failure in result.failures)



def _benchmark_mon(species: str, hp: int, speed: int) -> dict:
    return {
        "species": species,
        "hp": hp,
        "maxhp": 100,
        "fainted": hp == 0,
        "status": None,
        "boosts": {},
        "speed": speed,
        "grounded": True,
        "moveTypes": ["normal"],
    }


def _sneasler_public_view() -> dict:
    return {
        "turn": 2,
        "phase": "move",
        "field": {
            "weather": None,
            "terrain": "psychicterrain",
            "pseudo_weather": [],
        },
        "player": {
            "name": "Practice AI",
            "side_conditions": [],
            "team": [
                {
                    "species": "Indeedee-F",
                    "hp_percent": 100,
                    "fainted": False,
                    "active": True,
                    "ability": "Psychic Surge",
                    "moves": ["Psychic", "Trick Room", "Follow Me", "Protect"],
                },
                {
                    "species": "Sneasler",
                    "hp_percent": 100,
                    "fainted": False,
                    "active": True,
                    "ability": "Unburden",
                    "moves": ["Close Combat", "Dire Claw", "Rock Slide", "Protect"],
                },
                {
                    "species": "Gardevoir",
                    "hp_percent": 100,
                    "fainted": False,
                    "active": False,
                    "ability": "Trace",
                    "moves": ["Psychic", "Protect"],
                },
                {
                    "species": "Rillaboom",
                    "hp_percent": 100,
                    "fainted": False,
                    "active": False,
                    "ability": "Grassy Surge",
                    "moves": ["Wood Hammer", "Protect"],
                },
            ],
            "active_details": [
                {
                    "species": "Indeedee-F",
                    "moves": ["Psychic", "Trick Room", "Follow Me", "Protect"],
                },
                {
                    "species": "Sneasler",
                    "moves": ["Close Combat", "Dire Claw", "Rock Slide", "Protect"],
                },
            ],
        },
        "opponent": {
            "name": "Human",
            "preview_species": ["FoeA", "FoeB", "FoeC", "FoeD"],
            "side_conditions": [],
            "active": [
                {
                    "species": "FoeA",
                    "base_species": "FoeA",
                    "hp_percent": 100,
                    "status": None,
                    "boosts": {},
                    "fainted": False,
                },
                {
                    "species": "FoeB",
                    "base_species": "FoeB",
                    "hp_percent": 100,
                    "status": None,
                    "boosts": {},
                    "fainted": False,
                },
            ],
            "revealed": [],
        },
    }


def _sneasler_summary(*, trick_room: bool, foe_a_hp: int) -> dict:
    indeedee = _benchmark_mon("Indeedee-F", 100, 80)
    sneasler = _benchmark_mon("Sneasler", 100, 190)
    gardevoir = _benchmark_mon("Gardevoir", 100, 150)
    rillaboom = _benchmark_mon("Rillaboom", 100, 140)
    foe_a = _benchmark_mon("FoeA", foe_a_hp, 120)
    foe_b = _benchmark_mon("FoeB", 100, 110)
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
            "pokemon": [indeedee, sneasler, gardevoir, rillaboom],
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


class GeneratedSneaslerWorker:
    psychic = "move psychic +1, move protect"
    trick_room = "move trickroom, move protect"
    response = "move attack +1, move attack +2"

    def legal_choices(self, *, state, side):
        return [self.psychic, self.trick_room] if side == "p1" else [self.response]

    def branch_many(self, *, state, branches):
        resolved = []
        for index, branch in enumerate(branches):
            choice = branch["p1_choice"]
            resolved.append(
                {
                    "index": index,
                    "summary": (
                        _sneasler_summary(trick_room=False, foe_a_hp=60)
                        if choice == self.psychic
                        else _sneasler_summary(trick_room=True, foe_a_hp=100)
                    ),
                }
            )
        return resolved


def test_executable_benchmark_runs_real_strategy_generation_probe_and_selection() -> None:
    case = _case("sneasler-neutral-trick-room")

    execution = run_generated_strategy_benchmark(
        GeneratedSneaslerWorker(),
        case=case,
        view=_sneasler_public_view(),
        particles=(SimpleNamespace(weight=1.0, world_id="world-a"),),
        worlds=(
            ExactBeliefWorldState(
                state={"id": "sneasler"},
                weight=1.0,
                label="world-a",
            ),
        ),
        side="p1",
        plan_limit=4,
        candidate_limit=2,
        response_limit=1,
        rng_seeds=("low",),
    )

    assert execution.result.status == "pass"
    assert execution.selected_probe is not None
    assert execution.selected_probe.plan.name == "preserve-indeedeef"
    assert execution.selected_probe.chosen.choice == "move psychic +1, move protect"
    assert "establish-speed-control-indeedeef" in execution.generated_plan_names
    assert "preserve-indeedeef" in execution.generated_plan_names
    assert set(execution.probed_plan_names) == {
        "establish-speed-control-indeedeef",
        "preserve-indeedeef",
    }
    assert execution.exact_branch_count > 0



def _keeper_public_view() -> dict:
    return {
        "turn": 4,
        "phase": "move",
        "field": {
            "weather": None,
            "terrain": None,
            "pseudo_weather": [],
        },
        "player": {
            "name": "Practice AI",
            "side_conditions": [],
            "team": [
                {
                    "species": "Keeper",
                    "hp_percent": 100,
                    "fainted": False,
                    "active": True,
                    "ability": "",
                    "moves": ["Attack", "Psychic Terrain", "Protect"],
                },
                {
                    "species": "Partner",
                    "hp_percent": 100,
                    "fainted": False,
                    "active": True,
                    "ability": "",
                    "moves": ["Attack", "Protect"],
                },
                {
                    "species": "BenchA",
                    "hp_percent": 100,
                    "fainted": False,
                    "active": False,
                    "ability": "",
                    "moves": ["Attack", "Protect"],
                },
                {
                    "species": "BenchB",
                    "hp_percent": 100,
                    "fainted": False,
                    "active": False,
                    "ability": "",
                    "moves": ["Attack", "Protect"],
                },
            ],
            "active_details": [
                {
                    "species": "Keeper",
                    "moves": ["Attack", "Psychic Terrain", "Protect"],
                },
                {
                    "species": "Partner",
                    "moves": ["Attack", "Protect"],
                },
            ],
        },
        "opponent": {
            "name": "Human",
            "preview_species": ["FoeA", "FoeB", "FoeC", "FoeD"],
            "side_conditions": [],
            "active": [
                {
                    "species": "FoeA",
                    "base_species": "FoeA",
                    "hp_percent": 100,
                    "status": None,
                    "boosts": {},
                    "fainted": False,
                },
                {
                    "species": "FoeB",
                    "base_species": "FoeB",
                    "hp_percent": 100,
                    "status": None,
                    "boosts": {},
                    "fainted": False,
                },
            ],
            "revealed": [],
        },
    }


def _keeper_summary(
    *,
    keeper_hp: int,
    partner_hp: int,
    foe_a_hp: int,
    foe_b_hp: int,
) -> dict:
    keeper = _benchmark_mon("Keeper", keeper_hp, 100)
    partner = _benchmark_mon("Partner", partner_hp, 100)
    bench_a = _benchmark_mon("BenchA", 100, 100)
    bench_b = _benchmark_mon("BenchB", 100, 100)
    foe_a = _benchmark_mon("FoeA", foe_a_hp, 100)
    foe_b = _benchmark_mon("FoeB", foe_b_hp, 100)
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
            "pokemon": [keeper, partner, bench_a, bench_b],
            "active": [keeper, partner],
            "sideConditions": [],
        },
        "p2": {
            "name": "Human",
            "pokemon": [foe_a, foe_b],
            "active": [foe_a, foe_b],
            "sideConditions": [],
        },
    }


class GeneratedKeeperWorker:
    material = "move attack +1, move attack +2"
    preserve = "move protect, move protect"
    response = "move counter +1, move counter +2"

    def legal_choices(self, *, state, side):
        return [self.material, self.preserve] if side == "p1" else [self.response]

    def branch_many(self, *, state, branches):
        resolved = []
        for index, branch in enumerate(branches):
            choice = branch["p1_choice"]
            resolved.append(
                {
                    "index": index,
                    "summary": (
                        _keeper_summary(
                            keeper_hp=0,
                            partner_hp=100,
                            foe_a_hp=0,
                            foe_b_hp=0,
                        )
                        if choice == self.material
                        else _keeper_summary(
                            keeper_hp=100,
                            partner_hp=100,
                            foe_a_hp=100,
                            foe_b_hp=100,
                        )
                    ),
                }
            )
        return resolved


def test_executable_benchmark_generates_resource_preservation_from_position() -> None:
    case = _case("critical-resource-over-material")

    execution = run_generated_strategy_benchmark(
        GeneratedKeeperWorker(),
        case=case,
        view=_keeper_public_view(),
        particles=(SimpleNamespace(weight=1.0, world_id="world-a"),),
        worlds=(
            ExactBeliefWorldState(
                state={"id": "keeper"},
                weight=1.0,
                label="world-a",
            ),
        ),
        side="p1",
        plan_limit=4,
        candidate_limit=2,
        response_limit=1,
        rng_seeds=("low",),
    )

    assert execution.result.status == "pass"
    assert execution.generated_plan_names == ("preserve-keeper",)
    assert execution.probed_plan_names == ("preserve-keeper",)
    assert execution.selected_probe is not None
    assert execution.selected_probe.plan.name == "preserve-keeper"
    assert execution.selected_probe.chosen.choice == "move protect, move protect"



def _anchor_public_view() -> dict:
    return {
        "turn": 5,
        "phase": "move",
        "field": {
            "weather": None,
            "terrain": None,
            "pseudo_weather": [],
        },
        "player": {
            "name": "Practice AI",
            "side_conditions": [],
            "team": [
                {
                    "species": "Anchor",
                    "hp_percent": 100,
                    "fainted": False,
                    "active": True,
                    "ability": "",
                    "moves": ["Follow Me", "Protect", "Attack"],
                },
                {
                    "species": "Partner",
                    "hp_percent": 100,
                    "fainted": False,
                    "active": True,
                    "ability": "",
                    "moves": ["Attack"],
                },
                {
                    "species": "BenchA",
                    "hp_percent": 100,
                    "fainted": False,
                    "active": False,
                    "ability": "",
                    "moves": ["Attack"],
                },
                {
                    "species": "BenchB",
                    "hp_percent": 100,
                    "fainted": False,
                    "active": False,
                    "ability": "",
                    "moves": ["Attack"],
                },
            ],
            "active_details": [
                {
                    "species": "Anchor",
                    "moves": ["Follow Me", "Protect", "Attack"],
                },
                {
                    "species": "Partner",
                    "moves": ["Attack"],
                },
            ],
        },
        "opponent": {
            "name": "Human",
            "preview_species": ["FoeA", "FoeB", "FoeC", "FoeD"],
            "side_conditions": [],
            "active": [
                {
                    "species": "FoeA",
                    "base_species": "FoeA",
                    "hp_percent": 100,
                    "status": None,
                    "boosts": {},
                    "fainted": False,
                },
                {
                    "species": "FoeB",
                    "base_species": "FoeB",
                    "hp_percent": 100,
                    "status": None,
                    "boosts": {},
                    "fainted": False,
                },
            ],
            "revealed": [],
        },
    }


def _anchor_summary(
    *,
    anchor_hp: int,
    foe_a_hp: int = 100,
    switched: bool = False,
) -> dict:
    anchor = _benchmark_mon("Anchor", anchor_hp, 90)
    partner = _benchmark_mon("Partner", 100, 100)
    bench_a = _benchmark_mon("BenchA", 100, 110)
    bench_b = _benchmark_mon("BenchB", 100, 120)
    foe_a = _benchmark_mon("FoeA", foe_a_hp, 100)
    foe_b = _benchmark_mon("FoeB", 100, 100)
    active = [bench_a, partner] if switched else [anchor, partner]
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
            "pokemon": [anchor, partner, bench_a, bench_b],
            "active": active,
            "sideConditions": [],
        },
        "p2": {
            "name": "Human",
            "pokemon": [foe_a, foe_b],
            "active": [foe_a, foe_b],
            "sideConditions": [],
        },
    }


class ProtectAnchorWorker:
    attack = "move attack +1, move attack +1"
    protect = "move protect, move attack +1"
    response = "move pressure +1, move pressure +1"

    def legal_choices(self, *, state, side):
        return [self.attack, self.protect] if side == "p1" else [self.response]

    def branch_many(self, *, state, branches):
        results = []
        for index, branch in enumerate(branches):
            choice = branch["p1_choice"]
            summary = (
                _anchor_summary(anchor_hp=0, foe_a_hp=0)
                if choice == self.attack
                else _anchor_summary(anchor_hp=100)
            )
            results.append({"index": index, "summary": summary})
        return results


class SwitchAnchorWorker:
    protect = "move protect, move attack +1"
    switch = "switch 3, move attack +1"
    response = "move feint +1, move pressure +1"

    def legal_choices(self, *, state, side):
        return [self.protect, self.switch] if side == "p1" else [self.response]

    def branch_many(self, *, state, branches):
        results = []
        for index, branch in enumerate(branches):
            choice = branch["p1_choice"]
            summary = (
                _anchor_summary(anchor_hp=100, switched=True)
                if choice == self.switch
                else _anchor_summary(anchor_hp=0)
            )
            results.append({"index": index, "summary": summary})
        return results


def _run_anchor_benchmark(case_id: str, worker) -> object:
    return run_generated_strategy_benchmark(
        worker,
        case=_case(case_id),
        view=_anchor_public_view(),
        particles=(SimpleNamespace(weight=1.0, world_id="world-a"),),
        worlds=(
            ExactBeliefWorldState(
                state={"id": case_id},
                weight=1.0,
                label="world-a",
            ),
        ),
        side="p1",
        plan_limit=4,
        candidate_limit=2,
        response_limit=1,
        rng_seeds=("low", "high"),
    )


def test_executable_benchmark_uses_protect_to_preserve_unique_resource() -> None:
    execution = _run_anchor_benchmark(
        "protect-unique-resource",
        ProtectAnchorWorker(),
    )

    assert execution.result.status == "pass"
    assert execution.generated_plan_names == ("preserve-anchor",)
    assert execution.probed_plan_names == ("preserve-anchor",)
    assert execution.selected_probe is not None
    assert execution.selected_probe.chosen.choice == ProtectAnchorWorker.protect
    assert execution.selected_probe.sampled_robust is True


def test_executable_benchmark_switches_when_protect_does_not_preserve_resource() -> None:
    execution = _run_anchor_benchmark(
        "switch-unique-resource",
        SwitchAnchorWorker(),
    )

    assert execution.result.status == "pass"
    assert execution.generated_plan_names == ("preserve-anchor",)
    assert execution.probed_plan_names == ("preserve-anchor",)
    assert execution.selected_probe is not None
    assert execution.selected_probe.chosen.choice == SwitchAnchorWorker.switch
    assert execution.selected_probe.sampled_robust is True


def _gap_public_view(
    *,
    team_species: tuple[str, str, str, str],
    active_species: tuple[str, str],
    boosted_foe: bool = False,
) -> dict:
    team = []
    for species in team_species:
        team.append(
            {
                "species": species,
                "hp_percent": 100,
                "fainted": False,
                "active": species in active_species,
                "ability": "",
                "moves": ["Attack"],
            }
        )
    return {
        "turn": 6,
        "phase": "move",
        "field": {
            "weather": None,
            "terrain": None,
            "pseudo_weather": [],
        },
        "player": {
            "name": "Practice AI",
            "side_conditions": [],
            "team": team,
            "active_details": [
                {"species": species, "moves": ["Attack"]}
                for species in active_species
            ],
        },
        "opponent": {
            "name": "Human",
            "preview_species": ["BoostedFoe", "FoeB", "FoeC", "FoeD"],
            "side_conditions": [],
            "active": [
                {
                    "species": "BoostedFoe",
                    "base_species": "BoostedFoe",
                    "hp_percent": 100,
                    "status": None,
                    "boosts": {"atk": 1} if boosted_foe else {},
                    "fainted": False,
                },
                {
                    "species": "FoeB",
                    "base_species": "FoeB",
                    "hp_percent": 100,
                    "status": None,
                    "boosts": {},
                    "fainted": False,
                },
            ],
            "revealed": [],
        },
    }


def _targeting_summary(*, focus_boosted: bool) -> dict:
    attacker_a = _benchmark_mon("AttackerA", 100, 120)
    attacker_b = _benchmark_mon("AttackerB", 100, 110)
    bench_a = _benchmark_mon("BenchA", 100, 100)
    bench_b = _benchmark_mon("BenchB", 100, 90)
    boosted = _benchmark_mon(
        "BoostedFoe",
        0 if focus_boosted else 100,
        105,
    )
    boosted["boosts"] = {"atk": 1 if focus_boosted else 2}
    foe_b = _benchmark_mon("FoeB", 100 if focus_boosted else 0, 95)
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
            "pokemon": [attacker_a, attacker_b, bench_a, bench_b],
            "active": [attacker_a, attacker_b],
            "sideConditions": [],
        },
        "p2": {
            "name": "Human",
            "pokemon": [boosted, foe_b],
            "active": [boosted, foe_b],
            "sideConditions": [],
        },
    }


class TargetingWorker:
    focus_boosted = "move attack +1, move attack +1"
    focus_other = "move attack +2, move attack +2"
    response = "move attack +1, move attack +2"

    def legal_choices(self, *, state, side):
        if side == "p1":
            return [self.focus_boosted, self.focus_other]
        return [self.response]

    def branch_many(self, *, state, branches):
        return [
            {
                "index": index,
                "summary": _targeting_summary(
                    focus_boosted=branch["p1_choice"] == self.focus_boosted,
                ),
            }
            for index, branch in enumerate(branches)
        ]


class GapWorker:
    def legal_choices(self, *, state, side):
        if side == "p1":
            return [
                "move attack +1, move attack +1",
                "move attack +2, move attack +2",
            ]
        return ["move attack +1, move attack +2"]

    def branch_many(self, *, state, branches):
        raise AssertionError("known-gap plan should not reach exact probing")


def test_boosted_threat_targeting_passes_exact_evidence() -> None:
    execution = run_generated_strategy_benchmark(
        TargetingWorker(),
        case=_case("boosted-threat-targeting-evidence"),
        view=_gap_public_view(
            team_species=("AttackerA", "AttackerB", "BenchA", "BenchB"),
            active_species=("AttackerA", "AttackerB"),
            boosted_foe=True,
        ),
        particles=(SimpleNamespace(weight=1.0, world_id="world-a"),),
        worlds=(
            ExactBeliefWorldState(
                state={"id": "boosted-target"},
                weight=1.0,
                label="world-a",
            ),
        ),
        side="p1",
        candidate_limit=2,
        response_limit=1,
        rng_seeds=("low", "high"),
    )

    assert execution.result.status == "pass"
    assert execution.probed_plan_names == ("neutralize-boosted-boostedfoe",)
    assert execution.selected_probe is not None
    assert execution.selected_probe.chosen.choice == TargetingWorker.focus_boosted
    assert execution.selected_probe.sampled_robust is True

    probe = execution.selected_probe
    wrong = next(
        candidate
        for candidate in probe.ranking
        if candidate.choice == TargetingWorker.focus_other
    )
    assert wrong.evaluation.robust is False
    assert wrong.worst_world_outcomes[0].triggered_failures == (
        "threat-snowballs:boostedfoe",
    )


def _pairing_public_view() -> dict:
    view = _gap_public_view(
        team_species=("Partner", "Rillaboom", "Gardevoir", "Sneasler"),
        active_species=("Partner", "Rillaboom"),
    )
    team = view["player"]["team"]
    team[1]["ability"] = "Grassy Surge"
    team[2]["moves"] = ["Trick Room", "Attack"]
    view["player"]["active_details"] = [
        {"species": "Partner", "moves": ["Attack"]},
        {"species": "Rillaboom", "moves": ["Attack"]},
    ]
    return view


def _pairing_summary(*, gardevoir_active: bool) -> dict:
    partner = _benchmark_mon("Partner", 100, 60)
    rillaboom = _benchmark_mon("Rillaboom", 100, 85)
    gardevoir = _benchmark_mon("Gardevoir", 100, 100)
    sneasler = _benchmark_mon("Sneasler", 100, 120)
    foe_a = _benchmark_mon("BoostedFoe", 100, 105)
    foe_b = _benchmark_mon("FoeB", 100, 90)
    active = [gardevoir, rillaboom] if gardevoir_active else [partner, rillaboom]
    return {
        "ended": False,
        "winner": None,
        "requestState": "move",
        "field": {
            "weather": None,
            "terrain": "grassyterrain",
            "pseudoWeather": [],
        },
        "p1": {
            "name": "Practice AI",
            "pokemon": [partner, rillaboom, gardevoir, sneasler],
            "active": active,
            "sideConditions": [],
        },
        "p2": {
            "name": "Human",
            "pokemon": [foe_a, foe_b],
            "active": [foe_a, foe_b],
            "sideConditions": [],
        },
    }


class PairingWorker:
    switch = "switch 3, move attack +1"
    stay = "move attack +1, move attack +1"
    response = "move attack +1, move attack +2"

    def legal_choices(self, *, state, side):
        return [self.switch, self.stay] if side == "p1" else [self.response]

    def branch_many(self, *, state, branches):
        return [
            {
                "index": index,
                "summary": _pairing_summary(
                    gardevoir_active=branch["p1_choice"] == self.switch,
                ),
            }
            for index, branch in enumerate(branches)
        ]


def test_active_pair_generation_passes_exact_safe_entry_evidence() -> None:
    execution = run_generated_strategy_benchmark(
        PairingWorker(),
        case=_case("auto-generate-active-pair"),
        view=_pairing_public_view(),
        particles=(SimpleNamespace(weight=1.0, world_id="world-a"),),
        worlds=(
            ExactBeliefWorldState(
                state={"id": "pairing"},
                weight=1.0,
                label="world-a",
            ),
        ),
        side="p1",
        plan_limit=4,
        candidate_limit=2,
        response_limit=1,
        rng_seeds=("low", "high"),
    )

    assert execution.result.status == "pass"
    assert "create-gardevoir-rillaboom-board" in execution.generated_plan_names
    assert execution.selected_probe is not None
    assert execution.selected_probe.plan.name == "create-gardevoir-rillaboom-board"
    assert execution.selected_probe.chosen.choice == PairingWorker.switch
    assert execution.selected_probe.sampled_robust is True
    outcome = execution.selected_probe.chosen.worst_world_outcomes[0]
    assert set(outcome.active_resources) == {"Gardevoir", "Rillaboom"}
    assert outcome.newly_active_resources == ("Gardevoir",)


def test_sacrifice_generation_gap_remains_explicit() -> None:
    sacrifice = run_generated_strategy_benchmark(
        GapWorker(),
        case=_case("auto-generate-sacrifice-endgame"),
        view=_gap_public_view(
            team_species=("Indeedee-F", "Porygon2", "Torkoal", "Partner"),
            active_species=("Indeedee-F", "Porygon2"),
        ),
        particles=(SimpleNamespace(weight=1.0, world_id="world-a"),),
        worlds=(
            ExactBeliefWorldState(
                state={"id": "sacrifice-gap"},
                weight=1.0,
                label="world-a",
            ),
        ),
        side="p1",
        rng_seeds=("low",),
    )

    assert sacrifice.result.status == "known-gap"
    assert sacrifice.generated_plan_names == ()
    assert sacrifice.selected_probe is None
