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
    candidate_shortlist: tuple[str, ...]
    response_shortlist: tuple[str, ...]
    result: ExactSearchResult


def _strategy_signature(choice: str) -> tuple[tuple[str, ...], ...]:
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
        [choice for choice in choices if "switch " in choice],
        [
            choice
            for choice in choices
            if any(f"move {term}" in choice for term in support_terms)
        ],
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
    reference_limit: int = 3,
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
    if reference_limit <= 0:
        raise ValueError("reference limit must be positive")

    opponent: SideId = "p2" if side == "p1" else "p1"
    choices = worker.legal_choices(state=state, side=side)
    responses = worker.legal_choices(state=state, side=opponent)
    if not choices:
        raise ValueError(f"{side} has no legal choices")
    if not responses:
        raise ValueError(f"{opponent} has no legal responses")

    response_references = _reference_choices(responses, reference_limit)
    choice_pruning = search_exact_turn(
        worker,
        state=state,
        side=side,
        choices=choices,
        opponent_responses=response_references,
    )
    candidate_shortlist = _diversified_top(
        choice_pruning.ranking,
        candidate_limit,
    )

    choice_references = _reference_choices(choices, reference_limit)
    response_pruning = search_exact_turn(
        worker,
        state=state,
        side=opponent,
        choices=responses,
        opponent_responses=choice_references,
    )
    response_shortlist = _diversified_top(
        response_pruning.ranking,
        response_limit,
    )

    result = search_exact_turn(
        worker,
        state=state,
        side=side,
        choices=candidate_shortlist,
        opponent_responses=response_shortlist,
    )
    return ExactRecommendation(
        side=side,
        mode="perfect_information",
        legal_choice_count=len(choices),
        legal_response_count=len(responses),
        candidate_shortlist=tuple(candidate_shortlist),
        response_shortlist=tuple(response_shortlist),
        result=result,
    )
