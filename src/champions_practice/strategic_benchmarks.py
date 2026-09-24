"""Labeled strategic benchmark cases and implementation-agnostic scoring.

The benchmark catalog is a normative description of strategic outcomes we care about.
It is intentionally separate from unit-test fixtures and from live move selection so new
strategy work can be measured before it is granted more authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from champions_practice.belief_search import ExactBeliefWorldState
from champions_practice.exact_search import SideId
from champions_practice.strategy import (
    DesiredBoard,
    ResourcePurpose,
    StrategicAssessment,
    StrategicPlan,
    assess_strategic_position,
    generate_strategic_plans,
)
from champions_practice.strategy_evidence import (
    StrategicPlanProbe,
    filter_supported_plans,
    probe_strategic_plan,
    select_supported_plan,
)


@dataclass(frozen=True)
class StrategicBenchmarkExpectation:
    accepted_plan_names: tuple[str, ...] = ()
    forbidden_plan_names: tuple[str, ...] = ()
    accepted_choices: tuple[str, ...] = ()
    require_robust: bool | None = True
    required_active_pair: tuple[str, ...] = ()
    safe_entry_resources: tuple[str, ...] = ()
    resource_purposes: tuple[ResourcePurpose, ...] = ()
    required_preserve: tuple[str, ...] = ()
    required_acceptable_losses: tuple[str, ...] = ()


@dataclass(frozen=True)
class StrategicBenchmarkCase:
    case_id: str
    label: str
    category: str
    stage: str
    scenario: str
    principle: str
    expectation: StrategicBenchmarkExpectation
    known_gap: str | None = None


class _ProbeChoice(Protocol):
    choice: str


class _PlanProbe(Protocol):
    plan: StrategicPlan
    chosen: _ProbeChoice
    proven_robust: bool


@dataclass(frozen=True)
class StrategicBenchmarkObservation:
    plan_name: str | None
    choice: str | None
    robust: bool | None
    desired_board: DesiredBoard | None
    preserve: tuple[str, ...] = ()
    acceptable_losses: tuple[str, ...] = ()


@dataclass(frozen=True)
class StrategicBenchmarkResult:
    case: StrategicBenchmarkCase
    observation: StrategicBenchmarkObservation
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.failures

    @property
    def status(self) -> str:
        if self.passed:
            return "pass"
        if self.case.known_gap is not None:
            return "known-gap"
        return "fail"


@dataclass(frozen=True)
class StrategicBenchmarkExecution:
    case: StrategicBenchmarkCase
    assessment: StrategicAssessment
    generated_plan_names: tuple[str, ...]
    probed_plan_names: tuple[str, ...]
    probes: tuple[StrategicPlanProbe, ...]
    selected_probe: StrategicPlanProbe | None
    result: StrategicBenchmarkResult
    exact_branch_count: int
    response_screening_branch_count: int

    @property
    def passed(self) -> bool:
        return self.result.passed


@dataclass(frozen=True)
class StrategicBenchmarkSuite:
    results: tuple[StrategicBenchmarkResult, ...]

    @property
    def regressions(self) -> tuple[StrategicBenchmarkResult, ...]:
        return tuple(result for result in self.results if result.status == "fail")

    @property
    def known_gaps(self) -> tuple[StrategicBenchmarkResult, ...]:
        return tuple(result for result in self.results if result.status == "known-gap")

    @property
    def passed(self) -> bool:
        return not self.regressions


def observation_from_plan(
    plan: StrategicPlan | None,
    *,
    choice: str | None = None,
    robust: bool | None = None,
) -> StrategicBenchmarkObservation:
    """Create a benchmark observation from an inspectable strategy plan."""
    if plan is None:
        return StrategicBenchmarkObservation(
            plan_name=None,
            choice=choice,
            robust=robust,
            desired_board=None,
        )
    return StrategicBenchmarkObservation(
        plan_name=plan.name,
        choice=choice,
        robust=robust,
        desired_board=plan.desired_board,
        preserve=plan.preserve,
        acceptable_losses=plan.acceptable_losses,
    )


def observation_from_probe(
    probe: _PlanProbe | None,
) -> StrategicBenchmarkObservation:
    """Create a benchmark observation from an exact strategic plan probe."""
    if probe is None:
        return observation_from_plan(None)
    return observation_from_plan(
        probe.plan,
        choice=probe.chosen.choice,
        robust=probe.proven_robust,
    )


def _purpose_keys(
    purposes: Iterable[ResourcePurpose],
) -> set[tuple[str, str, str]]:
    return {
        (purpose.species, purpose.purpose, purpose.position)
        for purpose in purposes
    }


def evaluate_strategic_benchmark(
    case: StrategicBenchmarkCase,
    observation: StrategicBenchmarkObservation,
) -> StrategicBenchmarkResult:
    """Compare one observed strategic result against its labeled expectation."""
    expected = case.expectation
    failures: list[str] = []

    if (
        expected.accepted_plan_names
        and observation.plan_name not in expected.accepted_plan_names
    ):
        failures.append(
            "selected plan "
            f"{observation.plan_name!r} not in accepted set "
            f"{expected.accepted_plan_names!r}"
        )
    if observation.plan_name in expected.forbidden_plan_names:
        failures.append(f"selected forbidden plan {observation.plan_name!r}")
    if expected.accepted_choices and observation.choice not in expected.accepted_choices:
        failures.append(
            "selected choice "
            f"{observation.choice!r} not in accepted set "
            f"{expected.accepted_choices!r}"
        )
    if (
        expected.require_robust is not None
        and observation.robust is not expected.require_robust
    ):
        failures.append(
            f"robust={observation.robust!r}; expected {expected.require_robust!r}"
        )

    board = observation.desired_board
    if (
        expected.required_active_pair
        or expected.safe_entry_resources
        or expected.resource_purposes
    ) and board is None:
        failures.append("selected result has no DesiredBoard")
    elif board is not None:
        if (
            expected.required_active_pair
            and set(board.required_active_pair) != set(expected.required_active_pair)
        ):
            failures.append(
                "desired active pair "
                f"{board.required_active_pair!r}; expected "
                f"{expected.required_active_pair!r}"
            )
        if (
            expected.safe_entry_resources
            and not set(expected.safe_entry_resources).issubset(
                board.safe_entry_resources
            )
        ):
            failures.append(
                "safe-entry resources "
                f"{board.safe_entry_resources!r}; expected at least "
                f"{expected.safe_entry_resources!r}"
            )
        expected_purposes = _purpose_keys(expected.resource_purposes)
        actual_purposes = _purpose_keys(board.resource_purposes)
        missing_purposes = expected_purposes.difference(actual_purposes)
        if missing_purposes:
            failures.append(
                "missing resource purposes "
                + ", ".join(
                    f"{species}={purpose} ({position})"
                    for species, purpose, position in sorted(missing_purposes)
                )
            )

    if (
        expected.required_preserve
        and not set(expected.required_preserve).issubset(observation.preserve)
    ):
        failures.append(
            f"preserve={observation.preserve!r}; expected at least "
            f"{expected.required_preserve!r}"
        )
    if (
        expected.required_acceptable_losses
        and not set(expected.required_acceptable_losses).issubset(
            observation.acceptable_losses
        )
    ):
        failures.append(
            f"acceptable_losses={observation.acceptable_losses!r}; expected at least "
            f"{expected.required_acceptable_losses!r}"
        )

    return StrategicBenchmarkResult(
        case=case,
        observation=observation,
        failures=tuple(failures),
    )


def evaluate_strategic_benchmark_suite(
    cases: Iterable[StrategicBenchmarkCase],
    observations: dict[str, StrategicBenchmarkObservation],
) -> StrategicBenchmarkSuite:
    """Evaluate a benchmark corpus while keeping known gaps separate from regressions."""
    results = []
    for case in cases:
        observation = observations.get(
            case.case_id,
            StrategicBenchmarkObservation(
                plan_name=None,
                choice=None,
                robust=None,
                desired_board=None,
            ),
        )
        results.append(evaluate_strategic_benchmark(case, observation))
    return StrategicBenchmarkSuite(results=tuple(results))


def run_generated_strategy_benchmark(
    worker: Any,
    *,
    case: StrategicBenchmarkCase,
    view: dict[str, Any],
    particles: Iterable[Any],
    worlds: tuple[ExactBeliefWorldState, ...],
    side: SideId,
    plan_limit: int = 4,
    candidate_limit: int = 4,
    response_limit: int = 3,
    rng_seeds: tuple[str, ...] | None = None,
) -> StrategicBenchmarkExecution:
    """Run the production-shaped strategy pipeline for one labeled position.

    The path is intentionally the same sequence used by the live controller:
    public assessment -> plan generation -> one-turn support filtering -> exact plan probes
    -> supported-plan selection -> benchmark scoring.
    """
    if plan_limit <= 0:
        raise ValueError("plan_limit must be positive")
    if candidate_limit <= 0 or response_limit <= 0:
        raise ValueError("benchmark search limits must be positive")
    if not worlds:
        raise ValueError("benchmark requires at least one exact belief world")

    assessment = assess_strategic_position(view, particles=tuple(particles))
    generated = generate_strategic_plans(assessment, limit=None)
    supported = filter_supported_plans(generated, limit=plan_limit)

    probes = []
    for plan in supported:
        kwargs: dict[str, Any] = {
            "worlds": worlds,
            "assessment": assessment,
            "view": view,
            "side": side,
            "plan": plan,
            "candidate_limit": candidate_limit,
            "response_limit": response_limit,
        }
        if rng_seeds is not None:
            kwargs["rng_seeds"] = rng_seeds
        probes.append(probe_strategic_plan(worker, **kwargs))

    selected = select_supported_plan(tuple(probes))
    observation = observation_from_probe(selected)
    result = evaluate_strategic_benchmark(case, observation)
    return StrategicBenchmarkExecution(
        case=case,
        assessment=assessment,
        generated_plan_names=tuple(plan.name for plan in generated),
        probed_plan_names=tuple(probe.plan.name for probe in probes),
        probes=tuple(probes),
        selected_probe=selected,
        result=result,
        exact_branch_count=sum(probe.branch_count for probe in probes),
        response_screening_branch_count=sum(
            probe.response_screening_branch_count for probe in probes
        ),
    )


def format_strategic_benchmark_report(suite: StrategicBenchmarkSuite) -> str:
    """Render a compact benchmark report for CI artifacts and manual review."""
    passed = sum(result.status == "pass" for result in suite.results)
    gaps = sum(result.status == "known-gap" for result in suite.results)
    failed = sum(result.status == "fail" for result in suite.results)
    lines = [
        "Strategic benchmark report",
        f"Cases: {len(suite.results)} | pass {passed} | known-gap {gaps} | fail {failed}",
    ]
    for result in suite.results:
        lines.append(
            f"[{result.status.upper()}] {result.case.case_id}: {result.case.label}"
        )
        if result.failures:
            for failure in result.failures:
                lines.append(f"  - {failure}")
        if result.status == "known-gap" and result.case.known_gap:
            lines.append(f"  known gap: {result.case.known_gap}")
    return "\n".join(lines)


STRATEGIC_BENCHMARKS = (
    StrategicBenchmarkCase(
        case_id="sneasler-neutral-trick-room",
        label="Do not establish neutral Trick Room beside fast Sneasler",
        category="speed-control",
        stage="plan-selection",
        scenario=(
            "Indeedee-F + Sneasler can choose Psychic + Protect or Trick Room + "
            "Protect. Trick Room creates no net active-pair speed advantage."
        ),
        principle=(
            "Speed control must improve the resulting speed relationship rather than "
            "receive credit merely for existing."
        ),
        expectation=StrategicBenchmarkExpectation(
            accepted_plan_names=("preserve-indeedeef",),
            forbidden_plan_names=("establish-speed-control-indeedeef",),
            accepted_choices=("move psychic +1, move protect",),
            require_robust=True,
        ),
    ),
    StrategicBenchmarkCase(
        case_id="sneasler-neutral-trick-room-showdown",
        label="Real Showdown must not prefer neutral Trick Room beside Sneasler",
        category="speed-control",
        stage="showdown-integration",
        scenario=(
            "A real Showdown state places fast Sneasler beside slower Indeedee-F "
            "against two opponents whose speeds lie between them."
        ),
        principle=(
            "The real simulator-backed strategy stack must reject speed control that "
            "does not improve the active pair's speed relationship."
        ),
        expectation=StrategicBenchmarkExpectation(
            accepted_plan_names=("preserve-indeedeef",),
            forbidden_plan_names=("establish-speed-control-indeedeef",),
            require_robust=True,
        ),
    ),
    StrategicBenchmarkCase(
        case_id="critical-resource-over-material",
        label="Preserve a required endgame resource over immediate material",
        category="resource-preservation",
        stage="exact-plan-evidence",
        scenario=(
            "One line KOs both opposing Pokemon but loses the designated Keeper; "
            "the alternative preserves Keeper while gaining no immediate material."
        ),
        principle=(
            "A resource required by the declared endgame can be more valuable than "
            "short-term material."
        ),
        expectation=StrategicBenchmarkExpectation(
            accepted_plan_names=("preserve-keeper",),
            accepted_choices=("move protect, move protect",),
            require_robust=True,
            required_preserve=("Keeper",),
        ),
    ),
    StrategicBenchmarkCase(
        case_id="gard-rilla-safe-entry-cleanup",
        label="Create Gardevoir + Rillaboom while reserving Sneasler for cleanup",
        category="positioning",
        stage="exact-plan-evidence",
        scenario=(
            "Gardevoir begins on the bench. The desired branch switches it in beside "
            "Rillaboom while Sneasler remains in reserve."
        ),
        principle=(
            "Living material is not enough: active pairing, safe entry, and the "
            "intended role of a benched cleanup piece all matter."
        ),
        expectation=StrategicBenchmarkExpectation(
            accepted_plan_names=("gard-rilla-with-sneasler-cleanup",),
            accepted_choices=("switch 3, move protect",),
            require_robust=True,
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
    StrategicBenchmarkCase(
        case_id="support-sacrifice-for-trick-room-endgame",
        label="Allow support losses when they secure the declared endgame",
        category="sacrifice",
        stage="plan-evaluation",
        scenario=(
            "Indeedee-F and Porygon2 may be lost if the trade secures a Torkoal "
            "Trick Room endgame with enough effective turns."
        ),
        principle=(
            "Sacrifices are evaluated by whether they convert resources into a "
            "robust win condition, not by raw Pokemon count."
        ),
        expectation=StrategicBenchmarkExpectation(
            accepted_plan_names=("trick-room-sweep", "commit-trick-room"),
            require_robust=True,
            required_preserve=("Torkoal",),
            required_acceptable_losses=("Indeedee-F", "Porygon2"),
        ),
    ),
    StrategicBenchmarkCase(
        case_id="auto-generate-cleanup-purpose",
        label="Infer an offensive cleanup role from the position",
        category="plan-generation",
        stage="plan-generation",
        scenario=(
            "Sneasler should be preserved specifically as a late-game offensive "
            "cleanup piece rather than merely because it owns a generic utility role."
        ),
        principle=(
            "Purpose-specific endgame roles should eventually be generated from "
            "position and matchup evidence, not hard-coded by species."
        ),
        expectation=StrategicBenchmarkExpectation(
            require_robust=None,
            resource_purposes=(
                ResourcePurpose(
                    species="Sneasler",
                    purpose="cleanup",
                    position="bench",
                ),
            ),
        ),
        known_gap=(
            "Current plan generation identifies generic/unique utility roles but does "
            "not yet infer offensive cleanup roles from matchup state."
        ),
    ),
)
