from types import SimpleNamespace

from champions_practice.strategic_benchmarks import (
    STRATEGIC_BENCHMARKS,
    StrategicBenchmarkObservation,
    evaluate_strategic_benchmark,
    evaluate_strategic_benchmark_suite,
    format_strategic_benchmark_report,
    observation_from_plan,
    observation_from_probe,
)
from champions_practice.strategy import DesiredBoard, ResourcePurpose, StrategicPlan


def _case(case_id: str):
    return next(case for case in STRATEGIC_BENCHMARKS if case.case_id == case_id)


def test_benchmark_catalog_has_unique_ids_and_expected_known_gap() -> None:
    ids = [case.case_id for case in STRATEGIC_BENCHMARKS]

    assert len(ids) == len(set(ids))
    assert len(STRATEGIC_BENCHMARKS) >= 5

    known_gaps = [case for case in STRATEGIC_BENCHMARKS if case.known_gap]
    assert [case.case_id for case in known_gaps] == [
        "auto-generate-cleanup-purpose"
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
        proven_robust=True,
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
    }

    suite = evaluate_strategic_benchmark_suite(
        STRATEGIC_BENCHMARKS,
        observations,
    )

    assert suite.passed is True
    assert suite.regressions == ()
    assert [result.case.case_id for result in suite.known_gaps] == [
        "auto-generate-cleanup-purpose"
    ]

    report = format_strategic_benchmark_report(suite)
    assert "pass 4 | known-gap 1 | fail 0" in report
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
