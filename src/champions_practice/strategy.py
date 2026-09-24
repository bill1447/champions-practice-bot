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
    speed: int | None = None
    damaging_move_count: int = 0


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
class ResourcePurpose:
    """Why a specific Pokemon must remain available for the intended endgame."""

    species: str
    purpose: str
    position: str = "any"

    def __post_init__(self) -> None:
        if self.position not in {"any", "active", "bench"}:
            raise ValueError("resource purpose position must be any, active, or bench")
        if not self.species.strip() or not self.purpose.strip():
            raise ValueError("resource purpose species and purpose must be non-empty")


@dataclass(frozen=True)
class DesiredBoard:
    required_conditions: tuple[str, ...] = ()
    required_resources: tuple[str, ...] = ()
    minimum_effective_turns: int = 0
    required_active_pair: tuple[str, ...] = ()
    safe_entry_resources: tuple[str, ...] = ()
    resource_purposes: tuple[ResourcePurpose, ...] = ()

    def __post_init__(self) -> None:
        if len(self.required_active_pair) > 2:
            raise ValueError("required_active_pair may contain at most two Pokemon")
        if self.minimum_effective_turns < 0:
            raise ValueError("minimum_effective_turns must be non-negative")


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
    active_resources: tuple[str, ...] = ()
    newly_active_resources: tuple[str, ...] = ()


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
_SUPPORT_MOVES = {
    "helpinghand",
    "healpulse",
    "lifedew",
    "coaching",
    "wideguard",
    "quickguard",
}
_SACRIFICIAL_SUPPORT_ROLES = {
    "redirection",
    "speed-control",
    "field-control",
    "pivot",
    "support",
}
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
    if moves.intersection(_SUPPORT_MOVES):
        roles.add("support")
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
                speed=(
                    int(pokemon["speed"])
                    if pokemon.get("speed") is not None
                    else None
                ),
                damaging_move_count=int(pokemon.get("damaging_move_count", 0)),
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

    desired = win_condition.desired_board
    required_conditions = set(desired.required_conditions)
    required_resources = set(desired.required_resources)
    required_active_pair = set(desired.required_active_pair)
    safe_entry_resources = set(desired.safe_entry_resources)
    declared_failures = set(win_condition.failure_conditions)
    viable_weight = 0.0
    total_weight = sum(outcome.weight for outcome in outcome_values)
    failed_worlds = 0
    positioning_failures = 0

    for outcome in outcome_values:
        living = set(outcome.living_resources)
        active = set(outcome.active_resources)
        newly_active = set(outcome.newly_active_resources)
        conditions_ok = required_conditions.issubset(outcome.conditions)
        resources_ok = required_resources.issubset(living)
        turns_ok = outcome.effective_turns >= desired.minimum_effective_turns
        failures_ok = not declared_failures.intersection(outcome.triggered_failures)
        active_pair_ok = required_active_pair.issubset(active)
        safe_entry_ok = safe_entry_resources.issubset(newly_active)

        purpose_ok = True
        for purpose in desired.resource_purposes:
            if purpose.species not in living:
                purpose_ok = False
                break
            if purpose.position == "active" and purpose.species not in active:
                purpose_ok = False
                break
            if purpose.position == "bench" and purpose.species in active:
                purpose_ok = False
                break

        viable = (
            conditions_ok
            and resources_ok
            and turns_ok
            and failures_ok
            and active_pair_ok
            and safe_entry_ok
            and purpose_ok
        )
        if viable:
            viable_weight += outcome.weight
        else:
            failed_worlds += 1
            if not active_pair_ok or not safe_entry_ok or not purpose_ok:
                positioning_failures += 1

    coverage = viable_weight / total_weight
    supports = coverage >= robust_threshold and not preserve_losses and not unacceptable_losses
    reasons = [
        f"win-condition coverage {coverage:.1%} across {len(outcome_values)} belief worlds"
    ]
    if preserve_losses:
        reasons.append("lost protected resource(s): " + ", ".join(preserve_losses))
    if unacceptable_losses:
        reasons.append("additional non-acceptable losses: " + ", ".join(unacceptable_losses))
    if failed_worlds:
        reasons.append(f"{failed_worlds} belief world(s) fail the desired-board requirements")
    if positioning_failures:
        reasons.append(
            f"{positioning_failures} belief world(s) fail pairing, entry, "
            "or resource-purpose requirements"
        )
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



@dataclass(frozen=True)
class StrategicPlan:
    """One inspectable multi-turn objective, separate from concrete move selection."""

    name: str
    objective: str
    desired_board: DesiredBoard
    required_resources: tuple[str, ...] = ()
    preserve: tuple[str, ...] = ()
    acceptable_losses: tuple[str, ...] = ()
    failure_conditions: tuple[str, ...] = ()
    rationale: tuple[str, ...] = ()
    tactical_priorities: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlanWorldOutcome:
    """One hypothetical belief-world result used to judge a strategic plan."""

    label: str
    weight: float
    conditions: tuple[str, ...]
    living_resources: tuple[str, ...]
    effective_turns: int
    lost_resources: tuple[str, ...] = ()
    triggered_failures: tuple[str, ...] = ()
    active_resources: tuple[str, ...] = ()
    newly_active_resources: tuple[str, ...] = ()


@dataclass(frozen=True)
class StrategicPlanEvaluation:
    plan: StrategicPlan
    viable_belief_mass: float
    robust: bool
    failed_worlds: int
    preserve_failure_mass: float
    required_resource_failure_mass: float
    condition_failure_mass: float
    timing_failure_mass: float
    declared_failure_mass: float
    unacceptable_loss_mass: float
    active_pair_failure_mass: float
    safe_entry_failure_mass: float
    purpose_failure_mass: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class StrategicPlanRanking:
    ranking: tuple[StrategicPlanEvaluation, ...]

    @property
    def chosen(self) -> StrategicPlanEvaluation:
        if not self.ranking:
            raise ValueError("strategic plan ranking is empty")
        return self.ranking[0]


def strategic_plan_from_win_condition(
    win_condition: WinCondition,
    *,
    rationale: Iterable[str] = (),
) -> StrategicPlan:
    """Promote an explicit win condition into an inspectable plan candidate."""
    return StrategicPlan(
        name=win_condition.name,
        objective=win_condition.objective,
        desired_board=win_condition.desired_board,
        required_resources=win_condition.desired_board.required_resources,
        preserve=win_condition.preserve,
        acceptable_losses=win_condition.acceptable_losses,
        failure_conditions=win_condition.failure_conditions,
        rationale=tuple(rationale),
    )


def _living_resources(assessment: StrategicAssessment) -> tuple[ResourceAssessment, ...]:
    return tuple(resource for resource in assessment.resources if not resource.fainted)


def generate_strategic_plans(
    assessment: StrategicAssessment,
    *,
    limit: int | None = 8,
) -> tuple[StrategicPlan, ...]:
    """Generate position-derived objectives without selecting a Showdown command.

    These are deliberately broad plans. Later exact search will decide whether and how a
    plan can be executed tactically. Generation uses only the read-only strategic
    assessment, so opponent hidden sets remain represented only by the posterior.
    """
    if limit is not None and limit <= 0:
        raise ValueError("plan limit must be positive")

    plans: list[StrategicPlan] = []
    key_resources = tuple(assessment.key_resources)
    living = _living_resources(assessment)

    if assessment.speed_control.trick_room_active:
        plans.append(
            StrategicPlan(
                name="exploit-trick-room",
                objective="Convert active Trick Room into progress before the speed window expires.",
                desired_board=DesiredBoard(
                    required_conditions=(
                        "favorable-speed-control",
                        "trickroom-progress",
                    ),
                    minimum_effective_turns=1,
                ),
                preserve=key_resources,
                failure_conditions=("trickroom-expired-before-progress",),
                rationale=(
                    "Trick Room is currently active.",
                    "Finite speed-control turns should be treated as a strategic resource.",
                ),
            )
        )
    elif assessment.speed_control.our_tailwind:
        plans.append(
            StrategicPlan(
                name="exploit-tailwind",
                objective="Convert active Tailwind into progress before the speed window expires.",
                desired_board=DesiredBoard(
                    required_conditions=(
                        "favorable-speed-control",
                        "tailwind-progress",
                    ),
                    minimum_effective_turns=1,
                ),
                preserve=key_resources,
                failure_conditions=("tailwind-expired-before-progress",),
                rationale=("Our Tailwind is currently active.",),
            )
        )

    if assessment.speed_control.opponent_tailwind:
        protectors = tuple(
            resource.species
            for resource in living
            if "protect" in resource.strategic_roles
        )
        plans.append(
            StrategicPlan(
                name="stall-opponent-tailwind",
                objective="Deny efficient conversion of the opponent's Tailwind turns.",
                desired_board=DesiredBoard(
                    required_conditions=("opponent-tailwind-expired",),
                ),
                preserve=key_resources,
                failure_conditions=("critical-resource-lost-during-tailwind",),
                rationale=(
                    "Opponent Tailwind is currently active.",
                    (
                        "Protect-capable resources are available: " + ", ".join(protectors)
                        if protectors
                        else "No Protect-capable resource was identified."
                    ),
                ),
                tactical_priorities=("prefer-protect", "prefer-switch"),
            )
        )

    if (
        not assessment.speed_control.trick_room_active
        and not assessment.speed_control.our_tailwind
    ):
        for species in assessment.speed_control.available_our_tools:
            plans.append(
                StrategicPlan(
                    name=f"establish-speed-control-{_id(species)}",
                    objective=f"Use {species} to establish a favorable speed-control state.",
                    desired_board=DesiredBoard(
                        required_conditions=("favorable-speed-control",),
                        required_resources=(species,),
                    ),
                    required_resources=(species,),
                    preserve=tuple(
                        resource
                        for resource in key_resources
                        if resource != species
                    ),
                    failure_conditions=("speed-control-denied",),
                    rationale=(f"{species} is a living speed-control provider.",),
                    tactical_priorities=("prefer-speed-control",),
                )
            )

    for threat in assessment.threats:
        if threat.urgency != "immediate":
            continue
        if not any(reason.startswith("positive boosts:") for reason in threat.reasons):
            continue
        threat_id = _id(threat.species)
        plans.append(
            StrategicPlan(
                name=f"neutralize-boosted-{threat_id}",
                objective=f"Remove or neutralize the boosted {threat.species} before it snowballs.",
                desired_board=DesiredBoard(
                    required_conditions=(f"threat-neutralized:{threat_id}",),
                ),
                preserve=key_resources,
                failure_conditions=(f"threat-snowballs:{threat_id}",),
                rationale=tuple(threat.reasons),
                tactical_priorities=(f"target:{threat.species}",),
            )
        )

    active_key_resources = tuple(
        resource
        for resource in living
        if resource.active and resource.preservation_priority == "high"
    )
    bench_key_resources = tuple(
        resource
        for resource in living
        if not resource.active and resource.preservation_priority == "high"
    )
    if len(active_key_resources) == 1:
        anchor = active_key_resources[0]
        for partner in bench_key_resources:
            plans.append(
                StrategicPlan(
                    name=(
                        f"create-{_id(partner.species)}-"
                        f"{_id(anchor.species)}-board"
                    ),
                    objective=(
                        f"Bring {partner.species} in safely beside {anchor.species} "
                        "to combine two high-priority strategic resources."
                    ),
                    desired_board=DesiredBoard(
                        required_resources=(
                            anchor.species,
                            partner.species,
                        ),
                        required_active_pair=(
                            partner.species,
                            anchor.species,
                        ),
                        safe_entry_resources=(partner.species,),
                    ),
                    required_resources=(
                        anchor.species,
                        partner.species,
                    ),
                    preserve=key_resources,
                    rationale=(
                        f"{anchor.species} is already active and strategically unique.",
                        f"{partner.species} is a benched strategically unique resource.",
                    ),
                    tactical_priorities=(f"preserve:{anchor.species}",),
                )
            )

    active_supports = tuple(
        resource
        for resource in living
        if (
            resource.active
            and resource.hp_percent <= 40.0
            and set(resource.strategic_roles).intersection(
                _SACRIFICIAL_SUPPORT_ROLES
            )
        )
    )
    healthy_bench_keys = tuple(
        resource
        for resource in living
        if (
            not resource.active
            and resource.preservation_priority == "high"
            and resource.hp_percent >= 60.0
        )
    )
    if len(active_supports) == 2:
        acceptable_losses = tuple(resource.species for resource in active_supports)
        for endgame in healthy_bench_keys:
            plans.append(
                StrategicPlan(
                    name=(
                        "sacrifice-support-for-"
                        f"{_id(endgame.species)}-endgame"
                    ),
                    objective=(
                        "Allow already-spent active support resources to be traded "
                        f"if doing so preserves {endgame.species} and improves the board."
                    ),
                    desired_board=DesiredBoard(
                        required_resources=(endgame.species,),
                        resource_purposes=(
                            ResourcePurpose(
                                species=endgame.species,
                                purpose="endgame",
                                position="bench",
                            ),
                        ),
                    ),
                    required_resources=(endgame.species,),
                    preserve=(endgame.species,),
                    acceptable_losses=acceptable_losses,
                    failure_conditions=(
                        f"critical-resource-lost:{_id(endgame.species)}",
                    ),
                    rationale=(
                        "Both active support resources are at 40% HP or lower.",
                        (
                            f"{endgame.species} is a healthy benched unique-role "
                            "resource."
                        ),
                        "Exact evidence must still justify the material trade.",
                    ),
                )
            )

    immediate_threats = tuple(
        threat
        for threat in assessment.threats
        if threat.urgency == "immediate"
    )
    cleanup_candidates = tuple(
        resource
        for resource in living
        if (
            not resource.active
            and resource.hp_percent >= 70.0
            and resource.damaging_move_count >= 2
            and resource.speed is not None
        )
    )
    chipped_active_board = bool(immediate_threats) and all(
        threat.hp_percent is not None and threat.hp_percent <= 55.0
        for threat in immediate_threats
    )
    if chipped_active_board and cleanup_candidates:
        if assessment.speed_control.trick_room_active:
            cleanup = min(
                cleanup_candidates,
                key=lambda resource: (
                    resource.speed,
                    -resource.damaging_move_count,
                    -resource.hp_percent,
                    resource.species,
                ),
            )
            speed_rationale = "Trick Room favors the slowest qualified reserve."
        else:
            cleanup = min(
                cleanup_candidates,
                key=lambda resource: (
                    -resource.speed,
                    -resource.damaging_move_count,
                    -resource.hp_percent,
                    resource.species,
                ),
            )
            speed_rationale = "Outside Trick Room, the fastest qualified reserve is favored."

        plans.append(
            StrategicPlan(
                name=f"reserve-{_id(cleanup.species)}-cleanup",
                objective=(
                    f"Keep {cleanup.species} in reserve as a cleanup resource while "
                    "the opposing active board is already chipped."
                ),
                desired_board=DesiredBoard(
                    required_resources=(cleanup.species,),
                    resource_purposes=(
                        ResourcePurpose(
                            species=cleanup.species,
                            purpose="cleanup",
                            position="bench",
                        ),
                    ),
                ),
                required_resources=(cleanup.species,),
                preserve=(cleanup.species,),
                failure_conditions=(
                    f"critical-resource-lost:{_id(cleanup.species)}",
                ),
                rationale=(
                    "All visible opposing active resources are at 55% HP or lower.",
                    (
                        f"{cleanup.species} is healthy in reserve with "
                        f"{cleanup.damaging_move_count} damaging moves."
                    ),
                    speed_rationale,
                ),
                tactical_priorities=(f"preserve:{cleanup.species}",),
            )
        )

    for species in key_resources:
        plans.append(
            StrategicPlan(
                name=f"preserve-{_id(species)}",
                objective=f"Preserve {species} because it uniquely supplies a needed role.",
                desired_board=DesiredBoard(required_resources=(species,)),
                required_resources=(species,),
                preserve=(species,),
                failure_conditions=(f"critical-resource-lost:{_id(species)}",),
                rationale=tuple(
                    reason
                    for resource in assessment.resources
                    if resource.species == species
                    for reason in resource.reasons
                ),
                tactical_priorities=(f"preserve:{species}",),
            )
        )

    deduplicated: dict[str, StrategicPlan] = {}
    for plan in plans:
        deduplicated.setdefault(plan.name, plan)
    values = tuple(deduplicated.values())
    return values if limit is None else values[:limit]


def evaluate_strategic_plan(
    plan: StrategicPlan,
    *,
    outcomes: Iterable[PlanWorldOutcome],
    robust_threshold: float = 0.8,
) -> StrategicPlanEvaluation:
    """Evaluate one plan across hypothetical public-belief worlds."""
    if not 0.0 <= robust_threshold <= 1.0:
        raise ValueError("robust_threshold must be between 0 and 1")

    outcomes = tuple(outcomes)
    if not outcomes:
        raise ValueError("at least one plan outcome is required")
    if any(outcome.weight <= 0 for outcome in outcomes):
        raise ValueError("plan outcome weights must be positive")

    total_weight = sum(outcome.weight for outcome in outcomes)
    desired_conditions = set(plan.desired_board.required_conditions)
    required_resources = set(plan.required_resources).union(
        plan.desired_board.required_resources
    )
    required_active_pair = set(plan.desired_board.required_active_pair)
    safe_entry_resources = set(plan.desired_board.safe_entry_resources)
    purposes = tuple(plan.desired_board.resource_purposes)
    preserve = set(plan.preserve)
    acceptable_losses = set(plan.acceptable_losses)
    declared_failures = set(plan.failure_conditions)

    viable_weight = 0.0
    preserve_failure = 0.0
    resource_failure = 0.0
    condition_failure = 0.0
    timing_failure = 0.0
    declared_failure = 0.0
    unacceptable_loss = 0.0
    active_pair_failure = 0.0
    safe_entry_failure = 0.0
    purpose_failure = 0.0
    failed_worlds = 0

    for outcome in outcomes:
        living = set(outcome.living_resources)
        active = set(outcome.active_resources)
        newly_active = set(outcome.newly_active_resources)
        lost = set(outcome.lost_resources)
        preserve_ok = preserve.issubset(living) and not preserve.intersection(lost)
        resources_ok = required_resources.issubset(living)
        conditions_ok = desired_conditions.issubset(outcome.conditions)
        timing_ok = outcome.effective_turns >= plan.desired_board.minimum_effective_turns
        failures_ok = not declared_failures.intersection(outcome.triggered_failures)
        extra_losses = lost.difference(acceptable_losses).difference(preserve)
        losses_ok = not extra_losses
        active_pair_ok = required_active_pair.issubset(active)
        safe_entry_ok = safe_entry_resources.issubset(newly_active)

        purpose_ok = True
        for purpose in purposes:
            if purpose.species not in living:
                purpose_ok = False
                break
            if purpose.position == "active" and purpose.species not in active:
                purpose_ok = False
                break
            if purpose.position == "bench" and purpose.species in active:
                purpose_ok = False
                break

        if not preserve_ok:
            preserve_failure += outcome.weight
        if not resources_ok:
            resource_failure += outcome.weight
        if not conditions_ok:
            condition_failure += outcome.weight
        if not timing_ok:
            timing_failure += outcome.weight
        if not failures_ok:
            declared_failure += outcome.weight
        if not losses_ok:
            unacceptable_loss += outcome.weight
        if not active_pair_ok:
            active_pair_failure += outcome.weight
        if not safe_entry_ok:
            safe_entry_failure += outcome.weight
        if not purpose_ok:
            purpose_failure += outcome.weight

        if (
            preserve_ok
            and resources_ok
            and conditions_ok
            and timing_ok
            and failures_ok
            and losses_ok
            and active_pair_ok
            and safe_entry_ok
            and purpose_ok
        ):
            viable_weight += outcome.weight
        else:
            failed_worlds += 1

    def mass(value: float) -> float:
        return value / total_weight

    coverage = mass(viable_weight)
    robust = coverage >= robust_threshold
    reasons = [
        f"viable across {coverage:.1%} posterior mass",
        f"{failed_worlds} of {len(outcomes)} belief world(s) fail at least one requirement",
    ]
    if mass(preserve_failure):
        reasons.append(
            f"preserve failures cover {mass(preserve_failure):.1%} posterior mass"
        )
    if mass(resource_failure):
        reasons.append(
            f"required-resource failures cover {mass(resource_failure):.1%} posterior mass"
        )
    if mass(condition_failure):
        reasons.append(
            f"desired-board failures cover {mass(condition_failure):.1%} posterior mass"
        )
    if mass(timing_failure):
        reasons.append(
            f"timing failures cover {mass(timing_failure):.1%} posterior mass"
        )
    if mass(declared_failure):
        reasons.append(
            f"declared failure conditions occur in {mass(declared_failure):.1%} posterior mass"
        )
    if mass(unacceptable_loss):
        reasons.append(
            f"unacceptable losses occur in {mass(unacceptable_loss):.1%} posterior mass"
        )
    if mass(active_pair_failure):
        reasons.append(
            f"active-pair failures cover {mass(active_pair_failure):.1%} posterior mass"
        )
    if mass(safe_entry_failure):
        reasons.append(
            f"safe-entry failures cover {mass(safe_entry_failure):.1%} posterior mass"
        )
    if mass(purpose_failure):
        reasons.append(
            f"resource-purpose failures cover {mass(purpose_failure):.1%} posterior mass"
        )

    return StrategicPlanEvaluation(
        plan=plan,
        viable_belief_mass=coverage,
        robust=robust,
        failed_worlds=failed_worlds,
        preserve_failure_mass=mass(preserve_failure),
        required_resource_failure_mass=mass(resource_failure),
        condition_failure_mass=mass(condition_failure),
        timing_failure_mass=mass(timing_failure),
        declared_failure_mass=mass(declared_failure),
        unacceptable_loss_mass=mass(unacceptable_loss),
        active_pair_failure_mass=mass(active_pair_failure),
        safe_entry_failure_mass=mass(safe_entry_failure),
        purpose_failure_mass=mass(purpose_failure),
        reasons=tuple(reasons),
    )

def rank_strategic_plans(
    plans: Iterable[StrategicPlan],
    *,
    outcomes_by_plan: dict[str, Iterable[PlanWorldOutcome]],
    robust_threshold: float = 0.8,
) -> StrategicPlanRanking:
    """Rank inspectable plans by robustness, then belief coverage.

    This ranking is intentionally disconnected from live move choice. It says which
    strategic objective is best supported by supplied hypothetical outcomes; exact search
    still owns the concrete tactical decision.
    """
    plans = tuple(plans)
    if not plans:
        raise ValueError("at least one strategic plan is required")

    evaluations = []
    for plan in plans:
        outcomes = outcomes_by_plan.get(plan.name)
        if outcomes is None:
            raise ValueError(f"missing outcomes for strategic plan {plan.name}")
        evaluations.append(
            evaluate_strategic_plan(
                plan,
                outcomes=outcomes,
                robust_threshold=robust_threshold,
            )
        )

    ranking = tuple(
        sorted(
            evaluations,
            key=lambda evaluation: (
                -int(evaluation.robust),
                -evaluation.viable_belief_mass,
                evaluation.preserve_failure_mass,
                evaluation.required_resource_failure_mass,
                evaluation.active_pair_failure_mass,
                evaluation.safe_entry_failure_mass,
                evaluation.purpose_failure_mass,
                evaluation.declared_failure_mass,
                evaluation.unacceptable_loss_mass,
                evaluation.plan.name,
            ),
        )
    )
    return StrategicPlanRanking(ranking=ranking)


def format_strategic_plan_ranking(ranking: StrategicPlanRanking) -> str:
    """Render strategic plan evidence without implying a concrete move recommendation."""
    lines = [
        "Strategic plan ranking:",
        "  Scope: read-only objectives ranked across hypothetical public-belief outcomes; "
        "live move selection is unchanged.",
    ]
    for index, evaluation in enumerate(ranking.ranking, start=1):
        marker = " [TOP PLAN]" if index == 1 else ""
        lines.append(
            f"  {index}.{marker} {evaluation.plan.name} | "
            f"coverage {evaluation.viable_belief_mass:.1%} | "
            f"{'robust' if evaluation.robust else 'fragile'}"
        )
        lines.append(f"     objective: {evaluation.plan.objective}")
        if evaluation.plan.preserve:
            lines.append("     preserve: " + ", ".join(evaluation.plan.preserve))
        if evaluation.plan.acceptable_losses:
            lines.append(
                "     acceptable losses: " + ", ".join(evaluation.plan.acceptable_losses)
            )
        desired = evaluation.plan.desired_board
        if desired.required_active_pair:
            lines.append(
                "     desired active pair: "
                + " + ".join(desired.required_active_pair)
            )
        if desired.safe_entry_resources:
            lines.append(
                "     safe entry: " + ", ".join(desired.safe_entry_resources)
            )
        if desired.resource_purposes:
            lines.append(
                "     resource purposes: "
                + ", ".join(
                    f"{purpose.species}={purpose.purpose} ({purpose.position})"
                    for purpose in desired.resource_purposes
                )
            )
        lines.append("     " + "; ".join(evaluation.reasons))
    return "\n".join(lines)
