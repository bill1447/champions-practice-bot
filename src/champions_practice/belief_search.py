"""Exact one-ply search across multiple public-belief worlds."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from statistics import fmean
from time import perf_counter
from typing import Any, Protocol

from champions_practice.exact_search import SideId, score_exact_summary


class BeliefSearchWorker(Protocol):
    def legal_choices(self, *, state: dict[str, Any], side: str) -> list[str]: ...

    def branch_many(
        self,
        *,
        state: dict[str, Any],
        branches: list[dict[str, str]],
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
    branch_seconds: float
    scoring_seconds: float
    legal_cache_hits: int
    legal_cache_misses: int


@dataclass(frozen=True)
class BeliefSearchResult:
    side: SideId
    chosen: BeliefChoiceScore
    ranking: tuple[BeliefChoiceScore, ...]
    world_count: int
    evaluated_choices: tuple[str, ...]
    branch_count: int
    timing: BeliefSearchTiming = field(compare=False)


def _side_legality_key(state: dict[str, Any], side: SideId) -> str:
    """Key legal-choice requests by the acting side's request-visible state.

    Showdown legal choices are determined by the acting side's active request. Opponent
    hidden sets are deliberately excluded so public-belief worlds that differ only in
    secret information can reuse the same enumeration.
    """
    side_state = state.get(side)
    if not isinstance(side_state, dict):
        return json.dumps(state, sort_keys=True, separators=(",", ":"))
    payload = {
        "requestState": state.get("requestState"),
        "turn": state.get("turn"),
        "side": side_state,
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


def search_exact_belief_turn(
    worker: BeliefSearchWorker,
    *,
    worlds: tuple[ExactBeliefWorldState, ...],
    side: SideId,
    choices: list[str] | None = None,
    response_limit: int | None = None,
    rng_seeds: tuple[str, ...] | None = None,
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
    response_legal_seconds = 0.0
    branch_seconds = 0.0
    scoring_seconds = 0.0

    for world_index, world in enumerate(worlds):
        response_legal_started = perf_counter()
        responses, cache_hit = _cached_legal_choices(
            worker, world.state, opponent, legal_cache
        )
        legal_cache_hits += int(cache_hit)
        legal_cache_misses += int(not cache_hit)
        response_legal_seconds += perf_counter() - response_legal_started
        if response_limit is not None:
            responses = responses[:response_limit]
        if not responses:
            raise ValueError(f"opponent has no legal responses in belief world {world_index}")

        requested: list[dict[str, str]] = []
        metadata: list[tuple[str, str]] = []
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
                    metadata.append((choice, response))

        branch_started = perf_counter()
        resolved = worker.branch_many(state=world.state, branches=requested)
        branch_seconds += perf_counter() - branch_started
        if len(resolved) != len(metadata):
            raise RuntimeError("unexpected number of belief-search branches")
        branch_count += len(requested)

        scoring_started = perf_counter()
        scores: dict[str, dict[str, list[float]]] = {
            choice: {response: [] for response in responses}
            for choice in candidate_choices
        }
        for (choice, response), result in zip(metadata, resolved, strict=True):
            summary = result.get("summary")
            if not isinstance(summary, dict):
                raise RuntimeError("belief-search branch is missing a summary")
            scores[choice][response].append(score_exact_summary(summary, side))

        for choice in candidate_choices:
            response_scores = {
                response: fmean(values)
                for response, values in scores[choice].items()
            }
            worst_response = min(
                response_scores,
                key=lambda response: (response_scores[response], response),
            )
            outcomes_by_choice[choice].append(
                BeliefWorldOutcome(
                    label=world.label or f"world-{world_index + 1}",
                    weight=world.weight,
                    worst_score=response_scores[worst_response],
                    mean_response_score=fmean(response_scores.values()),
                    worst_response=worst_response,
                    legal_response_count=len(responses),
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
                weighted_score=sum(
                    outcome.worst_score * outcome.weight for outcome in outcomes
                )
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
        timing=BeliefSearchTiming(
            total_seconds=total_seconds,
            candidate_legal_seconds=candidate_legal_seconds,
            response_legal_seconds=response_legal_seconds,
            branch_seconds=branch_seconds,
            scoring_seconds=scoring_seconds,
            legal_cache_hits=legal_cache_hits,
            legal_cache_misses=legal_cache_misses,
        ),
    )
