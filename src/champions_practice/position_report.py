"""Human-readable public battle positions and bounded-search evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from champions_practice.belief_search import (
    BeliefChoiceScore,
    BeliefPruningResult,
    BeliefSearchResult,
    BeliefWorldOutcome,
    SelectiveContinuationResult,
)
from champions_practice.exact_search import ExactScoreBreakdown, SideId


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
                        (str(stat), int(stage)) for stat, stage in boosts.items() if int(stage) != 0
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
    boosts = (
        ", ".join(f"{_BOOST_LABELS.get(stat, stat)} {stage:+d}" for stat, stage in active.boosts)
        or "none"
    )
    fainted = "; fainted" if active.fainted else ""
    return (
        f"  Slot {active.slot}: {active.species} — {hp}; status {status}; boosts {boosts}{fainted}"
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
        lines.append(f"{side.name}: side conditions {_format_conditions(side.side_conditions)}")
        lines.extend(_format_active(active) for active in side.active)
    return "\n".join(lines)


def _worst_world(candidate: BeliefChoiceScore) -> BeliefWorldOutcome:
    return min(
        candidate.worlds,
        key=lambda world: (world.worst_score, world.label),
    )


def _format_score_components(breakdown: ExactScoreBreakdown | None) -> str:
    if breakdown is None:
        return "components unavailable"
    values = []
    if breakdown.terminal:
        values.append(f"terminal {breakdown.terminal:+.1f}")
    values.extend(
        (
            f"material {breakdown.material:+.1f}",
            f"position {breakdown.position:+.1f}",
            f"speed {breakdown.speed:+.1f}",
        )
    )
    return ", ".join(values)


def _format_summary_active(value: dict[str, Any] | None, slot: int) -> str:
    if not value:
        return f"    Slot {slot}: empty"
    maximum = max(1, int(value.get("maxhp", 1)))
    hp = max(0, int(value.get("hp", 0)))
    percent = 100 * hp / maximum
    status = _label(value.get("status"))
    boosts_value = value.get("boosts", {})
    boosts = (
        ", ".join(
            f"{_BOOST_LABELS.get(str(stat), stat)} {int(stage):+d}"
            for stat, stage in sorted(boosts_value.items())
            if int(stage) != 0
        )
        if isinstance(boosts_value, dict)
        else ""
    ) or "none"
    fainted = "; fainted" if value.get("fainted") or hp == 0 else ""
    return (
        f"    Slot {slot}: {value.get('species', 'unknown')} — {percent:.1f}%; "
        f"status {status}; boosts {boosts}{fainted}"
    )


def format_exact_result_board(summary: dict[str, Any], *, side: SideId) -> str:
    """Render the four active slots from one sampled hypothetical result."""
    opponent: SideId = "p2" if side == "p1" else "p1"
    field = summary.get("field", {})
    if not isinstance(field, dict):
        field = {}
    pseudo_weather = field.get("pseudoWeather", [])
    if not isinstance(pseudo_weather, list):
        pseudo_weather = []
    lines = [
        "  Result field: "
        f"terrain {_label(field.get('terrain'))}; "
        f"weather {_label(field.get('weather'))}; "
        f"other {_format_conditions(str(value) for value in pseudo_weather)}"
    ]
    for side_id, role in ((side, "Practice AI"), (opponent, "Human")):
        side_value = summary.get(side_id, {})
        if not isinstance(side_value, dict):
            side_value = {}
        conditions = side_value.get("sideConditions", [])
        if not isinstance(conditions, list):
            conditions = []
        lines.append(
            f"  {role}: side conditions {_format_conditions(str(value) for value in conditions)}"
        )
        active = side_value.get("active", [])
        if not isinstance(active, list):
            active = []
        lines.extend(
            _format_summary_active(value if isinstance(value, dict) else None, slot)
            for slot, value in enumerate(active, start=1)
        )
    return "\n".join(lines)


def _compact_active_result(summary: dict[str, Any], *, side: SideId) -> str:
    opponent: SideId = "p2" if side == "p1" else "p1"

    def actives(side_id: SideId) -> str:
        side_value = summary.get(side_id, {})
        values = side_value.get("active", []) if isinstance(side_value, dict) else []
        if not isinstance(values, list):
            return "unknown"
        rendered = []
        for value in values:
            if not isinstance(value, dict):
                continue
            maximum = max(1, int(value.get("maxhp", 1)))
            hp = max(0, int(value.get("hp", 0)))
            percent = 100 * hp / maximum
            state = "fainted" if value.get("fainted") or hp == 0 else f"{percent:.1f}%"
            rendered.append(f"{value.get('species', 'unknown')} {state}")
        return ", ".join(rendered) or "empty"

    return f"AI [{actives(side)}]; Human [{actives(opponent)}]"


def format_belief_search_evidence(
    recommendation: BeliefSearchResult,
    pruning: BeliefPruningResult,
    *,
    limit: int = 8,
    rejected_limit: int = 5,
) -> str:
    """Explain the final shortlist, worst branches, and major pruning rejections."""
    if limit <= 0:
        raise ValueError("evidence limit must be positive")
    if rejected_limit <= 0:
        raise ValueError("rejected limit must be positive")
    lines = [
        "Search scope: "
        f"best of {len(recommendation.evaluated_choices)} shortlisted actions from "
        f"{pruning.legal_choice_count} legal choices / "
        f"{pruning.strategic_choice_count} strategic families; "
        "bounded one-ply search, not a proof of optimal play",
        "Final shortlist diagnostics:",
    ]
    for rank, candidate in enumerate(recommendation.ranking[:limit], start=1):
        worst_world = _worst_world(candidate)
        gap = candidate.worst_world_score - recommendation.chosen.worst_world_score
        marker = " [CHOSEN]" if candidate.choice == recommendation.chosen.choice else ""
        lines.append(
            f"  {rank}.{marker} {candidate.choice} | "
            f"worst {candidate.worst_world_score:.1f} ({gap:+.1f} vs chosen) | "
            f"weighted {candidate.weighted_score:.1f}"
        )
        lines.append(
            f"     worst branch: {worst_world.label} "
            f"(weight {worst_world.weight:.3f}) vs {worst_world.worst_response} | "
            f"{_format_score_components(worst_world.score_breakdown)}"
        )

    chosen_worst = _worst_world(recommendation.chosen)
    if chosen_worst.worst_sample_summary is not None:
        sample_score = chosen_worst.worst_sample_score
        score_text = f"{sample_score:.1f}" if sample_score is not None else "unknown"
        lines.extend(
            (
                "Chosen action's worst sampled resulting board (hypothetical belief world):",
                f"  {chosen_worst.label} vs {chosen_worst.worst_response}; "
                f"sample score {score_text} "
                "(the displayed branch is one RNG future; ranking averages all samples)",
                format_exact_result_board(
                    chosen_worst.worst_sample_summary,
                    side=recommendation.side,
                ),
            )
        )

    selected_families = set(pruning.selected_family_representatives)
    rejected_families = [
        candidate
        for candidate in pruning.family_ranking
        if candidate.choice not in selected_families
    ][:rejected_limit]
    final_choices = set(pruning.candidate_shortlist)
    rejected_expanded = [
        candidate for candidate in pruning.expanded_ranking if candidate.choice not in final_choices
    ][:rejected_limit]
    lines.append("Pruning audit (cheap screening scores, not final belief scores):")
    lines.append(
        f"  Expanded {len(selected_families)} of "
        f"{pruning.strategic_choice_count} strategic families"
    )
    if rejected_families:
        lines.append("  Best family plans not expanded:")
        for candidate in rejected_families:
            detail = ""
            if candidate.worst_response:
                detail += f" vs {candidate.worst_response}"
            if candidate.score_breakdown is not None:
                detail += f" | {_format_score_components(candidate.score_breakdown)}"
            if candidate.worst_sample_summary is not None:
                detail += " | " + _compact_active_result(
                    candidate.worst_sample_summary,
                    side=recommendation.side,
                )
            lines.append(
                f"    - {candidate.choice} | screen worst {candidate.worst_score:.1f}{detail}"
            )
    if rejected_expanded:
        lines.append("  Best expanded actions omitted from the final shortlist:")
        for candidate in rejected_expanded:
            detail = ""
            if candidate.worst_response:
                detail += f" vs {candidate.worst_response}"
            if candidate.score_breakdown is not None:
                detail += f" | {_format_score_components(candidate.score_breakdown)}"
            if candidate.worst_sample_summary is not None:
                detail += " | " + _compact_active_result(
                    candidate.worst_sample_summary,
                    side=recommendation.side,
                )
            lines.append(
                f"    - {candidate.choice} | screen worst {candidate.worst_score:.1f}{detail}"
            )
    return "\n".join(lines)


def format_selective_continuation(result: SelectiveContinuationResult) -> str:
    """Explain the bounded principal-variation continuation probe."""
    changed = result.chosen_choice != result.original_choice
    verdict = (
        f"changed from {result.original_choice} to {result.chosen_choice}"
        if changed
        else f"survived: {result.chosen_choice}"
    )
    lines = [
        "Selective continuation probe:",
        "  Scope: extend each top one-ply candidate from its current worst "
        "world/reply/RNG branch by one additional Showdown decision; "
        "not exhaustive two-ply minimax",
        f"  Result: original one-ply recommendation {verdict}",
    ]
    for rank, line in enumerate(result.ranking, start=1):
        marker = " [CONTINUATION CHOSEN]" if line.first_choice == result.chosen_choice else ""
        lines.append(
            f"  {rank}.{marker} first {line.first_choice} | "
            f"one-ply sample {line.first_turn_score:.1f} -> leaf {line.leaf_score:.1f} | "
            f"phase {line.next_phase} | {line.branch_count} added forks"
        )
        lines.append(
            f"     source: {line.first_world} (weight {line.first_world_weight:.3f}) "
            f"vs {line.first_response}"
        )
        if line.protect_chain_slots:
            slots = ", ".join(str(slot) for slot in line.protect_chain_slots)
            lines.append(
                f"     exact state: consecutive-Protect chain preserved for AI slot(s) {slots}"
            )
        if line.next_search is None:
            lines.append("     continuation: battle ended on the first branch")
            continue
        next_choice = line.next_search.chosen.choice
        next_world = _worst_world(line.next_search.chosen)
        lines.append(
            f"     next: {next_choice} vs {next_world.worst_response} | "
            f"{_format_score_components(line.leaf_breakdown)}"
        )

    chosen = result.ranking[0]
    lines.extend(
        (
            "Continuation-chosen worst sampled leaf board:",
            format_exact_result_board(chosen.leaf_summary, side=result.side),
            f"Continuation cost: {result.branch_count} added forks, "
            f"{result.total_seconds * 1000:.1f} ms",
        )
    )
    return "\n".join(lines)
