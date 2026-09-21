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
class ExactRngSample:
    rng_seed: str | None
    score: float
    summary: dict[str, Any]


@dataclass(frozen=True)
class ExactBranchScore:
    response: str
    score: float
    summary: dict[str, Any]
    samples: tuple[ExactRngSample, ...]


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
    branch_count: int


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


_BOOST_WEIGHTS = {
    "atk": 8.0,
    "def": 6.0,
    "spa": 8.0,
    "spd": 6.0,
    "spe": 10.0,
    "accuracy": 4.0,
    "evasion": 4.0,
}
_SIDE_CONDITION_VALUES = {
    "auroraveil": 35.0,
    "lightscreen": 20.0,
    "reflect": 20.0,
    "safeguard": 8.0,
    "mist": 8.0,
    "tailwind": 30.0,
    "stealthrock": -20.0,
    "stickyweb": -25.0,
    "spikes": -12.0,
    "toxicspikes": -12.0,
}
_TERRAIN_MOVE_TYPE = {
    "electricterrain": "electric",
    "grassyterrain": "grass",
    "psychicterrain": "psychic",
}
_WEATHER_MOVE_TYPE = {
    "raindance": "water",
    "sunnyday": "fire",
}


def _active_position_value(
    side: dict[str, Any],
    *,
    terrain: str | None,
    weather: str | None,
) -> float:
    """Give modest credit to immediately useful board resources."""
    value = sum(
        _SIDE_CONDITION_VALUES.get(condition, 0.0)
        for condition in side.get("sideConditions", [])
    )
    for pokemon in side.get("active", []):
        if not pokemon or pokemon.get("fainted"):
            continue
        max_hp = max(1, int(pokemon.get("maxhp", 1)))
        hp = max(0, int(pokemon.get("hp", 0)))
        value += 15.0 * hp / max_hp
        value += sum(
            _BOOST_WEIGHTS.get(stat, 0.0) * int(stage)
            for stat, stage in pokemon.get("boosts", {}).items()
        )

        move_types = set(pokemon.get("moveTypes", []))
        if pokemon.get("grounded"):
            terrain_type = _TERRAIN_MOVE_TYPE.get(terrain or "")
            if terrain_type and terrain_type in move_types:
                value += 18.0
            elif terrain == "mistyterrain":
                value += 5.0

        weather_type = _WEATHER_MOVE_TYPE.get(weather or "")
        if weather_type and weather_type in move_types:
            value += 12.0
    return value


def _pseudo_weather_ids(field: dict[str, Any]) -> set[str]:
    values = field.get("pseudoWeather", [])
    return {
        value if isinstance(value, str) else str(value.get("id", ""))
        for value in values
    }


def _average_active_speed(side: dict[str, Any]) -> float | None:
    speeds = [
        float(pokemon["speed"])
        for pokemon in side.get("active", [])
        if pokemon and not pokemon.get("fainted") and "speed" in pokemon
    ]
    return fmean(speeds) if speeds else None


def _speed_position_value(summary: dict[str, Any], side: SideId) -> float:
    opponent: SideId = "p2" if side == "p1" else "p1"
    own_speed = _average_active_speed(summary[side])
    opponent_speed = _average_active_speed(summary[opponent])
    if own_speed is None or opponent_speed is None:
        return 0.0

    delta = own_speed - opponent_speed
    if "trickroom" in _pseudo_weather_ids(summary.get("field", {})):
        delta = -delta
    return max(-20.0, min(20.0, delta / 5.0))


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

    field = summary.get("field", {})
    terrain = field.get("terrain")
    weather = field.get("weather")
    material = _side_material(summary[side]) - _side_material(summary[opponent])
    position = _active_position_value(
        summary[side], terrain=terrain, weather=weather
    ) - _active_position_value(
        summary[opponent], terrain=terrain, weather=weather
    )
    return material + position + _speed_position_value(summary, side)


def search_exact_turn(
    worker: BranchWorker,
    *,
    state: dict[str, Any],
    side: SideId,
    choices: list[str],
    opponent_responses: list[str],
    rng_seeds: tuple[str, ...] | None = None,
) -> ExactSearchResult:
    """Rank choices by their worst exact result across supplied opponent responses.

    This is deliberately one ply. A caller can pass a heuristic shortlist rather than
    exploding every legal doubles action against every response. When RNG seeds are
    supplied, each response is scored by its mean across those futures before minimax.
    Ties are broken by mean outcome, then best outcome, then the stable choice string.
    """
    if not choices:
        raise ValueError("choices must not be empty")
    if not opponent_responses:
        raise ValueError("opponent_responses must not be empty")
    if rng_seeds is not None and not rng_seeds:
        raise ValueError("rng_seeds must not be empty")

    samples: tuple[str | None, ...] = rng_seeds or (None,)

    requested: list[dict[str, str]] = []
    pairs: list[tuple[str, str, str | None]] = []
    for choice in choices:
        for response in opponent_responses:
            for rng_seed in samples:
                if side == "p1":
                    branch = {"p1_choice": choice, "p2_choice": response}
                else:
                    branch = {"p1_choice": response, "p2_choice": choice}
                if rng_seed is not None:
                    branch["rng_seed"] = rng_seed
                requested.append(branch)
                pairs.append((choice, response, rng_seed))

    resolved = worker.branch_many(state=state, branches=requested)
    if len(resolved) != len(pairs):
        raise RuntimeError(
            "Showdown worker returned an unexpected number of exact branches"
        )

    grouped: dict[str, dict[str, list[ExactRngSample]]] = {
        choice: {response: [] for response in opponent_responses}
        for choice in choices
    }
    for (choice, response, rng_seed), result in zip(pairs, resolved, strict=True):
        summary = result.get("summary")
        if not isinstance(summary, dict):
            raise RuntimeError("Showdown worker returned a branch without a summary")
        grouped[choice][response].append(
            ExactRngSample(
                rng_seed=rng_seed,
                score=score_exact_summary(summary, side),
                summary=summary,
            )
        )

    scored: list[ExactChoiceScore] = []
    for choice in choices:
        branches = tuple(
            ExactBranchScore(
                response=response,
                score=fmean(sample.score for sample in grouped[choice][response]),
                summary=grouped[choice][response][0].summary,
                samples=tuple(grouped[choice][response]),
            )
            for response in opponent_responses
        )
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
    return ExactSearchResult(
        side=side,
        chosen=ranking[0],
        ranking=ranking,
        branch_count=len(requested),
    )
