"""Bounded exact recommendations for analysis and post-game review."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from champions_practice.exact_search import (
    ExactChoiceScore,
    ExactSearchResult,
    SideId,
    search_exact_turn,
)

StrategySignature = tuple[tuple[str, ...], ...]

SCREENING_RNG_SEEDS = (
    "sodium,1111111111111111111111111111111111111111111111111111111111111111",
    "sodium,9999999999999999999999999999999999999999999999999999999999999999",
)
FINAL_RNG_SEEDS = SCREENING_RNG_SEEDS + (
    "sodium,eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
)


class RecommendationWorker(Protocol):
    def legal_choices(self, *, state: dict[str, Any], side: str) -> list[str]: ...

    def branch_many(
        self,
        *,
        state: dict[str, Any],
        branches: list[dict[str, str]],
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class ExactRecommendation:
    side: SideId
    mode: str
    legal_choice_count: int
    legal_response_count: int
    strategic_choice_count: int
    strategic_response_count: int
    expanded_candidate_count: int
    expanded_response_count: int
    candidate_shortlist: tuple[str, ...]
    response_shortlist: tuple[str, ...]
    pruning_branch_count: int
    final_branch_count: int
    rng_sample_count: int
    result: ExactSearchResult


@dataclass(frozen=True)
class StrategyFamily:
    signature: StrategySignature
    representative: str
    choices: tuple[str, ...]


def _strategy_signature(choice: str) -> StrategySignature:
    """Group target variants while preserving the strategic action pair."""
    signature: list[tuple[str, ...]] = []
    for command in choice.split(","):
        tokens = command.strip().split()
        if not tokens:
            signature.append(("wait",))
        elif tokens[0] == "move":
            event = next(
                (
                    token
                    for token in tokens[2:]
                    if token in {"mega", "megax", "megay", "ultra"}
                ),
                "base",
            )
            signature.append(("move", tokens[1], event))
        elif tokens[0] == "switch":
            signature.append(("switch", tokens[1]))
        else:
            signature.append((tokens[0],))
    return tuple(signature)


def _target_profile(choice: str) -> tuple[int, int, int]:
    """Prefer legal enemy targets and split double-target attacks."""
    targets: list[int] = []
    for command in choice.split(","):
        tokens = command.strip().split()
        if not tokens or tokens[0] != "move":
            continue
        for token in tokens[2:]:
            if token.removeprefix("+").removeprefix("-").isdigit():
                targets.append(int(token))
                break
    enemy_targets = [target for target in targets if target > 0]
    ally_targets = [target for target in targets if target < 0]
    return (
        len(enemy_targets),
        len(set(enemy_targets)),
        -len(ally_targets),
    )


def _strategy_families(choices: list[str]) -> list[StrategyFamily]:
    grouped: dict[StrategySignature, list[str]] = {}
    for choice in choices:
        grouped.setdefault(_strategy_signature(choice), []).append(choice)

    return [
        StrategyFamily(
            signature=signature,
            representative=max(members, key=lambda choice: (_target_profile(choice), choice)),
            choices=tuple(members),
        )
        for signature, members in grouped.items()
    ]


def _reference_choices(choices: list[str], limit: int) -> list[str]:
    """Pick varied reference lines for the inexpensive pruning pass."""
    if limit <= 0:
        raise ValueError("reference limit must be positive")
    if len(choices) <= limit:
        return choices.copy()

    support_terms = {
        "followme",
        "imprison",
        "protect",
        "trickroom",
        "wideguard",
    }
    buckets = [
        [
            choice
            for choice in choices
            if "switch " not in choice
            and not any(f"move {term}" in choice for term in support_terms)
        ],
        [
            choice
            for choice in choices
            if any(f"move {term}" in choice for term in support_terms)
        ],
        [choice for choice in choices if "switch " in choice],
        [choice for choice in choices if " mega" in choice],
        [choice for choice in choices if choice],
    ]

    selected: list[str] = []
    seen_signatures: set[tuple[tuple[str, ...], ...]] = set()
    while len(selected) < limit:
        added = False
        for bucket in buckets:
            for choice in bucket:
                signature = _strategy_signature(choice)
                if choice in selected or signature in seen_signatures:
                    continue
                selected.append(choice)
                seen_signatures.add(signature)
                added = True
                break
            if len(selected) >= limit:
                break
        if not added:
            break

    for choice in choices:
        if len(selected) >= limit:
            break
        if choice not in selected:
            selected.append(choice)
    return selected


def _top_families(
    ranking: tuple[ExactChoiceScore, ...],
    families: list[StrategyFamily],
    *,
    family_limit: int,
    expanded_limit: int,
) -> list[StrategyFamily]:
    by_representative = {family.representative: family for family in families}
    selected: list[StrategyFamily] = []
    expanded_count = 0
    for candidate in ranking:
        family = by_representative[candidate.choice]
        selected.append(family)
        expanded_count += len(family.choices)
        if len(selected) >= family_limit and expanded_count >= expanded_limit:
            break
    return selected


def _expand_families(families: list[StrategyFamily]) -> list[str]:
    return [choice for family in families for choice in family.choices]


def _diversified_top(
    ranking: tuple[ExactChoiceScore, ...],
    limit: int,
) -> list[str]:
    """Keep the strongest half, then add distinct strategic action pairs."""
    if limit <= 0:
        raise ValueError("shortlist limit must be positive")
    if len(ranking) <= limit:
        return [candidate.choice for candidate in ranking]

    strong_count = max(1, limit // 2)
    selected = [candidate.choice for candidate in ranking[:strong_count]]
    seen_signatures = {_strategy_signature(choice) for choice in selected}

    for candidate in ranking[strong_count:]:
        if len(selected) >= limit:
            break
        signature = _strategy_signature(candidate.choice)
        if signature in seen_signatures:
            continue
        selected.append(candidate.choice)
        seen_signatures.add(signature)

    for candidate in ranking:
        if len(selected) >= limit:
            break
        if candidate.choice not in selected:
            selected.append(candidate.choice)
    return selected


def recommend_exact_turn_perfect_information(
    worker: RecommendationWorker,
    *,
    state: dict[str, Any],
    side: SideId,
    candidate_limit: int = 12,
    response_limit: int = 12,
    family_limit: int = 5,
    reference_limit: int = 1,
) -> ExactRecommendation:
    """Return a bounded exact recommendation using the snapshot's full truth.

    This function is intentionally named as a warning: it enumerates both sides from the
    exact simulator state. It is suitable for plumbing tests, open-team-sheet analysis,
    and post-game review. Do not use it for a live closed-team-sheet opponent until the
    opposing choices come from a public-information belief model.
    """
    if candidate_limit <= 0:
        raise ValueError("candidate limit must be positive")
    if response_limit <= 0:
        raise ValueError("response limit must be positive")
    if family_limit <= 0:
        raise ValueError("family limit must be positive")
    if reference_limit <= 0:
        raise ValueError("reference limit must be positive")

    opponent: SideId = "p2" if side == "p1" else "p1"
    choices = worker.legal_choices(state=state, side=side)
    responses = worker.legal_choices(state=state, side=opponent)
    if not choices:
        raise ValueError(f"{side} has no legal choices")
    if not responses:
        raise ValueError(f"{opponent} has no legal responses")

    choice_families = _strategy_families(choices)
    response_families = _strategy_families(responses)
    choice_representatives = [family.representative for family in choice_families]
    response_representatives = [
        family.representative for family in response_families
    ]

    response_references = _reference_choices(
        response_representatives, reference_limit
    )
    choice_family_pruning = search_exact_turn(
        worker,
        state=state,
        side=side,
        choices=choice_representatives,
        opponent_responses=response_references,
        rng_seeds=SCREENING_RNG_SEEDS,
    )
    selected_choice_families = _top_families(
        choice_family_pruning.ranking,
        choice_families,
        family_limit=family_limit,
        expanded_limit=candidate_limit,
    )

    choice_references = _reference_choices(choice_representatives, reference_limit)
    response_family_pruning = search_exact_turn(
        worker,
        state=state,
        side=opponent,
        choices=response_representatives,
        opponent_responses=choice_references,
        rng_seeds=SCREENING_RNG_SEEDS,
    )
    selected_response_families = _top_families(
        response_family_pruning.ranking,
        response_families,
        family_limit=family_limit,
        expanded_limit=response_limit,
    )

    expanded_candidates = _expand_families(selected_choice_families)
    expanded_responses = _expand_families(selected_response_families)
    choice_target_pruning = search_exact_turn(
        worker,
        state=state,
        side=side,
        choices=expanded_candidates,
        opponent_responses=[response_family_pruning.chosen.choice],
        rng_seeds=SCREENING_RNG_SEEDS,
    )
    candidate_shortlist = _diversified_top(
        choice_target_pruning.ranking,
        candidate_limit,
    )
    response_target_pruning = search_exact_turn(
        worker,
        state=state,
        side=opponent,
        choices=expanded_responses,
        opponent_responses=[choice_family_pruning.chosen.choice],
        rng_seeds=SCREENING_RNG_SEEDS,
    )
    response_shortlist = _diversified_top(
        response_target_pruning.ranking,
        response_limit,
    )

    result = search_exact_turn(
        worker,
        state=state,
        side=side,
        choices=candidate_shortlist,
        opponent_responses=response_shortlist,
        rng_seeds=FINAL_RNG_SEEDS,
    )
    pruning_branch_count = sum(
        pruning.branch_count
        for pruning in (
            choice_family_pruning,
            response_family_pruning,
            choice_target_pruning,
            response_target_pruning,
        )
    )
    return ExactRecommendation(
        side=side,
        mode="perfect_information",
        legal_choice_count=len(choices),
        legal_response_count=len(responses),
        strategic_choice_count=len(choice_families),
        strategic_response_count=len(response_families),
        expanded_candidate_count=len(expanded_candidates),
        expanded_response_count=len(expanded_responses),
        candidate_shortlist=tuple(candidate_shortlist),
        response_shortlist=tuple(response_shortlist),
        pruning_branch_count=pruning_branch_count,
        final_branch_count=result.branch_count,
        rng_sample_count=len(FINAL_RNG_SEEDS),
        result=result,
    )
