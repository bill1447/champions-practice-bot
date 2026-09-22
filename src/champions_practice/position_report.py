"""Human-readable public battle positions and bounded-search evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from champions_practice.belief_search import BeliefPruningResult, BeliefSearchResult


_LABELS = {
    "electricterrain": "Electric Terrain",
    "grassyterrain": "Grassy Terrain",
    "mistyterrain": "Misty Terrain",
    "psychicterrain": "Psychic Terrain",
    "raindance": "Rain",
    "sandstorm": "Sandstorm",
    "sunnyday": "Sun",
    "snow": "Snow",
    "trickroom": "Trick Room",
    "tailwind": "Tailwind",
    "lightscreen": "Light Screen",
    "reflect": "Reflect",
    "auroraveil": "Aurora Veil",
    "stealthrock": "Stealth Rock",
    "wideguard": "Wide Guard",
    "safeguard": "Safeguard",
    "mist": "Mist",
    "brn": "burn",
    "frz": "frozen",
    "par": "paralyzed",
    "psn": "poisoned",
    "tox": "badly poisoned",
    "slp": "asleep",
}

_BOOST_LABELS = {
    "atk": "Atk",
    "def": "Def",
    "spa": "SpA",
    "spd": "SpD",
    "spe": "Spe",
    "accuracy": "Acc",
    "evasion": "Eva",
}


def _label(value: str | None) -> str:
    if not value:
        return "none"
    return _LABELS.get(value.lower(), value)


@dataclass(frozen=True)
class PublicActivePosition:
    slot: int
    species: str
    hp_percent: float
    status: str | None
    boosts: tuple[tuple[str, int], ...]
    fainted: bool


@dataclass(frozen=True)
class PublicSidePosition:
    name: str
    active: tuple[PublicActivePosition, ...]
    side_conditions: tuple[str, ...]


@dataclass(frozen=True)
class PublicBattlePosition:
    turn: int
    phase: str
    weather: str | None
    terrain: str | None
    pseudo_weather: tuple[str, ...]
    player: PublicSidePosition
    opponent: PublicSidePosition


def _active_positions(values: Any) -> tuple[PublicActivePosition, ...]:
    if not isinstance(values, list):
        raise ValueError("public view active slots are invalid")
    positions = []
    for slot, value in enumerate(values, start=1):
        if value is None:
            continue
        if not isinstance(value, dict) or not isinstance(value.get("species"), str):
            raise ValueError("public view active slot is invalid")
        boosts = value.get("boosts", {})
        if not isinstance(boosts, dict):
            raise ValueError("public view boosts are invalid")
        positions.append(
            PublicActivePosition(
                slot=slot,
                species=value["species"],
                hp_percent=float(value.get("hp_percent", 0)),
                status=value.get("status"),
                boosts=tuple(
                    sorted(
                        (str(stat), int(stage))
                        for stat, stage in boosts.items()
                        if int(stage) != 0
                    )
                ),
                fainted=bool(value.get("fainted", False)),
            )
        )
    return tuple(positions)


def _side_position(value: Any, *, own_side: bool) -> PublicSidePosition:
    if not isinstance(value, dict):
        raise ValueError("public view side is invalid")
    active_key = "active_details" if own_side else "active"
    conditions = value.get("side_conditions", [])
    if not isinstance(conditions, list):
        raise ValueError("public view side conditions are invalid")
    return PublicSidePosition(
        name=str(value.get("name", "")),
        active=_active_positions(value.get(active_key)),
        side_conditions=tuple(sorted(str(condition) for condition in conditions)),
    )


def build_public_battle_position(view: dict[str, Any]) -> PublicBattlePosition:
    """Freeze the exact public board that a recommendation is allowed to use."""
    field = view.get("field")
    if not isinstance(field, dict):
        raise ValueError("public view field is invalid")
    pseudo_weather = field.get("pseudo_weather", [])
    if not isinstance(pseudo_weather, list):
        raise ValueError("public view pseudo-weather is invalid")
    return PublicBattlePosition(
        turn=int(view.get("turn", 0)),
        phase=str(view.get("phase", "")),
        weather=field.get("weather"),
        terrain=field.get("terrain"),
        pseudo_weather=tuple(sorted(str(condition) for condition in pseudo_weather)),
        player=_side_position(view.get("player"), own_side=True),
        opponent=_side_position(view.get("opponent"), own_side=False),
    )


def _format_conditions(values: Iterable[str]) -> str:
    labels = [_label(value) for value in values]
    return ", ".join(labels) if labels else "none"


def _format_active(active: PublicActivePosition) -> str:
    hp = f"{active.hp_percent:g}%"
    status = _label(active.status)
    boosts = ", ".join(
        f"{_BOOST_LABELS.get(stat, stat)} {stage:+d}" for stat, stage in active.boosts
    ) or "none"
    fainted = "; fainted" if active.fainted else ""
    return (
        f"  Slot {active.slot}: {active.species} — {hp}; "
        f"status {status}; boosts {boosts}{fainted}"
    )


def format_public_battle_position(position: PublicBattlePosition) -> str:
    """Render a compact position block suitable for smoke output and later UI reuse."""
    field_parts = [
        f"terrain {_label(position.terrain)}",
        f"weather {_label(position.weather)}",
        f"other {_format_conditions(position.pseudo_weather)}",
    ]
    lines = [
        f"Position searched: turn {position.turn} ({position.phase})",
        f"Field: {'; '.join(field_parts)}",
    ]
    for side in (position.player, position.opponent):
        lines.append(
            f"{side.name}: side conditions {_format_conditions(side.side_conditions)}"
        )
        lines.extend(_format_active(active) for active in side.active)
    return "\n".join(lines)


def format_belief_search_evidence(
    recommendation: BeliefSearchResult,
    pruning: BeliefPruningResult,
    *,
    limit: int = 5,
) -> str:
    """Explain search coverage and leading alternatives without claiming optimality."""
    if limit <= 0:
        raise ValueError("evidence limit must be positive")
    lines = [
        "Search scope: "
        f"best of {len(recommendation.evaluated_choices)} shortlisted actions from "
        f"{pruning.legal_choice_count} legal choices / "
        f"{pruning.strategic_choice_count} strategic families; "
        "bounded one-ply search, not a proof of optimal play",
        "Top alternatives:",
    ]
    for rank, candidate in enumerate(recommendation.ranking[:limit], start=1):
        likely_world = max(candidate.worlds, key=lambda world: (world.weight, world.label))
        lines.append(
            f"  {rank}. {candidate.choice} | worst {candidate.worst_world_score:.1f} | "
            f"weighted {candidate.weighted_score:.1f} | "
            f"likely-world reply {likely_world.worst_response}"
        )
    return "\n".join(lines)
