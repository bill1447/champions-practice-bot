"""Opponent beliefs derived exclusively from the player-visible battle view."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any, Literal

BeliefActionKind = Literal["revealed_move", "unknown_move", "switch", "pass"]

_ALLOWED_OPPONENT_KEYS = {"name", "preview_species", "active", "revealed"}
_ALLOWED_ACTIVE_KEYS = {
    "species",
    "base_species",
    "hp_percent",
    "fainted",
    "status",
    "boosts",
}
_ALLOWED_REVEALED_KEYS = {"species", "moves", "items", "abilities", "fainted"}


class PublicInformationLeak(ValueError):
    """Raised when the supposedly public view contains private simulator fields."""


@dataclass(frozen=True)
class PublicPokemonBelief:
    species: str
    active_slot: int | None
    active_species: str | None
    hp_percent: float | None
    fainted: bool
    status: str | None
    boosts: tuple[tuple[str, int], ...]
    revealed_moves: tuple[str, ...]
    revealed_items: tuple[str, ...]
    revealed_abilities: tuple[str, ...]


@dataclass(frozen=True)
class PublicOpponentBelief:
    turn: int
    phase: str
    pokemon: tuple[PublicPokemonBelief, ...]

    @property
    def active(self) -> tuple[PublicPokemonBelief, ...]:
        return tuple(
            sorted(
                (pokemon for pokemon in self.pokemon if pokemon.active_slot is not None),
                key=lambda pokemon: pokemon.active_slot or 0,
            )
        )

    @property
    def possible_bench_species(self) -> tuple[str, ...]:
        return tuple(
            pokemon.species
            for pokemon in self.pokemon
            if pokemon.active_slot is None and not pokemon.fainted
        )


@dataclass(frozen=True)
class BeliefAction:
    slot: int
    actor_species: str
    kind: BeliefActionKind
    detail: str | None = None


@dataclass(frozen=True)
class PublicResponseHypothesis:
    actions: tuple[BeliefAction, ...]


def _id(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _reject_private_fields(
    value: dict[str, Any],
    allowed: set[str],
    location: str,
) -> None:
    unexpected = set(value).difference(allowed)
    if unexpected:
        raise PublicInformationLeak(
            f"{location} contains non-public fields: {sorted(unexpected)}"
        )


def build_public_opponent_belief(view: dict[str, Any]) -> PublicOpponentBelief:
    """Freeze a whitelist-only opponent belief from one player-visible view."""
    opponent = view.get("opponent")
    if not isinstance(opponent, dict):
        raise ValueError("view is missing opponent data")
    _reject_private_fields(opponent, _ALLOWED_OPPONENT_KEYS, "opponent view")

    preview_species = opponent.get("preview_species")
    active = opponent.get("active")
    revealed = opponent.get("revealed")
    if not isinstance(preview_species, list) or not all(
        isinstance(species, str) for species in preview_species
    ):
        raise ValueError("opponent preview species are invalid")
    if not isinstance(active, list):
        raise ValueError("opponent active slots are invalid")
    if not isinstance(revealed, list):
        raise ValueError("opponent revealed observations are invalid")

    active_by_species: dict[str, tuple[int, dict[str, Any]]] = {}
    for slot, pokemon in enumerate(active, start=1):
        if pokemon is None:
            continue
        if not isinstance(pokemon, dict):
            raise ValueError("opponent active slot is invalid")
        _reject_private_fields(pokemon, _ALLOWED_ACTIVE_KEYS, "opponent active slot")
        base_species = pokemon.get("base_species")
        if not isinstance(base_species, str):
            raise ValueError("opponent active slot is missing base species")
        active_by_species[_id(base_species)] = (slot, pokemon)

    revealed_by_species: dict[str, dict[str, Any]] = {}
    for observation in revealed:
        if not isinstance(observation, dict):
            raise ValueError("opponent revealed observation is invalid")
        _reject_private_fields(
            observation,
            _ALLOWED_REVEALED_KEYS,
            "opponent revealed observation",
        )
        species = observation.get("species")
        if not isinstance(species, str):
            raise ValueError("opponent revealed observation is missing species")
        revealed_by_species[_id(species)] = observation

    pokemon_beliefs: list[PublicPokemonBelief] = []
    for species in preview_species:
        species_id = _id(species)
        active_entry = active_by_species.get(species_id)
        active_slot, active_pokemon = active_entry or (None, {})
        observation = revealed_by_species.get(species_id, {})
        boosts = active_pokemon.get("boosts", {})
        if not isinstance(boosts, dict):
            raise ValueError("opponent boosts are invalid")

        pokemon_beliefs.append(
            PublicPokemonBelief(
                species=species,
                active_slot=active_slot,
                active_species=active_pokemon.get("species"),
                hp_percent=(
                    float(active_pokemon["hp_percent"])
                    if "hp_percent" in active_pokemon
                    else None
                ),
                fainted=bool(
                    active_pokemon.get("fainted", observation.get("fainted", False))
                ),
                status=active_pokemon.get("status"),
                boosts=tuple(sorted((str(stat), int(stage)) for stat, stage in boosts.items())),
                revealed_moves=tuple(sorted(str(move) for move in observation.get("moves", []))),
                revealed_items=tuple(sorted(str(item) for item in observation.get("items", []))),
                revealed_abilities=tuple(
                    sorted(str(ability) for ability in observation.get("abilities", []))
                ),
            )
        )

    return PublicOpponentBelief(
        turn=int(view.get("turn", 0)),
        phase=str(view.get("phase", "")),
        pokemon=tuple(pokemon_beliefs),
    )


def _slot_actions(
    pokemon: PublicPokemonBelief,
    possible_switches: tuple[str, ...],
) -> list[BeliefAction]:
    if pokemon.active_slot is None:
        return []

    actions: list[BeliefAction] = []
    if not pokemon.fainted:
        actions.extend(
            BeliefAction(
                slot=pokemon.active_slot,
                actor_species=pokemon.species,
                kind="revealed_move",
                detail=move,
            )
            for move in pokemon.revealed_moves
        )
        if len(pokemon.revealed_moves) < 4:
            actions.append(
                BeliefAction(
                    slot=pokemon.active_slot,
                    actor_species=pokemon.species,
                    kind="unknown_move",
                )
            )

    actions.extend(
        BeliefAction(
            slot=pokemon.active_slot,
            actor_species=pokemon.species,
            kind="switch",
            detail=species,
        )
        for species in possible_switches
    )
    if not actions:
        actions.append(
            BeliefAction(
                slot=pokemon.active_slot,
                actor_species=pokemon.species,
                kind="pass",
            )
        )
    return actions


def public_response_hypotheses(
    belief: PublicOpponentBelief,
    *,
    limit: int = 32,
) -> tuple[PublicResponseHypothesis, ...]:
    """Return bounded response families without inventing a private opponent set."""
    if limit <= 0:
        raise ValueError("hypothesis limit must be positive")

    active = belief.active
    if not active:
        return ()
    per_slot = [
        _slot_actions(pokemon, belief.possible_bench_species) for pokemon in active
    ]

    hypotheses: list[PublicResponseHypothesis] = []
    for joint_actions in product(*per_slot):
        switched_species = [
            action.detail for action in joint_actions if action.kind == "switch"
        ]
        if len(switched_species) != len(set(switched_species)):
            continue
        hypotheses.append(PublicResponseHypothesis(actions=tuple(joint_actions)))
        if len(hypotheses) >= limit:
            break
    return tuple(hypotheses)
