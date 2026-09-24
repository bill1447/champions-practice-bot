"""Exact one-ply evidence for strategic plan viability across belief worlds."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from champions_practice.belief_search import (
    BeliefPruningResult,
    BeliefSearchWorker,
    ExactBeliefWorldState,
    shortlist_belief_candidates,
    shortlist_belief_responses,
)
from champions_practice.exact_search import SideId, score_exact_summary_breakdown
from champions_practice.recommendations import SCREENING_RNG_SEEDS
from champions_practice.strategy import (
    PlanWorldOutcome,
    StrategicAssessment,
    StrategicPlan,
    StrategicPlanEvaluation,
    evaluate_strategic_plan,
)
from champions_practice.strategy_tactics import guidance_from_plan


@dataclass(frozen=True)
class PlanProbeCandidate:
    choice: str
    evaluation: StrategicPlanEvaluation
    worst_world_outcomes: tuple[PlanWorldOutcome, ...]
    worst_board_score: float
    weighted_board_score: float
    failure_penalty: float


@dataclass(frozen=True)
class StrategicPlanProbe:
    plan: StrategicPlan
    chosen: PlanProbeCandidate
    ranking: tuple[PlanProbeCandidate, ...]
    pruning: BeliefPruningResult
    branch_count: int
    response_screening_branch_count: int
    unsupported_conditions: tuple[str, ...]
    unresolved_failure_conditions: tuple[str, ...]
    proven_robust: bool
    total_seconds: float = field(compare=False)


def _id(value: object) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def _resource_id(value: object) -> str:
    result = _id(value)
    for suffix in ("megax", "megay", "mega"):
        if result.endswith(suffix):
            return result[: -len(suffix)]
    return result


def _side_ids(side: SideId) -> tuple[SideId, SideId]:
    return side, "p2" if side == "p1" else "p1"


def _summary_side(summary: dict[str, Any], side: SideId) -> dict[str, Any]:
    value = summary.get(side)
    return value if isinstance(value, dict) else {}


def _field(summary: dict[str, Any]) -> dict[str, Any]:
    value = summary.get("field")
    return value if isinstance(value, dict) else {}


def _condition_ids(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    result = set()
    for value in values:
        if isinstance(value, str):
            result.add(_id(value))
        elif isinstance(value, dict):
            result.add(_id(value.get("id", "")))
    return result


def _side_conditions(summary: dict[str, Any], side: SideId) -> set[str]:
    return _condition_ids(_summary_side(summary, side).get("sideConditions", []))


def _pseudo_weather(summary: dict[str, Any]) -> set[str]:
    return _condition_ids(_field(summary).get("pseudoWeather", []))


def _pokemon_entries(summary: dict[str, Any], side: SideId) -> tuple[dict[str, Any], ...]:
    values = _summary_side(summary, side).get("pokemon", [])
    if not isinstance(values, list):
        return ()
    return tuple(value for value in values if isinstance(value, dict))


def _active_entries(summary: dict[str, Any], side: SideId) -> tuple[dict[str, Any], ...]:
    values = _summary_side(summary, side).get("active", [])
    if not isinstance(values, list):
        return ()
    return tuple(value for value in values if isinstance(value, dict))


def _is_living(pokemon: dict[str, Any]) -> bool:
    return not bool(pokemon.get("fainted", False)) and int(pokemon.get("hp", 0)) > 0


def _living_summary_ids(summary: dict[str, Any], side: SideId) -> set[str]:
    return {
        _resource_id(pokemon.get("species", ""))
        for pokemon in _pokemon_entries(summary, side)
        if _is_living(pokemon)
    }


def _pokemon_percent(pokemon: dict[str, Any]) -> float:
    maximum = max(1, int(pokemon.get("maxhp", 1)))
    return 100.0 * max(0, int(pokemon.get("hp", 0))) / maximum


def _find_species(
    values: tuple[dict[str, Any], ...],
    species: str,
) -> dict[str, Any] | None:
    wanted = _resource_id(species)
    return next(
        (
            pokemon
            for pokemon in values
            if _resource_id(pokemon.get("species", "")) == wanted
        ),
        None,
    )


def _opponent_progress(
    assessment: StrategicAssessment,
    summary: dict[str, Any],
    opponent: SideId,
) -> bool:
    pokemon = _pokemon_entries(summary, opponent)
    for threat in assessment.threats:
        if threat.urgency != "immediate" or threat.hp_percent is None:
            continue
        after = _find_species(pokemon, threat.species)
        if after is None:
            continue
        if not _is_living(after):
            return True
        if _pokemon_percent(after) < threat.hp_percent - 0.5:
            return True
    return False


def _threat_fainted(
    summary: dict[str, Any],
    opponent: SideId,
    species_id: str,
) -> bool:
    for pokemon in _pokemon_entries(summary, opponent):
        if _resource_id(pokemon.get("species", "")) != _resource_id(species_id):
            continue
        return not _is_living(pokemon)
    return False


def _supported_condition(condition: str) -> bool:
    return condition in {
        "favorable-speed-control",
        "trickroom-progress",
        "tailwind-progress",
        "our-speed-control",
    } or condition.startswith("threat-neutralized:")


def _supported_failure(condition: str) -> bool:
    return condition in {
        "critical-resource-lost-during-tailwind",
        "speed-control-denied",
        "trickroom-expired-before-progress",
        "tailwind-expired-before-progress",
    } or condition.startswith("critical-resource-lost:")


def plan_is_one_turn_supported(plan: StrategicPlan) -> bool:
    """Return whether the one-turn evidence probe can evaluate every plan requirement."""
    return all(
        _supported_condition(condition)
        for condition in plan.desired_board.required_conditions
    ) and all(_supported_failure(condition) for condition in plan.failure_conditions)


def filter_supported_plans(
    plans: tuple[StrategicPlan, ...],
    *,
    limit: int,
) -> tuple[StrategicPlan, ...]:
    """Filter unprobeable plans before applying the live strategic-plan budget."""
    if limit <= 0:
        raise ValueError("plan limit must be positive")
    supported = tuple(plan for plan in plans if plan_is_one_turn_supported(plan))
    return supported[:limit]


def _favorable_speed_control(summary: dict[str, Any], side: SideId) -> bool:
    """Judge whether the resulting speed state favors the acting side's active pair."""
    own, opponent = _side_ids(side)
    own_active = tuple(
        pokemon for pokemon in _active_entries(summary, own) if _is_living(pokemon)
    )
    opponent_active = tuple(
        pokemon for pokemon in _active_entries(summary, opponent) if _is_living(pokemon)
    )
    if not own_active or not opponent_active:
        return False

    own_tailwind = "tailwind" in _side_conditions(summary, own)
    opponent_tailwind = "tailwind" in _side_conditions(summary, opponent)
    trick_room = "trickroom" in _pseudo_weather(summary)

    own_speeds = [
        int(pokemon.get("speed", 0)) * (2 if own_tailwind else 1)
        for pokemon in own_active
    ]
    opponent_speeds = [
        int(pokemon.get("speed", 0)) * (2 if opponent_tailwind else 1)
        for pokemon in opponent_active
    ]

    advantage = 0
    for own_speed in own_speeds:
        for opponent_speed in opponent_speeds:
            if own_speed == opponent_speed:
                continue
            acts_first = (
                own_speed < opponent_speed
                if trick_room
                else own_speed > opponent_speed
            )
            advantage += 1 if acts_first else -1
    return advantage > 0


def _outcome_from_summary(
    plan: StrategicPlan,
    assessment: StrategicAssessment,
    *,
    summary: dict[str, Any],
    side: SideId,
    label: str,
    weight: float,
) -> PlanWorldOutcome:
    own, opponent = _side_ids(side)
    living_after_ids = _living_summary_ids(summary, own)
    living_before = tuple(resource for resource in assessment.resources if not resource.fainted)

    living_resources = tuple(
        resource.species
        for resource in living_before
        if _resource_id(resource.species) in living_after_ids
    )
    lost_resources = tuple(
        resource.species
        for resource in living_before
        if _resource_id(resource.species) not in living_after_ids
    )

    active_after_ids = {
        _resource_id(pokemon.get("species", ""))
        for pokemon in _active_entries(summary, own)
        if _is_living(pokemon)
    }
    active_before_ids = {
        _resource_id(resource.species)
        for resource in assessment.resources
        if resource.active and not resource.fainted
    }
    active_resources = tuple(
        resource.species
        for resource in living_before
        if _resource_id(resource.species) in active_after_ids
    )
    newly_active_resources = tuple(
        species
        for species in active_resources
        if _resource_id(species) not in active_before_ids
    )

    pseudo = _pseudo_weather(summary)
    own_conditions = _side_conditions(summary, own)
    opponent_conditions = _side_conditions(summary, opponent)
    progress = _opponent_progress(assessment, summary, opponent)

    conditions: set[str] = set()
    has_our_speed_control = "trickroom" in pseudo or "tailwind" in own_conditions
    if has_our_speed_control:
        conditions.add("our-speed-control")
        if _favorable_speed_control(summary, side):
            conditions.add("favorable-speed-control")
    if assessment.speed_control.trick_room_active and "trickroom" in pseudo and progress:
        conditions.add("trickroom-progress")
    if assessment.speed_control.our_tailwind and "tailwind" in own_conditions and progress:
        conditions.add("tailwind-progress")
    if assessment.speed_control.opponent_tailwind and "tailwind" not in opponent_conditions:
        conditions.add("opponent-tailwind-expired")

    for condition in plan.desired_board.required_conditions:
        if not condition.startswith("threat-neutralized:"):
            continue
        species = condition.split(":", 1)[1]
        if _threat_fainted(summary, opponent, species):
            conditions.add(condition)

    failures: set[str] = set()
    lost_ids = {_resource_id(resource) for resource in lost_resources}
    for failure in plan.failure_conditions:
        if failure == "critical-resource-lost-during-tailwind":
            preserve_ids = {_resource_id(resource) for resource in plan.preserve}
            if assessment.speed_control.opponent_tailwind and preserve_ids.intersection(lost_ids):
                failures.add(failure)
        elif failure == "speed-control-denied":
            if "favorable-speed-control" not in conditions:
                failures.add(failure)
        elif failure == "trickroom-expired-before-progress":
            if (
                assessment.speed_control.trick_room_active
                and "trickroom" not in pseudo
                and "trickroom-progress" not in conditions
            ):
                failures.add(failure)
        elif failure == "tailwind-expired-before-progress":
            if (
                assessment.speed_control.our_tailwind
                and "tailwind" not in own_conditions
                and "tailwind-progress" not in conditions
            ):
                failures.add(failure)
        elif failure.startswith("critical-resource-lost:"):
            species = failure.split(":", 1)[1]
            if _resource_id(species) in lost_ids:
                failures.add(failure)

    demonstrated = bool(set(plan.desired_board.required_conditions).intersection(conditions))
    return PlanWorldOutcome(
        label=label,
        weight=weight,
        conditions=tuple(sorted(conditions)),
        living_resources=living_resources,
        effective_turns=1 if demonstrated else 0,
        lost_resources=lost_resources,
        triggered_failures=tuple(sorted(failures)),
        active_resources=active_resources,
        newly_active_resources=newly_active_resources,
    )


def _failure_penalty(evaluation: StrategicPlanEvaluation) -> float:
    return (
        evaluation.preserve_failure_mass
        + evaluation.required_resource_failure_mass
        + evaluation.condition_failure_mass
        + evaluation.timing_failure_mass
        + evaluation.declared_failure_mass
        + evaluation.unacceptable_loss_mass
        + evaluation.active_pair_failure_mass
        + evaluation.safe_entry_failure_mass
        + evaluation.purpose_failure_mass
    )


def _worst_branch(
    plan: StrategicPlan,
    assessment: StrategicAssessment,
    *,
    side: SideId,
    label: str,
    weight: float,
    branches: list[tuple[str, str | None, dict[str, Any]]],
) -> tuple[PlanWorldOutcome, float]:
    scored: list[tuple[float, float, str, str, PlanWorldOutcome]] = []
    for response, rng_seed, summary in branches:
        outcome = _outcome_from_summary(
            plan,
            assessment,
            summary=summary,
            side=side,
            label=label,
            weight=weight,
        )
        evaluation = evaluate_strategic_plan(
            plan,
            outcomes=(outcome,),
            robust_threshold=1.0,
        )
        board_score = score_exact_summary_breakdown(summary, side).total
        scored.append(
            (
                _failure_penalty(evaluation),
                -board_score,
                response,
                rng_seed or "",
                outcome,
            )
        )
    if not scored:
        raise ValueError("plan probe has no exact branches to evaluate")
    worst = max(scored, key=lambda value: (value[0], value[1], value[2], value[3]))
    return worst[4], -worst[1]


def probe_strategic_plan(
    worker: BeliefSearchWorker,
    *,
    worlds: tuple[ExactBeliefWorldState, ...],
    assessment: StrategicAssessment,
    view: dict[str, Any],
    side: SideId,
    plan: StrategicPlan,
    candidate_limit: int = 4,
    response_limit: int = 3,
    rng_seeds: tuple[str, ...] = SCREENING_RNG_SEEDS,
    robust_threshold: float = 0.8,
) -> StrategicPlanProbe:
    """Probe whether a plan has a robust exact one-turn tactical path.

    Candidate and response spaces remain bounded. Every retained candidate is resolved by
    Showdown against the selected adversarial replies and RNG futures in each belief world.
    Resulting boards are judged directly against the plan rather than against the generic
    material/position evaluator.
    """
    if not worlds:
        raise ValueError("worlds must not be empty")
    if candidate_limit <= 0 or response_limit <= 0:
        raise ValueError("plan probe limits must be positive")
    if not rng_seeds:
        raise ValueError("plan probe rng_seeds must not be empty")

    started = perf_counter()
    guidance = guidance_from_plan(plan, view=view)
    pruning = shortlist_belief_candidates(
        worker,
        worlds=worlds,
        side=side,
        candidate_limit=candidate_limit,
        reference_limit=1,
        guidance=guidance,
    )
    choices = list(pruning.candidate_shortlist)
    opponent: SideId = "p2" if side == "p1" else "p1"

    outcomes_by_choice: dict[str, list[PlanWorldOutcome]] = {
        choice: [] for choice in choices
    }
    board_scores_by_choice: dict[str, list[tuple[float, float]]] = {
        choice: [] for choice in choices
    }
    exact_branch_count = 0
    response_screening_count = 0

    for index, world in enumerate(worlds, start=1):
        legal_responses = worker.legal_choices(state=world.state, side=opponent)
        response_pruning = shortlist_belief_responses(
            worker,
            world=world,
            ai_side=side,
            candidate_references=choices,
            response_limit=response_limit,
            legal_responses=legal_responses,
        )
        response_screening_count += response_pruning.screening_branch_count
        responses = list(response_pruning.response_shortlist)

        requested: list[dict[str, str]] = []
        metadata: list[tuple[str, str, str]] = []
        for choice in choices:
            for response in responses:
                for rng_seed in rng_seeds:
                    branch = (
                        {"p1_choice": choice, "p2_choice": response, "rng_seed": rng_seed}
                        if side == "p1"
                        else {"p1_choice": response, "p2_choice": choice, "rng_seed": rng_seed}
                    )
                    requested.append(branch)
                    metadata.append((choice, response, rng_seed))

        resolved = worker.branch_many(state=world.state, branches=requested)
        if len(resolved) != len(metadata):
            raise RuntimeError("unexpected number of strategic plan probe branches")
        exact_branch_count += len(requested)

        branches_by_choice: dict[
            str,
            list[tuple[str, str | None, dict[str, Any]]],
        ] = {choice: [] for choice in choices}
        for (choice, response, rng_seed), result in zip(metadata, resolved, strict=True):
            summary = result.get("summary")
            if not isinstance(summary, dict):
                raise RuntimeError("strategic plan probe branch is missing a summary")
            branches_by_choice[choice].append((response, rng_seed, summary))

        label = world.label or f"world-{index}"
        for choice in choices:
            outcome, board_score = _worst_branch(
                plan,
                assessment,
                side=side,
                label=label,
                weight=world.weight,
                branches=branches_by_choice[choice],
            )
            outcomes_by_choice[choice].append(outcome)
            board_scores_by_choice[choice].append((world.weight, board_score))

    candidate_scores = []
    for choice in choices:
        outcomes = tuple(outcomes_by_choice[choice])
        evaluation = evaluate_strategic_plan(
            plan,
            outcomes=outcomes,
            robust_threshold=robust_threshold,
        )
        board_scores = board_scores_by_choice[choice]
        total_weight = sum(weight for weight, _ in board_scores)
        candidate_scores.append(
            PlanProbeCandidate(
                choice=choice,
                evaluation=evaluation,
                worst_world_outcomes=outcomes,
                worst_board_score=min(score for _, score in board_scores),
                weighted_board_score=(
                    sum(weight * score for weight, score in board_scores)
                    / total_weight
                ),
                failure_penalty=_failure_penalty(evaluation),
            )
        )

    ranking = tuple(
        sorted(
            candidate_scores,
            key=lambda candidate: (
                -int(candidate.evaluation.robust),
                -candidate.evaluation.viable_belief_mass,
                candidate.failure_penalty,
                -candidate.worst_board_score,
                -candidate.weighted_board_score,
                candidate.choice,
            ),
        )
    )
    unsupported = tuple(
        sorted(
            condition
            for condition in plan.desired_board.required_conditions
            if not _supported_condition(condition)
        )
    )
    unresolved = tuple(
        sorted(
            condition
            for condition in plan.failure_conditions
            if not _supported_failure(condition)
        )
    )
    chosen = ranking[0]
    proven_robust = (
        chosen.evaluation.robust
        and not unsupported
        and not unresolved
    )
    return StrategicPlanProbe(
        plan=plan,
        chosen=chosen,
        ranking=ranking,
        pruning=pruning,
        branch_count=exact_branch_count,
        response_screening_branch_count=response_screening_count,
        unsupported_conditions=unsupported,
        unresolved_failure_conditions=unresolved,
        proven_robust=proven_robust,
        total_seconds=perf_counter() - started,
    )


def format_strategic_plan_probe(probe: StrategicPlanProbe) -> str:
    """Render exact plan evidence while preserving its bounded-search limitations."""
    lines = [
        f"Strategic plan probe: {probe.plan.name}",
        "  Scope: exact one-turn branches over bounded candidates, adversarial replies, "
        "belief worlds, and RNG futures; not a proof of optimal play",
        f"  Best probe action: {probe.chosen.choice}",
        f"  Posterior coverage: {probe.chosen.evaluation.viable_belief_mass:.1%}",
        f"  Cross-plan board utility: worst {probe.chosen.worst_board_score:.1f}; "
        f"weighted {probe.chosen.weighted_board_score:.1f}",
        f"  Evidence status: {'proven robust' if probe.proven_robust else 'incomplete/fragile'}",
    ]
    desired = probe.plan.desired_board
    if desired.required_active_pair:
        lines.append(
            "  Desired active pair: " + " + ".join(desired.required_active_pair)
        )
    if desired.safe_entry_resources:
        lines.append(
            "  Safe entry: " + ", ".join(desired.safe_entry_resources)
        )
    if desired.resource_purposes:
        lines.append(
            "  Resource purposes: "
            + ", ".join(
                f"{purpose.species}={purpose.purpose} ({purpose.position})"
                for purpose in desired.resource_purposes
            )
        )
    if probe.unsupported_conditions:
        lines.append(
            "  Unsupported desired conditions: " + ", ".join(probe.unsupported_conditions)
        )
    if probe.unresolved_failure_conditions:
        lines.append(
            "  Unresolved failure conditions: "
            + ", ".join(probe.unresolved_failure_conditions)
        )
    lines.append(
        f"  Cost: {probe.branch_count} exact plan branches + "
        f"{probe.response_screening_branch_count} response-screening branches"
    )
    return "\n".join(lines)



def select_supported_plan(
    probes: tuple[StrategicPlanProbe, ...],
) -> StrategicPlanProbe | None:
    """Choose the strongest fully supported robust plan, if one exists.

    Unsupported or unresolved plans receive no live strategic authority. Among proven
    plans, prefer posterior coverage, then the stronger exact resulting board, then
    lower aggregate failure mass. Plan names are only a deterministic final tie-breaker.
    """
    supported = [probe for probe in probes if probe.proven_robust]
    if not supported:
        return None
    return min(
        supported,
        key=lambda probe: (
            -probe.chosen.evaluation.viable_belief_mass,
            -probe.chosen.worst_board_score,
            -probe.chosen.weighted_board_score,
            probe.chosen.failure_penalty,
            probe.plan.name,
        ),
    )
