"""One-ply action search backed by exact Pokemon Showdown forks."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean
from typing import Any, Literal, Protocol

SideId = Literal["p1", "p2"]


class BranchWorker(Protocol):
    def branch_many(
        self,
        *,
        state: dict[str, Any],
        branches: list[dict[str, str]],
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class ExactBranchScore:
    response: str
    score: float
    summary: dict[str, Any]


@dataclass(frozen=True)
class ExactChoiceScore:
    choice: str
    worst_score: float
    mean_score: float
    best_score: float
    branches: tuple[ExactBranchScore, ...]


@dataclass(frozen=True)
class ExactSearchResult:
    side: SideId
    chosen: ExactChoiceScore
    ranking: tuple[ExactChoiceScore, ...]


def _side_material(side: dict[str, Any]) -> float:
    """Value living pieces first, then remaining HP and status."""
    value = 0.0
    for pokemon in side["pokemon"]:
        max_hp = max(1, int(pokemon["maxhp"]))
        hp = max(0, int(pokemon["hp"]))
        fainted = bool(pokemon["fainted"]) or hp == 0
        if fainted:
            continue

        # The large living-piece bonus makes a needless sacrifice much more expensive
        # than modest chip damage. HP separates positions with equal survivors.
        value += 1000.0
        value += 100.0 * hp / max_hp
        if pokemon.get("status"):
            value -= 20.0
    return value


def score_exact_summary(summary: dict[str, Any], side: SideId) -> float:
    """Score an exact resolved board from one side's perspective."""
    opponent: SideId = "p2" if side == "p1" else "p1"

    if summary.get("ended"):
        winner = summary.get("winner")
        side_name = summary[side].get("name")
        opponent_name = summary[opponent].get("name")
        if winner and winner == side_name:
            return 1_000_000.0
        if winner and winner == opponent_name:
            return -1_000_000.0

    return _side_material(summary[side]) - _side_material(summary[opponent])


def search_exact_turn(
    worker: BranchWorker,
    *,
    state: dict[str, Any],
    side: SideId,
    choices: list[str],
    opponent_responses: list[str],
) -> ExactSearchResult:
    """Rank choices by their worst exact result across supplied opponent responses.

    This is deliberately one ply. A caller can pass a heuristic shortlist rather than
    exploding every legal doubles action against every response. Ties on the worst case
    are broken by mean outcome, then best outcome, then the stable choice string.
    """
    if not choices:
        raise ValueError("choices must not be empty")
    if not opponent_responses:
        raise ValueError("opponent_responses must not be empty")

    requested: list[dict[str, str]] = []
    pairs: list[tuple[str, str]] = []
    for choice in choices:
        for response in opponent_responses:
            if side == "p1":
                branch = {"p1_choice": choice, "p2_choice": response}
            else:
                branch = {"p1_choice": response, "p2_choice": choice}
            requested.append(branch)
            pairs.append((choice, response))

    resolved = worker.branch_many(state=state, branches=requested)
    if len(resolved) != len(pairs):
        raise RuntimeError(
            "Showdown worker returned an unexpected number of exact branches"
        )

    grouped: dict[str, list[ExactBranchScore]] = {choice: [] for choice in choices}
    for (choice, response), result in zip(pairs, resolved, strict=True):
        summary = result.get("summary")
        if not isinstance(summary, dict):
            raise RuntimeError("Showdown worker returned a branch without a summary")
        grouped[choice].append(
            ExactBranchScore(
                response=response,
                score=score_exact_summary(summary, side),
                summary=summary,
            )
        )

    scored: list[ExactChoiceScore] = []
    for choice in choices:
        branches = tuple(grouped[choice])
        scores = [branch.score for branch in branches]
        scored.append(
            ExactChoiceScore(
                choice=choice,
                worst_score=min(scores),
                mean_score=fmean(scores),
                best_score=max(scores),
                branches=branches,
            )
        )

    ranking = tuple(
        sorted(
            scored,
            key=lambda candidate: (
                -candidate.worst_score,
                -candidate.mean_score,
                -candidate.best_score,
                candidate.choice,
            ),
        )
    )
    return ExactSearchResult(side=side, chosen=ranking[0], ranking=ranking)
