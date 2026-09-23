"""Materialize bounded hidden-information worlds from public opponent beliefs.

The materializer never reads a simulator snapshot. Missing information must come from an
explicit caller-supplied public prior catalog, which keeps the anti-cheat boundary obvious.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any, Mapping, Protocol, Sequence
import warnings

from champions_practice.beliefs import PublicOpponentBelief, PublicPokemonBelief

_STAT_LABELS = {
    "hp": "HP",
    "atk": "Atk",
    "def": "Def",
    "spa": "SpA",
    "spd": "SpD",
    "spe": "Spe",
}


class MissingPublicSetPrior(ValueError):
    """Raised when public information cannot be materialized from the prior catalog."""


@dataclass(frozen=True)
class PublicSetCandidate:
    """One legal-set prior that is independent of the current hidden simulator state."""

    species: str
    item: str | None
    ability: str
    nature: str
    stat_points: tuple[tuple[str, int], ...]
    moves: tuple[str, ...]
    level: int = 50
    label: str = ""
    weight: float = 1.0

    def __post_init__(self) -> None:
        if self.weight <= 0:
            raise ValueError("set candidate weight must be positive")
        if not 1 <= len(self.moves) <= 4:
            raise ValueError("set candidate must contain between one and four moves")
        if len({_id(move) for move in self.moves}) != len(self.moves):
            raise ValueError("set candidate moves must be unique")
        if any(points < 0 for _, points in self.stat_points):
            raise ValueError("stat points must not be negative")

    @property
    def team_text(self) -> str:
        header = self.species
        if self.item:
            header += f" @ {self.item}"
        lines = [
            header,
            f"Ability: {self.ability}",
            f"Level: {self.level}",
        ]
        if self.stat_points:
            stats = " / ".join(
                f"{points} {_STAT_LABELS.get(stat.lower(), stat)}"
                for stat, points in self.stat_points
            )
            lines.append(f"EVs: {stats}")
        lines.append(f"{self.nature} Nature")
        lines.extend(f"- {move}" for move in self.moves)
        return "\n".join(lines)


@dataclass(frozen=True)
class PublicBeliefWorld:
    """A bounded opponent world consistent with public information and public priors."""

    selected_species: tuple[str, ...]
    sets: tuple[PublicSetCandidate, ...]
    weight: float

    @property
    def team_text(self) -> str:
        return "\n\n".join(candidate.team_text for candidate in self.sets) + "\n"

    def set_for_species(self, species: str) -> PublicSetCandidate:
        species_id = _id(species)
        for candidate in self.sets:
            if _id(candidate.species) == species_id:
                return candidate
        raise KeyError(species)


PublicSetPriorCatalog = Mapping[str, Sequence[PublicSetCandidate]]


def preview_choice_for_world(
    belief: PublicOpponentBelief,
    world: PublicBeliefWorld,
) -> str:
    """Return the legal team-preview command implied by one public belief world."""
    active_species = [pokemon.species for pokemon in belief.active]
    if len(active_species) > len(world.selected_species):
        raise ValueError("active roster exceeds selected belief-world roster")

    selected_ids = {_id(species) for species in world.selected_species}
    ordered_species = active_species + [
        pokemon.species
        for pokemon in belief.pokemon
        if _id(pokemon.species) in selected_ids
        and _id(pokemon.species) not in {_id(species) for species in active_species}
    ]
    if len(ordered_species) != len(world.selected_species):
        raise ValueError("belief world does not contain every public active Pokemon")

    preview_slots = {
        _id(pokemon.species): index
        for index, pokemon in enumerate(belief.pokemon, start=1)
    }
    try:
        digits = "".join(str(preview_slots[_id(species)]) for species in ordered_species)
    except KeyError as error:
        raise ValueError("belief world contains species outside the public preview") from error
    return f"team {digits}"


def _id(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _candidate_matches(
    pokemon: PublicPokemonBelief,
    candidate: PublicSetCandidate,
) -> bool:
    if _id(candidate.species) != _id(pokemon.species):
        return False

    candidate_moves = {_id(move) for move in candidate.moves}
    if not {_id(move) for move in pokemon.revealed_moves}.issubset(candidate_moves):
        return False

    if pokemon.revealed_items:
        candidate_item = _id(candidate.item or "")
        if candidate_item not in {_id(item) for item in pokemon.revealed_items}:
            return False

    if pokemon.revealed_abilities:
        candidate_ability = _id(candidate.ability)
        if candidate_ability not in {
            _id(ability) for ability in pokemon.revealed_abilities
        }:
            return False

    return True


def compatible_public_sets(
    pokemon: PublicPokemonBelief,
    priors: PublicSetPriorCatalog,
) -> tuple[PublicSetCandidate, ...]:
    """Return deterministic, weighted set priors compatible with one public belief."""
    options: list[PublicSetCandidate] = []
    species_id = _id(pokemon.species)
    for key, candidates in priors.items():
        if _id(key) != species_id:
            continue
        options.extend(
            candidate
            for candidate in candidates
            if _candidate_matches(pokemon, candidate)
        )

    return tuple(
        sorted(
            options,
            key=lambda candidate: (
                -candidate.weight,
                candidate.label,
                _id(candidate.item or ""),
                _id(candidate.ability),
                tuple(_id(move) for move in candidate.moves),
            ),
        )
    )


def _known_selected(pokemon: PublicPokemonBelief) -> bool:
    return (
        pokemon.active_slot is not None
        or pokemon.seen
        or pokemon.fainted
        or bool(pokemon.revealed_moves)
        or bool(pokemon.revealed_items)
        or bool(pokemon.revealed_abilities)
    )


def _selection_hypotheses(
    belief: PublicOpponentBelief,
    *,
    selected_size: int,
) -> tuple[tuple[str, ...], ...]:
    if selected_size <= 0:
        raise ValueError("selected_size must be positive")
    if selected_size > len(belief.pokemon):
        raise ValueError("selected_size exceeds preview roster size")

    known = [pokemon.species for pokemon in belief.pokemon if _known_selected(pokemon)]
    if len(known) > selected_size:
        raise MissingPublicSetPrior(
            "public observations imply more selected Pokemon than the format allows"
        )

    unknown = [
        pokemon.species for pokemon in belief.pokemon if pokemon.species not in known
    ]
    missing = selected_size - len(known)
    if missing > len(unknown):
        raise MissingPublicSetPrior("not enough unseen preview Pokemon to complete a team")

    selected_sets: list[tuple[str, ...]] = []
    for extra in combinations(unknown, missing):
        selected_ids = {_id(species) for species in (*known, *extra)}
        selected_sets.append(
            tuple(
                pokemon.species
                for pokemon in belief.pokemon
                if _id(pokemon.species) in selected_ids
            )
        )
    return tuple(selected_sets)


def _world_signature(world: PublicBeliefWorld) -> tuple:
    return (
        tuple(_id(species) for species in world.selected_species),
        tuple(
            (
                _id(candidate.species),
                candidate.label,
                _id(candidate.item or ""),
                _id(candidate.ability),
                tuple(_id(move) for move in candidate.moves),
            )
            for candidate in world.sets
        ),
    )


def materialize_public_belief_worlds(
    belief: PublicOpponentBelief,
    priors: PublicSetPriorCatalog,
    *,
    limit: int = 16,
    selected_size: int = 4,
) -> tuple[PublicBeliefWorld, ...]:
    """Build weighted opponent worlds without consulting any private battle state.

    All six preview species receive a set so the result can be serialized as normal
    Showdown team text. Set variation is explored only for the hypothesized selected
    Pokemon; unseen/unselected species use their highest-weight compatible prior to avoid
    wasting the world budget on information that cannot affect the current battle.
    """
    if limit <= 0:
        raise ValueError("world limit must be positive")

    options_by_species: dict[str, tuple[PublicSetCandidate, ...]] = {}
    for pokemon in belief.pokemon:
        options = compatible_public_sets(pokemon, priors)
        if not options:
            raise MissingPublicSetPrior(
                f"no public set prior matches revealed information for {pokemon.species}"
            )
        options_by_species[_id(pokemon.species)] = options

    selections = _selection_hypotheses(belief, selected_size=selected_size)
    worlds_by_selection: list[list[PublicBeliefWorld]] = []

    for selected_species in selections:
        selected_ids = {_id(species) for species in selected_species}
        baseline = [
            options_by_species[_id(pokemon.species)][0] for pokemon in belief.pokemon
        ]

        # Beam-search the Cartesian set-prior product so a large public prior catalog
        # cannot explode before the caller's world limit is applied.
        partials: list[tuple[dict[int, PublicSetCandidate], float]] = [({}, 1.0)]
        for index, pokemon in enumerate(belief.pokemon):
            if _id(pokemon.species) not in selected_ids:
                continue
            expanded: list[tuple[dict[int, PublicSetCandidate], float]] = []
            options = options_by_species[_id(pokemon.species)]
            option_weight = sum(candidate.weight for candidate in options)
            for assigned, weight in partials:
                for candidate in options:
                    next_assigned = dict(assigned)
                    next_assigned[index] = candidate
                    expanded.append(
                        (next_assigned, weight * candidate.weight / option_weight)
                    )
            expanded.sort(
                key=lambda entry: (
                    -entry[1],
                    tuple(
                        (index, candidate.label, _id(candidate.item or ""))
                        for index, candidate in sorted(entry[0].items())
                    ),
                )
            )
            partials = expanded[:limit]

        selection_worlds: list[PublicBeliefWorld] = []
        for assigned, weight in partials:
            sets = baseline.copy()
            for index, candidate in assigned.items():
                sets[index] = candidate
            selection_worlds.append(
                PublicBeliefWorld(
                    selected_species=selected_species,
                    sets=tuple(sets),
                    weight=weight,
                )
            )
        unique_selection: dict[tuple, PublicBeliefWorld] = {}
        for world in selection_worlds:
            signature = _world_signature(world)
            current = unique_selection.get(signature)
            if current is None or world.weight > current.weight:
                unique_selection[signature] = world
        worlds_by_selection.append(
            sorted(
                unique_selection.values(),
                key=lambda world: (-world.weight, _world_signature(world)),
            )
        )

    # Preserve team-selection coverage before spending extra world budget on additional
    # set variants. Otherwise a species with many catalog entries can crowd entire
    # bring-four hypotheses out of the bounded search.
    retained: list[PublicBeliefWorld] = []
    depth = 0
    while len(retained) < limit:
        added = False
        for selection_worlds in worlds_by_selection:
            if depth >= len(selection_worlds):
                continue
            retained.append(selection_worlds[depth])
            added = True
            if len(retained) >= limit:
                break
        if not added:
            break
        depth += 1

    retained_by_selection: dict[tuple[str, ...], list[PublicBeliefWorld]] = {}
    for world in retained:
        key = tuple(_id(species) for species in world.selected_species)
        retained_by_selection.setdefault(key, []).append(world)

    selection_weight = 1.0 / max(1, len(retained_by_selection))
    normalized: list[PublicBeliefWorld] = []
    for selection_worlds in retained_by_selection.values():
        retained_weight = sum(world.weight for world in selection_worlds)
        for world in selection_worlds:
            normalized.append(
                PublicBeliefWorld(
                    selected_species=world.selected_species,
                    sets=world.sets,
                    weight=selection_weight * world.weight / retained_weight,
                )
            )

    return tuple(
        sorted(
            normalized,
            key=lambda world: (-world.weight, _world_signature(world)),
        )
    )


class MidgameWorldWorker(Protocol):
    def create_state(self, *, battle_format: str, p1_team: str, p2_team: str,
                     p1_preview: str | None = None, p2_preview: str | None = None,
                     seed: str | None = None, **kwargs: Any) -> dict[str, Any]: ...
    def branch_many(self, *, state: dict[str, Any],
                    branches: list[dict[str, Any]]) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class PublicTurnChoice:
    """One fully public resolved turn used to advance every belief world."""
    p1_choice: str
    p2_choice: str
    rng_seed: str | None = None


@dataclass(frozen=True)
class ReconstructedBeliefWorld:
    world: PublicBeliefWorld
    state: dict[str, Any]


def reconstruct_midgame_belief_worlds(
    worker: MidgameWorldWorker,
    *,
    battle_format: str,
    belief: PublicOpponentBelief,
    preview_belief: PublicOpponentBelief,
    worlds: tuple[PublicBeliefWorld, ...],
    ai_team: str,
    ai_preview: str,
    public_turns: tuple[PublicTurnChoice, ...],
    opponent_side: str = "p1",
    seed: str | None = None,
) -> tuple[ReconstructedBeliefWorld, ...]:
    """Legacy replay reconstruction for tests/debugging, not live decisions.

    Live battle decisions must carry sequential particles through BeliefBattleController.
    This helper replays complete public command history and may accept an exact seed, so
    using it in the live opponent would reintroduce the reconstruction path that the
    persistent controller replaced.
    """
    warnings.warn(
        "reconstruct_midgame_belief_worlds() is legacy debug/test-only; "
        "use BeliefBattleController for live decisions",
        DeprecationWarning,
        stacklevel=2,
    )
    if opponent_side not in {"p1", "p2"}:
        raise ValueError("opponent_side must be p1 or p2")
    reconstructed = []
    for world in worlds:
        opponent_preview = preview_choice_for_world(preview_belief, world)
        if opponent_side == "p1":
            state = worker.create_state(
                battle_format=battle_format, p1_team=world.team_text, p2_team=ai_team,
                p1_preview=opponent_preview, p2_preview=ai_preview, seed=seed,
            )
        else:
            state = worker.create_state(
                battle_format=battle_format, p1_team=ai_team, p2_team=world.team_text,
                p1_preview=ai_preview, p2_preview=opponent_preview, seed=seed,
            )
        for turn in public_turns:
            branch = {"p1_choice": turn.p1_choice, "p2_choice": turn.p2_choice,
                      "include_state": True}
            if turn.rng_seed is not None:
                branch["rng_seed"] = turn.rng_seed
            resolved = worker.branch_many(state=state, branches=[branch])
            if len(resolved) != 1 or not isinstance(resolved[0].get("state"), dict):
                raise RuntimeError("midgame reconstruction did not return an exact state")
            state = resolved[0]["state"]
        reconstructed.append(ReconstructedBeliefWorld(world=world, state=state))
    return tuple(reconstructed)
