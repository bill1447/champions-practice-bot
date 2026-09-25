"""Exact bounded search across multiple public-belief worlds."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from statistics import fmean
from time import perf_counter
from typing import Any, Protocol

from champions_practice.exact_search import (
    ExactChoiceScore,
    ExactScoreBreakdown,
    SideId,
    score_exact_summary_breakdown,
    search_exact_turn,
)
from champions_practice.recommendations import (
    SCREENING_RNG_SEEDS,
    _diversified_top,
    _reference_choices,
    _strategy_families,
)
from champions_practice.strategy_tactics import (
    StrategicCandidateGuidance,
    choice_matches_guidance,
    reserve_strategic_candidate,
)

BELIEF_RESPONSE_SCREENING_RNG_SEEDS = (SCREENING_RNG_SEEDS[0],)


class BeliefSearchWorker(Protocol):
    def legal_choices(self, *, state: dict[str, Any], side: str) -> list[str]: ...

    def branch_many(
        self,
        *,
        state: dict[str, Any],
        branches: list[dict[str, Any]],
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class ExactBeliefWorldState:
    state: dict[str, Any]
    weight: float
    label: str = ""

    def __post_init__(self) -> None:
        if self.weight <= 0:
            raise ValueError("belief-world weight must be positive")


@dataclass(frozen=True)
class BeliefWorldOutcome:
    label: str
    weight: float
    worst_score: float
    mean_response_score: float
    worst_response: str
    legal_response_count: int
    score_breakdown: ExactScoreBreakdown | None = None
    worst_sample_score: float | None = None
    worst_sample_summary: dict[str, Any] | None = field(default=None, compare=False)
    worst_sample_rng_seed: str | None = None


@dataclass(frozen=True)
class BeliefPruningScore:
    choice: str
    worst_score: float
    mean_score: float
    best_score: float
    worst_response: str = ""
    score_breakdown: ExactScoreBreakdown | None = None
    worst_sample_score: float | None = None
    worst_sample_summary: dict[str, Any] | None = field(default=None, compare=False)


@dataclass(frozen=True)
class BeliefChoiceScore:
    choice: str
    worst_world_score: float
    weighted_score: float
    mean_world_score: float
    worlds: tuple[BeliefWorldOutcome, ...]


@dataclass(frozen=True)
class BeliefSearchTiming:
    total_seconds: float
    candidate_legal_seconds: float
    response_legal_seconds: float
    response_screening_seconds: float
    branch_seconds: float
    scoring_seconds: float
    legal_cache_hits: int
    legal_cache_misses: int


@dataclass(frozen=True)
class BeliefPruningResult:
    legal_choice_count: int
    strategic_choice_count: int
    candidate_shortlist: tuple[str, ...]
    screening_branch_count: int
    screening_seconds: float = field(compare=False)
    selected_family_representatives: tuple[str, ...] = ()
    family_ranking: tuple[BeliefPruningScore, ...] = ()
    expanded_ranking: tuple[BeliefPruningScore, ...] = ()
    guidance_plan: str | None = None
    strategic_reserved_choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class BeliefResponsePruning:
    legal_response_count: int
    strategic_response_count: int
    response_shortlist: tuple[str, ...]
    screening_branch_count: int
    screening_seconds: float = field(compare=False)


@dataclass(frozen=True)
class BeliefSearchResult:
    side: SideId
    chosen: BeliefChoiceScore
    ranking: tuple[BeliefChoiceScore, ...]
    world_count: int
    evaluated_choices: tuple[str, ...]
    branch_count: int
    response_screening_branch_count: int
    timing: BeliefSearchTiming = field(compare=False)


@dataclass(frozen=True)
class SelectiveContinuationLine:
    """One first-turn candidate extended from its current principal worst branch."""

    first_choice: str
    first_world: str
    first_world_weight: float
    first_response: str
    first_rng_seed: str | None
    first_turn_score: float
    next_phase: str
    next_pruning: BeliefPruningResult | None
    next_search: BeliefSearchResult | None
    leaf_score: float
    leaf_breakdown: ExactScoreBreakdown
    leaf_summary: dict[str, Any] = field(compare=False)
    protect_chain_slots: tuple[int, ...] = ()
    branch_count: int = 0


@dataclass(frozen=True)
class SelectiveContinuationResult:
    """Selective one-decision extension of the strongest one-ply candidates."""

    side: SideId
    original_choice: str
    chosen_choice: str
    ranking: tuple[SelectiveContinuationLine, ...]
    candidate_limit: int
    next_candidate_limit: int
    next_response_limit: int
    branch_count: int
    total_seconds: float = field(compare=False)


def _protect_chain_slots(state: dict[str, Any], side: SideId) -> tuple[int, ...]:
    """Return active slots whose exact state carries Showdown's Protect chain."""
    sides = state.get("sides")
    side_index = 0 if side == "p1" else 1
    if not isinstance(sides, list) or len(sides) <= side_index:
        return ()
    side_state = sides[side_index]
    if not isinstance(side_state, dict):
        return ()
    active = side_state.get("active")
    pokemon = side_state.get("pokemon")
    if not isinstance(active, list) or not isinstance(pokemon, list):
        return ()
    active_count = len(active)
    slots = []
    for mon in pokemon:
        if not isinstance(mon, dict):
            continue
        position = mon.get("position")
        volatiles = mon.get("volatiles")
        if (
            isinstance(position, int)
            and 0 <= position < active_count
            and isinstance(volatiles, dict)
            and "stall" in volatiles
        ):
            slots.append(position + 1)
    return tuple(sorted(slots))


def _side_legality_key(state: dict[str, Any], side: SideId) -> str:
    """Key legal-choice requests by the acting side's request-visible state.

    Showdown legal choices are determined by the acting side's active request. Opponent
    hidden sets are deliberately excluded so public-belief worlds that differ only in
    secret information can reuse the same enumeration.
    """
    sides = state.get("sides")
    side_index = 0 if side == "p1" else 1
    side_state = (
        sides[side_index]
        if isinstance(sides, list)
        and len(sides) > side_index
        and isinstance(sides[side_index], dict)
        else state.get(side)
    )
    if not isinstance(side_state, dict):
        return json.dumps(state, sort_keys=True, separators=(",", ":"))
    opponent_active: Any = None
    if isinstance(sides, list) and len(sides) == 2:
        opponent_state = sides[1 - side_index]
        if isinstance(opponent_state, dict):
            opponent_active = opponent_state.get("active")
    payload = {
        "requestState": state.get("requestState"),
        "turn": state.get("turn"),
        "side": side_state,
        "opponentActive": opponent_active,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _cached_legal_choices(
    worker: BeliefSearchWorker,
    state: dict[str, Any],
    side: SideId,
    cache: dict[tuple[SideId, str], list[str]],
) -> tuple[list[str], bool]:
    key = (side, _side_legality_key(state, side))
    cached = cache.get(key)
    if cached is not None:
        return cached, True
    choices = worker.legal_choices(state=state, side=side)
    cache[key] = choices
    return choices, False


def _common_legal_choices(
    worker: BeliefSearchWorker,
    worlds: tuple[ExactBeliefWorldState, ...],
    *,
    side: SideId,
    cache: dict[tuple[SideId, str], list[str]],
) -> tuple[list[str], int, int]:
    per_world = []
    hits = 0
    misses = 0
    for world in worlds:
        choices, hit = _cached_legal_choices(worker, world.state, side, cache)
        per_world.append(set(choices))
        hits += int(hit)
        misses += int(not hit)
    if not per_world:
        return [], hits, misses
    common = set.intersection(*per_world)
    return sorted(common), hits, misses


def _pruning_score(candidate: ExactChoiceScore, side: SideId) -> BeliefPruningScore:
    """Retain the representative failure behind a cheap screening score."""
    if not candidate.branches:
        return BeliefPruningScore(
            candidate.choice,
            candidate.worst_score,
            candidate.mean_score,
            candidate.best_score,
        )
    worst_branch = min(
        candidate.branches,
        key=lambda branch: (branch.score, branch.response),
    )
    worst_sample = min(
        worst_branch.samples,
        key=lambda sample: (sample.score, sample.rng_seed or ""),
    )
    breakdowns = [
        score_exact_summary_breakdown(sample.summary, side) for sample in worst_branch.samples
    ]
    score_breakdown = ExactScoreBreakdown(
        total=fmean(value.total for value in breakdowns),
        terminal=fmean(value.terminal for value in breakdowns),
        material=fmean(value.material for value in breakdowns),
        position=fmean(value.position for value in breakdowns),
        speed=fmean(value.speed for value in breakdowns),
    )
    return BeliefPruningScore(
        choice=candidate.choice,
        worst_score=candidate.worst_score,
        mean_score=candidate.mean_score,
        best_score=candidate.best_score,
        worst_response=worst_branch.response,
        score_breakdown=score_breakdown,
        worst_sample_score=worst_sample.score,
        worst_sample_summary=worst_sample.summary,
    )


def shortlist_belief_candidates(
    worker: BeliefSearchWorker,
    *,
    worlds: tuple[ExactBeliefWorldState, ...],
    side: SideId,
    candidate_limit: int = 8,
    reference_limit: int = 2,
    guidance: StrategicCandidateGuidance | None = None,
) -> BeliefPruningResult:
    """Autonomously shortlist public-belief-safe AI actions.

    Candidate legality is intersected across all belief worlds. Strategic families
    collapse target variants, then representatives are screened on a single belief
    world against a small diversified opponent reference set. This stage chooses only
    which of the AI's already-public legal actions deserve full cross-world search; it
    must never inspect the live opponent's hidden truth.
    """
    if not worlds:
        raise ValueError("worlds must not be empty")
    if candidate_limit <= 0:
        raise ValueError("candidate_limit must be positive")
    if reference_limit <= 0:
        raise ValueError("reference_limit must be positive")

    screening_started = perf_counter()
    cache: dict[tuple[SideId, str], list[str]] = {}
    common, _, _ = _common_legal_choices(worker, worlds, side=side, cache=cache)
    if not common:
        raise ValueError("no candidate choices are legal in every belief world")

    families = _strategy_families(common)
    representatives = [family.representative for family in families]
    opponent: SideId = "p2" if side == "p1" else "p1"
    reference_world = max(worlds, key=lambda world: (world.weight, world.label))
    responses = worker.legal_choices(state=reference_world.state, side=opponent)
    response_families = _strategy_families(responses)
    response_representatives = [family.representative for family in response_families]
    references = _reference_choices(response_representatives, reference_limit)

    family_screening = search_exact_turn(
        worker,
        state=reference_world.state,
        side=side,
        choices=representatives,
        opponent_responses=references,
        rng_seeds=SCREENING_RNG_SEEDS,
    )
    minimum_families = (
        2
        if guidance is not None and guidance.active and candidate_limit >= 2
        else 1
    )
    family_limit = min(
        len(families),
        max(minimum_families, candidate_limit - 2),
    )
    representative_shortlist = _diversified_top(
        family_screening.ranking,
        family_limit,
    )
    by_representative = {family.representative: family for family in families}

    # Soft strategy guidance may reserve one family for deeper screening, but can never
    # displace the tactically strongest screened family. Match against every member of a
    # family so a target-specific plan is not lost just because the family's generic
    # representative happened to point at the other slot.
    family_reserved: tuple[str, ...] = ()
    if guidance is not None and guidance.active and family_limit >= 2:
        guided_representatives = {
            family.representative
            for family in families
            if any(choice_matches_guidance(choice, guidance) for choice in family.choices)
        }
        if guided_representatives and not any(
            representative in guided_representatives
            for representative in representative_shortlist
        ):
            reserve = next(
                (
                    candidate.choice
                    for candidate in family_screening.ranking
                    if candidate.choice in guided_representatives
                ),
                None,
            )
            if reserve is not None:
                representative_shortlist[-1] = reserve
                family_reserved = (reserve,)

    # Family representatives decide which broad plans deserve more work. Every target
    # variant in those families is then scored before the final bound is applied.
    expanded = [
        choice
        for representative in representative_shortlist
        for choice in by_representative[representative].choices
    ]
    target_screening = search_exact_turn(
        worker,
        state=reference_world.state,
        side=side,
        choices=expanded,
        opponent_responses=references,
        rng_seeds=SCREENING_RNG_SEEDS,
    )
    shortlist = _diversified_top(target_screening.ranking, candidate_limit)
    shortlist_tuple, target_reserved = reserve_strategic_candidate(
        target_screening.ranking,
        shortlist,
        limit=candidate_limit,
        guidance=guidance,
    )
    reserved = tuple(dict.fromkeys((*family_reserved, *target_reserved)))

    return BeliefPruningResult(
        legal_choice_count=len(common),
        strategic_choice_count=len(families),
        candidate_shortlist=shortlist_tuple,
        screening_branch_count=(family_screening.branch_count + target_screening.branch_count),
        screening_seconds=perf_counter() - screening_started,
        selected_family_representatives=tuple(representative_shortlist),
        family_ranking=tuple(
            _pruning_score(candidate, side) for candidate in family_screening.ranking
        ),
        expanded_ranking=tuple(
            _pruning_score(candidate, side) for candidate in target_screening.ranking
        ),
        guidance_plan=guidance.plan_name if guidance is not None and guidance.active else None,
        strategic_reserved_choices=reserved,
    )


def _family_diverse_response_shortlist(
    ranking: tuple[ExactChoiceScore, ...],
    families,
    *,
    limit: int,
) -> tuple[str, ...]:
    """Prefer one strong target variant from each retained response family first."""
    family_by_choice = {
        choice: family_index
        for family_index, family in enumerate(families)
        for choice in family.choices
    }
    selected: list[str] = []
    seen_families: set[int] = set()

    for candidate in ranking:
        family_index = family_by_choice.get(candidate.choice)
        if family_index is None or family_index in seen_families:
            continue
        selected.append(candidate.choice)
        seen_families.add(family_index)
        if len(selected) >= limit:
            return tuple(selected)

    for candidate in ranking:
        if candidate.choice in selected:
            continue
        selected.append(candidate.choice)
        if len(selected) >= limit:
            break
    return tuple(selected)


def _candidate_specific_response_counters(
    worker: BeliefSearchWorker,
    *,
    state: dict[str, Any],
    opponent: SideId,
    families,
    candidate_references: list[str],
    limit: int,
) -> tuple[tuple[str, ...], int]:
    """Keep one strongest exact reply for each AI candidate while budget allows."""
    representatives = [family.representative for family in families]
    by_representative = {family.representative: family for family in families}
    selected: list[str] = []
    branch_count = 0

    for reference in candidate_references:
        family_screening = search_exact_turn(
            worker,
            state=state,
            side=opponent,
            choices=representatives,
            opponent_responses=[reference],
            rng_seeds=BELIEF_RESPONSE_SCREENING_RNG_SEEDS,
        )
        branch_count += family_screening.branch_count
        family = by_representative[family_screening.chosen.choice]

        target_screening = search_exact_turn(
            worker,
            state=state,
            side=opponent,
            choices=list(family.choices),
            opponent_responses=[reference],
            rng_seeds=BELIEF_RESPONSE_SCREENING_RNG_SEEDS,
        )
        branch_count += target_screening.branch_count
        counter = target_screening.chosen.choice
        if counter not in selected:
            selected.append(counter)
            if len(selected) >= limit:
                break

    return tuple(selected), branch_count


def shortlist_belief_responses(
    worker: BeliefSearchWorker,
    *,
    world: ExactBeliefWorldState,
    ai_side: SideId,
    candidate_references: list[str],
    response_limit: int = 8,
    legal_responses: list[str] | None = None,
    reference_limit: int = 1,
) -> BeliefResponsePruning:
    """Select dangerous replies while protecting a best counter to each AI candidate."""
    if response_limit <= 0:
        raise ValueError("response_limit must be positive")
    if not candidate_references:
        raise ValueError("candidate_references must not be empty")
    if reference_limit <= 0:
        raise ValueError("reference_limit must be positive")
    screening_started = perf_counter()
    opponent: SideId = "p2" if ai_side == "p1" else "p1"
    responses = (
        legal_responses
        if legal_responses is not None
        else worker.legal_choices(state=world.state, side=opponent)
    )
    if not responses:
        raise ValueError("opponent has no legal responses in belief world")
    families = _strategy_families(responses)
    representatives = [family.representative for family in families]

    protected, protected_branch_count = _candidate_specific_response_counters(
        worker,
        state=world.state,
        opponent=opponent,
        families=families,
        candidate_references=candidate_references,
        limit=response_limit,
    )
    if len(protected) >= response_limit:
        return BeliefResponsePruning(
            legal_response_count=len(responses),
            strategic_response_count=len(families),
            response_shortlist=protected,
            screening_branch_count=protected_branch_count,
            screening_seconds=perf_counter() - screening_started,
        )

    # The final matrix still uses every requested RNG future. This is only the cheap
    # per-world funnel, so one shared reference and seed are enough to rank broad plans
    # before their targeting variants receive a second screening pass.
    references = _reference_choices(candidate_references, reference_limit)
    family_screening = search_exact_turn(
        worker,
        state=world.state,
        side=opponent,
        choices=representatives,
        opponent_responses=references,
        rng_seeds=BELIEF_RESPONSE_SCREENING_RNG_SEEDS,
    )
    family_limit = min(
        len(families),
        1 if response_limit == 1 else max(2, response_limit // 2),
    )
    representative_shortlist = _diversified_top(
        family_screening.ranking,
        family_limit,
    )
    by_representative = {family.representative: family for family in families}
    expanded = [
        choice
        for representative in representative_shortlist
        for choice in by_representative[representative].choices
    ]
    target_screening = search_exact_turn(
        worker,
        state=world.state,
        side=opponent,
        choices=expanded,
        opponent_responses=references,
        rng_seeds=BELIEF_RESPONSE_SCREENING_RNG_SEEDS,
    )
    retained_families = [
        by_representative[representative]
        for representative in representative_shortlist
    ]
    fallback = _family_diverse_response_shortlist(
        target_screening.ranking,
        retained_families,
        limit=response_limit,
    )
    shortlist = list(protected)
    for response in fallback:
        if response in shortlist:
            continue
        shortlist.append(response)
        if len(shortlist) >= response_limit:
            break

    return BeliefResponsePruning(
        legal_response_count=len(responses),
        strategic_response_count=len(families),
        response_shortlist=tuple(shortlist),
        screening_branch_count=(
            protected_branch_count
            + family_screening.branch_count
            + target_screening.branch_count
        ),
        screening_seconds=perf_counter() - screening_started,
    )


def search_exact_belief_turn(
    worker: BeliefSearchWorker,
    *,
    worlds: tuple[ExactBeliefWorldState, ...],
    side: SideId,
    choices: list[str] | None = None,
    response_limit: int | None = None,
    autonomous_responses: bool = False,
    rng_seeds: tuple[str, ...] | None = None,
    response_shortlists: tuple[tuple[str, ...], ...] | None = None,
) -> BeliefSearchResult:
    """Rank actions across exact states generated only from public belief worlds.

    Each candidate is scored pessimistically against the worst legal opponent response
    inside each world. Those per-world minimax scores are then aggregated by public-prior
    weights. Ranking prioritizes worst-world resilience, then weighted expected score.
    """
    if not worlds:
        raise ValueError("worlds must not be empty")
    if response_limit is not None and response_limit <= 0:
        raise ValueError("response_limit must be positive")
    if rng_seeds is not None and not rng_seeds:
        raise ValueError("rng_seeds must not be empty")
    if response_shortlists is not None and len(response_shortlists) != len(worlds):
        raise ValueError("response_shortlists must align one-to-one with worlds")

    total_started = perf_counter()
    candidate_legal_started = perf_counter()
    samples: tuple[str | None, ...] = rng_seeds or (None,)
    opponent: SideId = "p2" if side == "p1" else "p1"

    legal_cache: dict[tuple[SideId, str], list[str]] = {}
    common_choices, legal_cache_hits, legal_cache_misses = _common_legal_choices(
        worker, worlds, side=side, cache=legal_cache
    )
    candidate_legal_seconds = perf_counter() - candidate_legal_started
    if choices is None:
        candidate_choices = common_choices
    else:
        common = set(common_choices)
        candidate_choices = [choice for choice in choices if choice in common]

    if not candidate_choices:
        raise ValueError("no candidate choices are legal in every belief world")

    total_weight = sum(world.weight for world in worlds)
    outcomes_by_choice: dict[str, list[BeliefWorldOutcome]] = {
        choice: [] for choice in candidate_choices
    }
    branch_count = 0
    response_screening_branch_count = 0
    response_legal_seconds = 0.0
    response_screening_seconds = 0.0
    branch_seconds = 0.0
    scoring_seconds = 0.0

    for world_index, world in enumerate(worlds):
        response_legal_started = perf_counter()
        responses, cache_hit = _cached_legal_choices(worker, world.state, opponent, legal_cache)
        legal_cache_hits += int(cache_hit)
        legal_cache_misses += int(not cache_hit)
        response_legal_seconds += perf_counter() - response_legal_started
        if response_shortlists is not None:
            legal_response_set = set(responses)
            responses = [
                response
                for response in response_shortlists[world_index]
                if response in legal_response_set
            ]
        elif autonomous_responses and response_limit is not None:
            pruning = shortlist_belief_responses(
                worker,
                world=world,
                ai_side=side,
                candidate_references=candidate_choices,
                response_limit=response_limit,
                legal_responses=responses,
            )
            responses = list(pruning.response_shortlist)
            response_screening_branch_count += pruning.screening_branch_count
            response_screening_seconds += pruning.screening_seconds
        elif response_limit is not None:
            responses = responses[:response_limit]
        if not responses:
            raise ValueError(f"opponent has no legal responses in belief world {world_index}")

        requested: list[dict[str, str]] = []
        metadata: list[tuple[str, str, str | None]] = []
        for choice in candidate_choices:
            for response in responses:
                for rng_seed in samples:
                    if side == "p1":
                        branch: dict[str, str] = {
                            "p1_choice": choice,
                            "p2_choice": response,
                        }
                    else:
                        branch = {
                            "p1_choice": response,
                            "p2_choice": choice,
                        }
                    if rng_seed is not None:
                        branch["rng_seed"] = rng_seed
                    requested.append(branch)
                    metadata.append((choice, response, rng_seed))

        branch_started = perf_counter()
        resolved = worker.branch_many(state=world.state, branches=requested)
        branch_seconds += perf_counter() - branch_started
        if len(resolved) != len(metadata):
            raise RuntimeError("unexpected number of belief-search branches")
        branch_count += len(requested)

        scoring_started = perf_counter()
        samples_by_choice: dict[
            str,
            dict[str, list[tuple[ExactScoreBreakdown, dict[str, Any], str | None]]],
        ] = {choice: {response: [] for response in responses} for choice in candidate_choices}
        for (choice, response, rng_seed), result in zip(metadata, resolved, strict=True):
            summary = result.get("summary")
            if not isinstance(summary, dict):
                raise RuntimeError("belief-search branch is missing a summary")
            breakdown = score_exact_summary_breakdown(summary, side)
            samples_by_choice[choice][response].append((breakdown, summary, rng_seed))

        for choice in candidate_choices:
            response_scores = {
                response: fmean(sample[0].total for sample in values)
                for response, values in samples_by_choice[choice].items()
            }
            worst_response = min(
                response_scores,
                key=lambda response: (response_scores[response], response),
            )
            worst_samples = samples_by_choice[choice][worst_response]
            worst_sample = min(
                worst_samples,
                key=lambda sample: (sample[0].total, sample[2] or ""),
            )
            component_means = ExactScoreBreakdown(
                total=fmean(sample[0].total for sample in worst_samples),
                terminal=fmean(sample[0].terminal for sample in worst_samples),
                material=fmean(sample[0].material for sample in worst_samples),
                position=fmean(sample[0].position for sample in worst_samples),
                speed=fmean(sample[0].speed for sample in worst_samples),
            )
            outcomes_by_choice[choice].append(
                BeliefWorldOutcome(
                    label=world.label or f"world-{world_index + 1}",
                    weight=world.weight,
                    worst_score=response_scores[worst_response],
                    mean_response_score=fmean(response_scores.values()),
                    worst_response=worst_response,
                    legal_response_count=len(responses),
                    score_breakdown=component_means,
                    worst_sample_score=worst_sample[0].total,
                    worst_sample_summary=worst_sample[1],
                    worst_sample_rng_seed=worst_sample[2],
                )
            )
        scoring_seconds += perf_counter() - scoring_started

    aggregation_started = perf_counter()
    scored: list[BeliefChoiceScore] = []
    for choice in candidate_choices:
        outcomes = tuple(outcomes_by_choice[choice])
        scored.append(
            BeliefChoiceScore(
                choice=choice,
                worst_world_score=min(outcome.worst_score for outcome in outcomes),
                weighted_score=sum(outcome.worst_score * outcome.weight for outcome in outcomes)
                / total_weight,
                mean_world_score=fmean(outcome.worst_score for outcome in outcomes),
                worlds=outcomes,
            )
        )

    ranking = tuple(
        sorted(
            scored,
            key=lambda candidate: (
                -candidate.worst_world_score,
                -candidate.weighted_score,
                -candidate.mean_world_score,
                candidate.choice,
            ),
        )
    )
    scoring_seconds += perf_counter() - aggregation_started
    total_seconds = perf_counter() - total_started
    return BeliefSearchResult(
        side=side,
        chosen=ranking[0],
        ranking=ranking,
        world_count=len(worlds),
        evaluated_choices=tuple(candidate_choices),
        branch_count=branch_count,
        response_screening_branch_count=response_screening_branch_count,
        timing=BeliefSearchTiming(
            total_seconds=total_seconds,
            candidate_legal_seconds=candidate_legal_seconds,
            response_legal_seconds=response_legal_seconds,
            response_screening_seconds=response_screening_seconds,
            branch_seconds=branch_seconds,
            scoring_seconds=scoring_seconds,
            legal_cache_hits=legal_cache_hits,
            legal_cache_misses=legal_cache_misses,
        ),
    )


def search_selective_continuation(
    worker: BeliefSearchWorker,
    *,
    worlds: tuple[ExactBeliefWorldState, ...],
    first_turn: BeliefSearchResult,
    candidate_limit: int = 3,
    next_candidate_limit: int = 4,
    next_response_limit: int = 4,
    rng_seeds: tuple[str, ...] | None = None,
) -> SelectiveContinuationResult:
    """Extend the strongest first-turn choices through one more decision.

    This is a principal-variation probe, not exhaustive two-ply minimax. For each top
    first-turn candidate, it restores that candidate's current worst sampled
    world/response/RNG result and runs a fresh bounded adversarial search from the exact
    resulting state. This exposes next-turn liabilities such as consecutive Protect,
    forced switches, and an exposed active Pokemon without multiplying the full belief
    matrix by another complete search tree.
    """
    if not worlds:
        raise ValueError("worlds must not be empty")
    if candidate_limit <= 0:
        raise ValueError("candidate_limit must be positive")
    if next_candidate_limit <= 0:
        raise ValueError("next_candidate_limit must be positive")
    if next_response_limit <= 0:
        raise ValueError("next_response_limit must be positive")
    if rng_seeds is not None and not rng_seeds:
        raise ValueError("rng_seeds must not be empty")

    started = perf_counter()
    continuation_rng = rng_seeds or SCREENING_RNG_SEEDS
    labels: dict[str, ExactBeliefWorldState] = {}
    for index, world in enumerate(worlds):
        label = world.label or f"world-{index + 1}"
        if label in labels:
            raise ValueError(f"duplicate belief-world label: {label}")
        labels[label] = world

    lines: list[SelectiveContinuationLine] = []
    total_branches = 0
    for candidate in first_turn.ranking[:candidate_limit]:
        first_outcome = min(
            candidate.worlds,
            key=lambda outcome: (outcome.worst_score, outcome.label),
        )
        source_world = labels.get(first_outcome.label)
        if source_world is None:
            raise ValueError(
                f"first-turn outcome references unknown belief world {first_outcome.label!r}"
            )

        if first_turn.side == "p1":
            first_branch: dict[str, Any] = {
                "p1_choice": candidate.choice,
                "p2_choice": first_outcome.worst_response,
                "include_state": True,
            }
        else:
            first_branch = {
                "p1_choice": first_outcome.worst_response,
                "p2_choice": candidate.choice,
                "include_state": True,
            }
        if first_outcome.worst_sample_rng_seed is not None:
            first_branch["rng_seed"] = first_outcome.worst_sample_rng_seed

        resolved = worker.branch_many(state=source_world.state, branches=[first_branch])
        total_branches += 1
        if len(resolved) != 1:
            raise RuntimeError("unexpected number of continuation source branches")
        first_summary = resolved[0].get("summary")
        next_state = resolved[0].get("state")
        if not isinstance(first_summary, dict) or not isinstance(next_state, dict):
            raise RuntimeError("continuation source branch is missing summary or exact state")

        first_score = (
            first_outcome.worst_sample_score
            if first_outcome.worst_sample_score is not None
            else score_exact_summary_breakdown(first_summary, first_turn.side).total
        )
        next_phase = str(next_state.get("requestState", first_summary.get("requestState", "")))
        protect_chain_slots = _protect_chain_slots(next_state, first_turn.side)
        if first_summary.get("ended"):
            breakdown = score_exact_summary_breakdown(first_summary, first_turn.side)
            lines.append(
                SelectiveContinuationLine(
                    first_choice=candidate.choice,
                    first_world=first_outcome.label,
                    first_world_weight=first_outcome.weight,
                    first_response=first_outcome.worst_response,
                    first_rng_seed=first_outcome.worst_sample_rng_seed,
                    first_turn_score=first_score,
                    next_phase="ended",
                    next_pruning=None,
                    next_search=None,
                    leaf_score=breakdown.total,
                    leaf_breakdown=breakdown,
                    leaf_summary=first_summary,
                    protect_chain_slots=protect_chain_slots,
                    branch_count=1,
                )
            )
            continue

        continuation_world = ExactBeliefWorldState(
            state=next_state,
            weight=1.0,
            label=f"{first_outcome.label}-continuation",
        )
        pruning = shortlist_belief_candidates(
            worker,
            worlds=(continuation_world,),
            side=first_turn.side,
            candidate_limit=next_candidate_limit,
            reference_limit=1,
        )
        continuation = search_exact_belief_turn(
            worker,
            worlds=(continuation_world,),
            side=first_turn.side,
            choices=list(pruning.candidate_shortlist),
            response_limit=next_response_limit,
            autonomous_responses=True,
            rng_seeds=continuation_rng,
        )
        next_worst = min(
            continuation.chosen.worlds,
            key=lambda outcome: (outcome.worst_score, outcome.label),
        )
        leaf_summary = next_worst.worst_sample_summary
        if leaf_summary is None:
            raise RuntimeError("continuation search is missing its worst leaf summary")
        leaf_breakdown = next_worst.score_breakdown
        if leaf_breakdown is None:
            leaf_breakdown = score_exact_summary_breakdown(leaf_summary, first_turn.side)
        line_branches = (
            1
            + pruning.screening_branch_count
            + continuation.response_screening_branch_count
            + continuation.branch_count
        )
        total_branches += line_branches - 1
        lines.append(
            SelectiveContinuationLine(
                first_choice=candidate.choice,
                first_world=first_outcome.label,
                first_world_weight=first_outcome.weight,
                first_response=first_outcome.worst_response,
                first_rng_seed=first_outcome.worst_sample_rng_seed,
                first_turn_score=first_score,
                next_phase=next_phase,
                next_pruning=pruning,
                next_search=continuation,
                leaf_score=continuation.chosen.worst_world_score,
                leaf_breakdown=leaf_breakdown,
                leaf_summary=leaf_summary,
                protect_chain_slots=protect_chain_slots,
                branch_count=line_branches,
            )
        )

    ranking = tuple(
        sorted(
            lines,
            key=lambda line: (
                -line.leaf_score,
                -line.first_turn_score,
                line.first_choice,
            ),
        )
    )
    if not ranking:
        raise ValueError("first-turn result has no candidates to extend")
    return SelectiveContinuationResult(
        side=first_turn.side,
        original_choice=first_turn.chosen.choice,
        chosen_choice=ranking[0].first_choice,
        ranking=ranking,
        candidate_limit=min(candidate_limit, len(first_turn.ranking)),
        next_candidate_limit=next_candidate_limit,
        next_response_limit=next_response_limit,
        branch_count=total_branches,
        total_seconds=perf_counter() - started,
    )
