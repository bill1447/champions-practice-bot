"""Read-only strategic position model for public-belief VGC reasoning.

This module deliberately does not choose Showdown commands. It extracts strategic
facts from the AI-visible view, summarizes belief diversity, and evaluates whether a
proposed resource trade actually advances a declared win condition.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from champions_practice.beliefs import build_public_opponent_belief


class PosteriorParticle(Protocol):
    weight: float
    world_id: str


@dataclass(frozen=True)
class ThreatAssessment:
    species: str
    urgency: str
    hp_percent: float | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ResourceAssessment:
    species: str
    hp_percent: float
    active: bool
    fainted: bool
    strategic_roles: tuple[str, ...]
    preservation_priority: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class SpeedControlAssessment:
    trick_room_active: bool
    our_tailwind: bool
    opponent_tailwind: bool
    available_our_tools: tuple[str, ...]


@dataclass(frozen=True)
class FieldControlAssessment:
    terrain: str | None
    weather: str | None
    our_side_conditions: tuple[str, ...]
    opponent_side_conditions: tuple[str, ...]
    available_our_setters: tuple[str, ...]


@dataclass(frozen=True)
class PosteriorAssessment:
    particle_count: int
    world_count: int
    world_mass: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class DesiredBoard:
    required_conditions: tuple[str, ...] = ()
    required_resources: tuple[str, ...] = ()
    minimum_effective_turns: int = 0


@dataclass(frozen=True)
class WinCondition:
    name: str
    objective: str
    desired_board: DesiredBoard
    preserve: tuple[str, ...] = ()
    acceptable_losses: tuple[str, ...] = ()
    failure_conditions: tuple[str, ...] = ()


@dataclass(frozen=True)
class BeliefBoardOutcome:
    label: str
    weight: float
    conditions: tuple[str, ...]
    living_resources: tuple[str, ...]
    effective_turns: int
    triggered_failures: tuple[str, ...] = ()


@dataclass(frozen=True)
class TradeAssessment:
    lost_resources: tuple[str, ...]
    preserve_losses: tuple[str, ...]
    unacceptable_losses: tuple[str, ...]
    viable_belief_mass: float
    supports_win_condition: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class StrategicAssessment:
    turn: int
    phase: str
    threats: tuple[ThreatAssessment, ...]
    resources: tuple[ResourceAssessment, ...]
    speed_control: SpeedControlAssessment
    field_control: FieldControlAssessment
    posterior: PosteriorAssessment
    key_resources: tuple[str, ...]
    notes: tuple[str, ...]


_SPEED_CONTROL_MOVES = {"trickroom", "tailwind", "icywind", "electroweb"}
_REDIRECTION_MOVES = {"followme", "ragepowder"}
_PROTECT_MOVES = {"protect", "detect", "spikyshield", "kingsshield", "banefulbunker"}
_PIVOT_MOVES = {"uturn", "voltswitch", "partingshot", "flipturn"}
_FIELD_MOVES = {
    "electricterrain",
    "grassyterrain",
    "mistyterrain",
    "psychicterrain",
    "raindance",
    "sunnyday",
    "sandstorm",
    "snowscape",
}
_FIELD_ABILITIES = {
    "electricsurge",
    "grassysurge",
    "mistysurge",
    "psychicsurge",
    "drizzle",
    "drought",
    "sandstream",
    "snowwarning",
}


def _id(value: object) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def _roles(pokemon: dict[str, Any]) -> tuple[str, ...]:
    moves = {_id(move) for move in pokemon.get("moves", [])}
    ability = _id(pokemon.get("ability") or "")
    roles: set[str] = set()
    if moves.intersection(_SPEED_CONTROL_MOVES):
        roles.add("speed-control")
    if moves.intersection(_REDIRECTION_MOVES):
        roles.add("redirection")
    if moves.intersection(_PROTECT_MOVES):
        roles.add("protect")
    if moves.intersection(_PIVOT_MOVES):
        roles.add("pivot")
    if moves.intersection(_FIELD_MOVES) or ability in _FIELD_ABILITIES:
        roles.add("field-control")
    return tuple(sorted(roles))


def _posterior_assessment(particles: Iterable[PosteriorParticle]) -> PosteriorAssessment:
    particles = tuple(particles)
    masses: dict[str, float] = {}
    for index, particle in enumerate(particles, start=1):
        label = particle.world_id or f"unlabeled-{index}"
        masses[label] = masses.get(label, 0.0) + float(particle.weight)
    total = sum(masses.values())
    world_mass = tuple(
        sorted(
            ((label, mass / total if total > 0 else 0.0) for label, mass in masses.items()),
            key=lambda value: (-value[1], value[0]),
        )
    )
    return PosteriorAssessment(
        particle_count=len(particles),
        world_count=len(masses),
        world_mass=world_mass,
    )


def _resource_assessments(view: dict[str, Any]) -> tuple[ResourceAssessment, ...]:
    player = view.get("player")
    if not isinstance(player, dict):
        raise ValueError("public view is missing player data")
    team = player.get("team")
    if not isinstance(team, list):
        raise ValueError("public view is missing the AI's own team data")

    preliminary: list[tuple[dict[str, Any], tuple[str, ...]]] = []
    role_counts: dict[str, int] = {}
    for pokemon in team:
        if not isinstance(pokemon, dict) or not isinstance(pokemon.get("species"), str):
            raise ValueError("AI team data is invalid")
        roles = _roles(pokemon)
        preliminary.append((pokemon, roles))
        if not bool(pokemon.get("fainted", False)):
            for role in roles:
                role_counts[role] = role_counts.get(role, 0) + 1

    resources = []
    for pokemon, roles in preliminary:
        fainted = bool(pokemon.get("fainted", False))
        unique_roles = tuple(role for role in roles if not fainted and role_counts.get(role) == 1)
        reasons = tuple(f"only living {role} provider" for role in unique_roles)
        if fainted:
            priority = "spent"
        elif unique_roles:
            priority = "high"
        elif roles:
            priority = "contextual"
        else:
            priority = "unassigned"
        resources.append(
            ResourceAssessment(
                species=pokemon["species"],
                hp_percent=float(pokemon.get("hp_percent", 0.0)),
                active=bool(pokemon.get("active", False)),
                fainted=fainted,
                strategic_roles=roles,
                preservation_priority=priority,
                reasons=reasons,
            )
        )
    return tuple(resources)


def _threat_assessments(view: dict[str, Any]) -> tuple[ThreatAssessment, ...]:
    opponent = view.get("opponent")
    if not isinstance(opponent, dict):
        raise ValueError("public view is missing opponent data")
    active = opponent.get("active")
    preview = opponent.get("preview_species")
    revealed = opponent.get("revealed", [])
    if not isinstance(active, list) or not isinstance(preview, list):
        raise ValueError("public opponent data is invalid")

    threats: list[ThreatAssessment] = []
    active_bases: set[str] = set()
    for pokemon in active:
        if pokemon is None:
            continue
        if not isinstance(pokemon, dict):
            raise ValueError("public opponent active data is invalid")
        base = str(pokemon.get("base_species") or pokemon.get("species") or "unknown")
        active_bases.add(_id(base))
        boosts = pokemon.get("boosts", {})
        positive = []
        if isinstance(boosts, dict):
            positive = [str(stat) for stat, stage in boosts.items() if int(stage) > 0]
        reasons = ["currently active"]
        if positive:
            reasons.append("positive boosts: " + ", ".join(sorted(positive)))
        threats.append(
            ThreatAssessment(
                species=str(pokemon.get("species") or base),
                urgency="immediate",
                hp_percent=(
                    float(pokemon["hp_percent"])
                    if pokemon.get("hp_percent") is not None
                    else None
                ),
                reasons=tuple(reasons),
            )
        )

    revealed_by_species = {
        _id(item.get("species")): item
        for item in revealed
        if isinstance(item, dict) and item.get("species")
    }
    for species in preview:
        if _id(species) in active_bases:
            continue
        observation = revealed_by_species.get(_id(species), {})
        if bool(observation.get("fainted", False)):
            continue
        reasons = ["available from team preview"]
        if bool(observation.get("seen", False)):
            reasons.append("previously revealed")
        threats.append(
            ThreatAssessment(
                species=str(species),
                urgency="latent",
                hp_percent=(
                    float(observation["hp_percent"])
                    if observation.get("hp_percent") is not None
                    else None
                ),
                reasons=tuple(reasons),
            )
        )
    return tuple(threats)


def assess_strategic_position(
    view: dict[str, Any],
    *,
    particles: Iterable[PosteriorParticle] = (),
) -> StrategicAssessment:
    """Build a read-only strategic assessment from legal AI-visible information."""
    field = view.get("field")
    player = view.get("player")
    opponent = view.get("opponent")
    if (
        not isinstance(field, dict)
        or not isinstance(player, dict)
        or not isinstance(opponent, dict)
    ):
        raise ValueError("public view is missing field or side data")

    # Reuse the production public-information whitelist before doing any strategic work.
    build_public_opponent_belief(view)
    resources = _resource_assessments(view)
    pseudo_weather = {_id(value) for value in field.get("pseudo_weather", [])}
    our_conditions = tuple(sorted(str(value) for value in player.get("side_conditions", [])))
    opponent_conditions = tuple(
        sorted(str(value) for value in opponent.get("side_conditions", []))
    )

    speed_tools = sorted(
        {
            species
            for resource in resources
            if "speed-control" in resource.strategic_roles and not resource.fainted
            for species in (resource.species,)
        }
    )
    field_setters = sorted(
        {
            species
            for resource in resources
            if "field-control" in resource.strategic_roles and not resource.fainted
            for species in (resource.species,)
        }
    )
    key_resources = tuple(
        resource.species
        for resource in resources
        if resource.preservation_priority == "high"
    )

    notes = (
        "Assessment is descriptive only; it does not choose a Showdown command.",
        "Opponent unrevealed sets remain hypotheses in the posterior, not facts.",
    )
    return StrategicAssessment(
        turn=int(view.get("turn", 0)),
        phase=str(view.get("phase", "")),
        threats=_threat_assessments(view),
        resources=resources,
        speed_control=SpeedControlAssessment(
            trick_room_active="trickroom" in pseudo_weather,
            our_tailwind="tailwind" in {_id(value) for value in our_conditions},
            opponent_tailwind="tailwind" in {_id(value) for value in opponent_conditions},
            available_our_tools=tuple(speed_tools),
        ),
        field_control=FieldControlAssessment(
            terrain=field.get("terrain"),
            weather=field.get("weather"),
            our_side_conditions=our_conditions,
            opponent_side_conditions=opponent_conditions,
            available_our_setters=tuple(field_setters),
        ),
        posterior=_posterior_assessment(particles),
        key_resources=key_resources,
        notes=notes,
    )


def assess_trade_against_win_condition(
    win_condition: WinCondition,
    *,
    lost_resources: Iterable[str],
    outcomes: Iterable[BeliefBoardOutcome],
    robust_threshold: float = 0.8,
) -> TradeAssessment:
    """Judge a sacrifice/trade by resulting win-condition viability, not material alone."""
    if not 0.0 <= robust_threshold <= 1.0:
        raise ValueError("robust_threshold must be between 0 and 1")
    lost = tuple(sorted(set(str(value) for value in lost_resources)))
    outcome_values = tuple(outcomes)
    if not outcome_values:
        raise ValueError("at least one belief outcome is required")
    if any(outcome.weight <= 0 for outcome in outcome_values):
        raise ValueError("belief outcome weights must be positive")

    preserve = set(win_condition.preserve)
    acceptable = set(win_condition.acceptable_losses)
    preserve_losses = tuple(sorted(preserve.intersection(lost)))
    unacceptable_losses = tuple(
        sorted(
            resource
            for resource in lost
            if resource not in acceptable and resource not in preserve
        )
    )

    required_conditions = set(win_condition.desired_board.required_conditions)
    required_resources = set(win_condition.desired_board.required_resources)
    declared_failures = set(win_condition.failure_conditions)
    viable_weight = 0.0
    total_weight = sum(outcome.weight for outcome in outcome_values)
    failed_worlds = 0

    for outcome in outcome_values:
        conditions_ok = required_conditions.issubset(outcome.conditions)
        resources_ok = required_resources.issubset(outcome.living_resources)
        turns_ok = outcome.effective_turns >= win_condition.desired_board.minimum_effective_turns
        failures_ok = not declared_failures.intersection(outcome.triggered_failures)
        viable = conditions_ok and resources_ok and turns_ok and failures_ok
        if viable:
            viable_weight += outcome.weight
        else:
            failed_worlds += 1

    coverage = viable_weight / total_weight
    supports = coverage >= robust_threshold and not preserve_losses and not unacceptable_losses
    reasons = [f"win-condition coverage {coverage:.1%} across {len(outcome_values)} belief worlds"]
    if preserve_losses:
        reasons.append("lost protected resource(s): " + ", ".join(preserve_losses))
    if unacceptable_losses:
        reasons.append("additional non-acceptable losses: " + ", ".join(unacceptable_losses))
    if failed_worlds:
        reasons.append(f"{failed_worlds} belief world(s) fail the desired-board requirements")
    if supports:
        reasons.append("trade converts material into a robust path to the declared win condition")
    else:
        reasons.append("trade does not robustly secure the declared win condition")

    return TradeAssessment(
        lost_resources=lost,
        preserve_losses=preserve_losses,
        unacceptable_losses=unacceptable_losses,
        viable_belief_mass=coverage,
        supports_win_condition=supports,
        reasons=tuple(reasons),
    )


def format_strategic_assessment(assessment: StrategicAssessment) -> str:
    """Render the read-only assessment for smoke output and later UI reuse."""
    immediate = [threat.species for threat in assessment.threats if threat.urgency == "immediate"]
    latent = [threat.species for threat in assessment.threats if threat.urgency == "latent"]
    speed = []
    if assessment.speed_control.trick_room_active:
        speed.append("Trick Room active")
    if assessment.speed_control.our_tailwind:
        speed.append("our Tailwind active")
    if assessment.speed_control.opponent_tailwind:
        speed.append("opponent Tailwind active")
    if not speed:
        speed.append("no active major speed-control field effect")

    masses = ", ".join(
        f"{label} {mass:.1%}" for label, mass in assessment.posterior.world_mass
    ) or "none"
    key_resources = ", ".join(assessment.key_resources) or "none identified"
    return "\n".join(
        (
            f"Strategic assessment: turn {assessment.turn} ({assessment.phase})",
            "Immediate threats: " + (", ".join(immediate) or "none"),
            "Latent threats: " + (", ".join(latent) or "none"),
            "Speed control: " + "; ".join(speed),
            f"Field: terrain {assessment.field_control.terrain or 'none'}; "
            f"weather {assessment.field_control.weather or 'none'}",
            "Key resources: " + key_resources,
            f"Posterior: {assessment.posterior.particle_count} particles / "
            f"{assessment.posterior.world_count} worlds ({masses})",
            *assessment.notes,
        )
    )
