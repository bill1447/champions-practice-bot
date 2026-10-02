"""Mechanics-authoritative recovery contracts and replay validation.

This module is intentionally not integrated into the live decision controller yet.
Static hidden dimensions are proposed against trusted pre-opening belief states.
They have no authority until the pinned Showdown runtime rebuilds the post-preview
root, mechanically reproduces the retained public prefix through the current
checkpoint, and then reproduces the recovery suffix.

The live session's exact hidden state is never an input to this API.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Protocol

from champions_practice.observation_beliefs import (
    BeliefParticle,
    condition_particles,
    identity_member_lineage,
    particle_member_lineage,
    public_observation_signature,
)

SideId = Literal["p1", "p2"]

CHAMPIONS_STAT_POINT_CAP = 32
CHAMPIONS_TOTAL_STAT_POINTS = 66
_RECOVERY_STATS = ("hp", "atk", "def", "spa", "spd", "spe")
_RECOVERY_NON_HP_STATS = ("atk", "def", "spa", "spd", "spe")
_DEFAULT_STAT_POINT_GRID = (0, 16, 32)


@dataclass(frozen=True)
class RecoveryObservation:
    """One already-resolved public transition that a candidate must replay."""

    ai_choice: str
    previous_public_view: dict[str, Any] | None
    public_view: dict[str, Any]


@dataclass(frozen=True)
class RecoveryOpeningAuthority:
    """Trusted battle-creation inputs and preview lineage for one turn-one root."""

    world_id: str
    history_id: str
    battle_format: str
    p1_team: str
    p2_team: str
    p1_name: str
    p2_name: str
    seed: str
    p1_preview_choice: str
    p2_preview_choice: str
    p1_root_to_input: tuple[int, ...]
    p2_root_to_input: tuple[int, ...]


@dataclass(frozen=True)
class RecoveryRequest:
    """Trusted static-history root, current checkpoint, and retained suffix evidence.

    Static hidden dimensions such as stat points are lifelong. A proposal therefore
    cannot gain authority by mutating a post-preview or midgame state. Each retained
    root has trusted battle-creation inputs plus exact preview choices and member
    lineage. Showdown must construct a fresh battle, apply the typed proposal before
    initialization, and rebuild the turn-one root before authority_observations can
    replay through checkpoint_public_view.
    """

    authority_root_particles: tuple[BeliefParticle, ...]
    opening_authorities: tuple[RecoveryOpeningAuthority, ...]
    authority_root_public_view: dict[str, Any]
    authority_observations: tuple[RecoveryObservation, ...]
    authority_history_complete: bool
    checkpoint_particles: tuple[BeliefParticle, ...]
    checkpoint_public_view: dict[str, Any]
    observations: tuple[RecoveryObservation, ...]
    ai_side: SideId
    previews: dict[str, list[str]] | None = None
    _authority_fingerprint: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_authority_fingerprint",
            _recovery_request_fingerprint(self),
        )


def _stable_json_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _recovery_request_fingerprint(request: "RecoveryRequest") -> str:
    payload = {
        "authority_root_particles": [
            {
                "state": particle.state,
                "weight": particle.weight,
                "world_id": particle.world_id,
                "history_id": particle.history_id,
                "p1_member_lineage": particle.p1_member_lineage,
                "p2_member_lineage": particle.p2_member_lineage,
            }
            for particle in request.authority_root_particles
        ],
        "opening_authorities": [
            {
                "world_id": authority.world_id,
                "history_id": authority.history_id,
                "battle_format": authority.battle_format,
                "p1_team": authority.p1_team,
                "p2_team": authority.p2_team,
                "p1_name": authority.p1_name,
                "p2_name": authority.p2_name,
                "seed": authority.seed,
                "p1_preview_choice": authority.p1_preview_choice,
                "p2_preview_choice": authority.p2_preview_choice,
                "p1_root_to_input": authority.p1_root_to_input,
                "p2_root_to_input": authority.p2_root_to_input,
            }
            for authority in request.opening_authorities
        ],
        "authority_root_public_view": request.authority_root_public_view,
        "authority_history_complete": request.authority_history_complete,
        "authority_observations": [
            {
                "ai_choice": observation.ai_choice,
                "previous_public_view": observation.previous_public_view,
                "public_view": observation.public_view,
            }
            for observation in request.authority_observations
        ],
        "checkpoint_particles": [
            {
                "state": particle.state,
                "weight": particle.weight,
                "world_id": particle.world_id,
                "history_id": particle.history_id,
                "p1_member_lineage": particle.p1_member_lineage,
                "p2_member_lineage": particle.p2_member_lineage,
            }
            for particle in request.checkpoint_particles
        ],
        "checkpoint_public_view": request.checkpoint_public_view,
        "observations": [
            {
                "ai_choice": observation.ai_choice,
                "previous_public_view": observation.previous_public_view,
                "public_view": observation.public_view,
            }
            for observation in request.observations
        ],
        "ai_side": request.ai_side,
        "previews": request.previews,
    }
    return _stable_json_hash(payload)


@dataclass(frozen=True)
class OpponentStatProposal:
    """One bounded stat-point alternative for a publicly seen opponent."""

    proposal_id: str
    parent_particle_index: int
    pokemon_index: int
    root_pokemon_index: int
    species: str
    stat_points: tuple[tuple[str, int], ...]
    changed_hidden_dimensions: tuple[str, ...]

    @property
    def stat_point_dict(self) -> dict[str, int]:
        return dict(self.stat_points)


@dataclass(frozen=True)
class RecoveryMaterializationFailure:
    proposal: OpponentStatProposal
    reason: str


@dataclass(frozen=True)
class RecoveryMaterializationReport:
    candidates: tuple["_MaterializedStatCandidate", ...]
    failures: tuple[RecoveryMaterializationFailure, ...]


class BoundedOpponentStatProposalGenerator:
    """Generate deterministic, bounded non-HP Champions stat-point alternatives.

    The generator only inspects last-good hypothetical particles and the sanitized
    public checkpoint. It never receives a live worker or session identifier.
    HP stat points are intentionally frozen until public-HP interval recovery is
    implemented; changing max HP without that mapping would invent exact HP state.
    """

    def __init__(
        self,
        *,
        max_proposals: int = 64,
        stat_point_grid: tuple[int, ...] = _DEFAULT_STAT_POINT_GRID,
    ) -> None:
        if max_proposals <= 0:
            raise ValueError("max_proposals must be positive")
        if not stat_point_grid:
            raise ValueError("stat_point_grid must not be empty")
        if any(
            not isinstance(value, int)
            or value < 0
            or value > CHAMPIONS_STAT_POINT_CAP
            for value in stat_point_grid
        ):
            raise ValueError("stat-point grid values must be integers from 0 to 32")
        self.max_proposals = max_proposals
        self.stat_point_grid = tuple(sorted(set(stat_point_grid)))

    def generate(
        self,
        request: RecoveryRequest,
    ) -> tuple[OpponentStatProposal, ...]:
        seen_species = _publicly_seen_opponent_species(
            request.checkpoint_public_view
        )
        if not seen_species:
            return ()

        opponent_side_index = 1 if request.ai_side == "p1" else 0
        opponent_side = "p2" if request.ai_side == "p1" else "p1"
        ranked: list[
            tuple[int, int, int, int, tuple[int, ...], OpponentStatProposal]
        ] = []

        for parent_index, particle in enumerate(request.checkpoint_particles):
            sides = particle.state.get("sides")
            if not isinstance(sides, list) or len(sides) <= opponent_side_index:
                raise ValueError("checkpoint particle is missing opponent side data")
            pokemon = sides[opponent_side_index].get("pokemon")
            if not isinstance(pokemon, list):
                raise ValueError("checkpoint particle is missing opponent Pokemon")

            member_lineage = particle_member_lineage(
                particle,
                opponent_side,
                require_tracked=True,
            )
            for pokemon_index, mon in enumerate(pokemon):
                if not isinstance(mon, dict):
                    continue
                root_pokemon_index = member_lineage[pokemon_index]
                set_data = mon.get("set")
                if not isinstance(set_data, dict):
                    continue
                species = str(set_data.get("species") or set_data.get("name") or "")
                if _id(species) not in seen_species:
                    continue
                current = _stat_points_from_set(set_data)
                variants = _bounded_non_hp_stat_variants(
                    current,
                    grid=self.stat_point_grid,
                )
                for variant in variants:
                    changed = tuple(
                        stat
                        for stat in _RECOVERY_NON_HP_STATS
                        if variant[stat] != current[stat]
                    )
                    if not changed:
                        continue
                    distance = sum(
                        abs(variant[stat] - current[stat])
                        for stat in _RECOVERY_NON_HP_STATS
                    )
                    signature = tuple(variant[stat] for stat in _RECOVERY_STATS)
                    proposal = OpponentStatProposal(
                        proposal_id=(
                            f"p{parent_index}-r{root_pokemon_index}-"
                            f"c{pokemon_index}-"
                            + "-".join(
                                f"{stat}{variant[stat]}" for stat in _RECOVERY_STATS
                            )
                        ),
                        parent_particle_index=parent_index,
                        pokemon_index=pokemon_index,
                        root_pokemon_index=root_pokemon_index,
                        species=species,
                        stat_points=tuple(
                            (stat, variant[stat]) for stat in _RECOVERY_STATS
                        ),
                        changed_hidden_dimensions=tuple(
                            "opponent."
                            f"member{root_pokemon_index}."
                            f"{_id(species)}.stat_points.{stat}"
                            for stat in changed
                        ),
                    )
                    ranked.append(
                        (
                            distance,
                            parent_index,
                            root_pokemon_index,
                            pokemon_index,
                            signature,
                            proposal,
                        )
                    )

        ranked.sort(key=lambda item: item[:-1])
        return tuple(item[-1] for item in ranked[: self.max_proposals])


def _id(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _publicly_seen_opponent_species(view: dict[str, Any]) -> set[str]:
    opponent = view.get("opponent")
    if not isinstance(opponent, dict):
        return set()
    revealed = opponent.get("revealed")
    if not isinstance(revealed, list):
        return set()
    return {
        _id(str(entry.get("species", "")))
        for entry in revealed
        if isinstance(entry, dict) and entry.get("seen") is True
    } - {""}


def _stat_points_from_set(set_data: dict[str, Any]) -> dict[str, int]:
    raw = set_data.get("evs")
    if not isinstance(raw, dict):
        raw = {}
    points: dict[str, int] = {}
    for stat in _RECOVERY_STATS:
        value = raw.get(stat, 0)
        if not isinstance(value, int):
            raise ValueError(f"checkpoint {stat} stat points are not an integer")
        if value < 0 or value > CHAMPIONS_STAT_POINT_CAP:
            raise ValueError(f"checkpoint {stat} stat points are outside 0-32")
        points[stat] = value
    if sum(points.values()) > CHAMPIONS_TOTAL_STAT_POINTS:
        raise ValueError("checkpoint stat points exceed the Champions total cap")
    return points


def _bounded_non_hp_stat_variants(
    current: dict[str, int],
    *,
    grid: tuple[int, ...],
) -> tuple[dict[str, int], ...]:
    variants: dict[tuple[int, ...], dict[str, int]] = {}

    def add(candidate: dict[str, int]) -> None:
        if candidate["hp"] != current["hp"]:
            return
        if any(
            candidate[stat] < 0 or candidate[stat] > CHAMPIONS_STAT_POINT_CAP
            for stat in _RECOVERY_STATS
        ):
            return
        if sum(candidate.values()) > CHAMPIONS_TOTAL_STAT_POINTS:
            return
        signature = tuple(candidate[stat] for stat in _RECOVERY_STATS)
        if signature != tuple(current[stat] for stat in _RECOVERY_STATS):
            variants[signature] = candidate

    # Direct lower/equal-budget alternatives allow recovery from an overly high
    # parent hypothesis without inventing how freed points must have been spent.
    for stat in _RECOVERY_NON_HP_STATS:
        for value in grid:
            candidate = dict(current)
            candidate[stat] = value
            add(candidate)

    # Pairwise transfers preserve the total budget and can recover a missing
    # investment even when the parent already spends the full 66 points.
    for donor in _RECOVERY_NON_HP_STATS:
        for target in _RECOVERY_NON_HP_STATS:
            if donor == target:
                continue
            transferable = min(
                current[donor],
                CHAMPIONS_STAT_POINT_CAP - current[target],
            )
            if transferable <= 0:
                continue
            candidate = dict(current)
            candidate[donor] -= transferable
            candidate[target] += transferable
            add(candidate)

    return tuple(variants[key] for key in sorted(variants))


@dataclass(frozen=True)
class _MaterializedStatCandidate:
    """Internal root-state result of trusted Showdown stat materialization."""

    candidate_id: str
    proposal_id: str
    parent_particle_index: int
    authority_root_particle_index: int
    root_pokemon_index: int
    input_pokemon_index: int
    particle: BeliefParticle
    source: str
    changed_hidden_dimensions: tuple[str, ...] = ()


class RecoveryStatMaterializationWorker(Protocol):
    """Hypothetical-only capability for simulator-coherent stat rematerialization."""

    def materialize_recovery_stat_proposals(
        self,
        *,
        state: dict[str, Any],
        side: str,
        proposals: list[dict[str, Any]],
    ) -> list[dict[str, Any]]: ...

    def materialize_recovery_opening_stat_proposals(
        self,
        *,
        battle_format: str,
        p1_team: str,
        p2_team: str,
        p1_name: str,
        p2_name: str,
        seed: str,
        side: str,
        p1_preview: str,
        p2_preview: str,
        proposals: list[dict[str, Any]],
    ) -> list[dict[str, Any]]: ...


class RecoveryStatValidationWorker(
    RecoveryStatMaterializationWorker,
    Protocol,
):
    """Typed static-stat recovery needs materialization plus hypothetical replay."""

    def validate_recovery_opening_authority(
        self,
        *,
        battle_format: str,
        p1_team: str,
        p2_team: str,
        p1_name: str,
        p2_name: str,
        seed: str,
        root_state: dict[str, Any],
        p1_preview: str,
        p2_preview: str,
        p1_root_to_input: tuple[int, ...],
        p2_root_to_input: tuple[int, ...],
    ) -> bool: ...

    def validate_recovery_opening_stat_candidate(
        self,
        *,
        battle_format: str,
        p1_team: str,
        p2_team: str,
        p1_name: str,
        p2_name: str,
        seed: str,
        candidate_state: dict[str, Any],
        side: str,
        pokemon_index: int,
        stat_points: dict[str, int],
        p1_preview: str,
        p2_preview: str,
    ) -> bool: ...

    def validate_recovery_stat_candidate(
        self,
        *,
        state: dict[str, Any],
        side: str,
        pokemon_index: int,
        stat_points: dict[str, int],
    ) -> bool: ...

    def state_view(
        self,
        *,
        state: dict[str, Any],
        side: str,
        previews: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]: ...

    def validate_choices(
        self,
        *,
        state: dict[str, Any],
        side: str,
        candidates: list[str],
    ) -> list[str]: ...

    def legal_choices(
        self,
        *,
        state: dict[str, Any],
        side: str,
    ) -> list[str]: ...

    def branch_many(
        self,
        *,
        state: dict[str, Any],
        branches: list[dict[str, Any]],
    ) -> list[dict[str, Any]]: ...

def _opponent_side_index(ai_side: SideId) -> int:
    return 1 if ai_side == "p1" else 0


def _opening_authority(
    request: RecoveryRequest,
    root_index: int,
) -> RecoveryOpeningAuthority:
    if not 0 <= root_index < len(request.opening_authorities):
        raise ValueError("recovery root has no pre-opening authority")
    authority = request.opening_authorities[root_index]
    root = request.authority_root_particles[root_index]
    if (
        authority.world_id != root.world_id
        or authority.history_id != root.history_id
    ):
        raise ValueError("opening authority lineage does not match root")
    return authority


def _preopening_target_index(
    request: RecoveryRequest,
    *,
    root_index: int,
    root_pokemon_index: int,
) -> int:
    authority = _opening_authority(request, root_index)
    mapping = (
        authority.p2_root_to_input
        if request.ai_side == "p1"
        else authority.p1_root_to_input
    )
    if not 0 <= root_pokemon_index < len(mapping):
        raise ValueError("recovery root target has no opening input member lineage")
    index = mapping[root_pokemon_index]
    if index < 0:
        raise ValueError("recovery root target has invalid opening input member lineage")
    return index


def _target_pokemon(
    state: dict[str, Any],
    *,
    ai_side: SideId,
    pokemon_index: int,
) -> dict[str, Any]:
    sides = state.get("sides")
    side_index = _opponent_side_index(ai_side)
    if not isinstance(sides, list) or len(sides) <= side_index:
        raise ValueError("recovery state is missing opponent side data")
    side = sides[side_index]
    if not isinstance(side, dict):
        raise ValueError("recovery opponent side is invalid")
    pokemon = side.get("pokemon")
    if not isinstance(pokemon, list) or not 0 <= pokemon_index < len(pokemon):
        raise ValueError("recovery proposal targets an invalid opponent Pokemon")
    target = pokemon[pokemon_index]
    if not isinstance(target, dict):
        raise ValueError("recovery target Pokemon is invalid")
    return target


def _target_set(
    particle: BeliefParticle,
    *,
    ai_side: SideId,
    pokemon_index: int,
) -> dict[str, Any]:
    target = _target_pokemon(
        particle.state,
        ai_side=ai_side,
        pokemon_index=pokemon_index,
    )
    set_data = target.get("set")
    if not isinstance(set_data, dict):
        raise ValueError("recovery target Pokemon is missing set data")
    return set_data


def _matching_authority_roots(
    request: RecoveryRequest,
    proposal: OpponentStatProposal,
) -> tuple[tuple[int, BeliefParticle], ...]:
    parent = request.checkpoint_particles[proposal.parent_particle_index]
    if not parent.world_id:
        raise ValueError(
            f"stat proposal {proposal.proposal_id!r} parent has no world lineage"
        )
    opponent_side = "p2" if request.ai_side == "p1" else "p1"
    parent_lineage = particle_member_lineage(
        parent,
        opponent_side,
        require_tracked=True,
    )
    if not 0 <= proposal.pokemon_index < len(parent_lineage):
        raise ValueError(
            f"stat proposal {proposal.proposal_id!r} has invalid checkpoint member"
        )
    if parent_lineage[proposal.pokemon_index] != proposal.root_pokemon_index:
        raise ValueError(
            f"stat proposal {proposal.proposal_id!r} has inconsistent member lineage"
        )

    parent_set = _target_set(
        parent,
        ai_side=request.ai_side,
        pokemon_index=proposal.pokemon_index,
    )
    parent_species = _id(
        str(parent_set.get("species") or parent_set.get("name") or "")
    )
    parent_points = _stat_points_from_set(parent_set)

    roots: list[tuple[int, BeliefParticle]] = []
    for root_index, root in enumerate(request.authority_root_particles):
        if root.world_id != parent.world_id:
            continue
        try:
            root_set = _target_set(
                root,
                ai_side=request.ai_side,
                pokemon_index=proposal.root_pokemon_index,
            )
            root_species = _id(
                str(root_set.get("species") or root_set.get("name") or "")
            )
            root_points = _stat_points_from_set(root_set)
        except ValueError:
            continue
        if root_species != parent_species or root_points != parent_points:
            continue
        roots.append((root_index, root))

    if not roots:
        raise ValueError(
            f"stat proposal {proposal.proposal_id!r} has no matching authority root"
        )
    return tuple(roots)


def _validate_typed_stat_proposal(
    *,
    request: RecoveryRequest,
    proposal: OpponentStatProposal,
) -> None:
    if not 0 <= proposal.parent_particle_index < len(
        request.checkpoint_particles
    ):
        raise ValueError(
            f"stat proposal {proposal.proposal_id!r} has invalid parent"
        )
    parent = request.checkpoint_particles[proposal.parent_particle_index]
    opponent_side = "p2" if request.ai_side == "p1" else "p1"
    lineage = particle_member_lineage(
        parent,
        opponent_side,
        require_tracked=True,
    )
    if not 0 <= proposal.pokemon_index < len(lineage):
        raise ValueError(
            f"stat proposal {proposal.proposal_id!r} has invalid checkpoint member"
        )
    if lineage[proposal.pokemon_index] != proposal.root_pokemon_index:
        raise ValueError(
            f"stat proposal {proposal.proposal_id!r} has inconsistent member lineage"
        )

    set_data = _target_set(
        parent,
        ai_side=request.ai_side,
        pokemon_index=proposal.pokemon_index,
    )

    species = str(set_data.get("species") or set_data.get("name") or "")
    if _id(species) != _id(proposal.species):
        raise ValueError(
            f"stat proposal {proposal.proposal_id!r} species does not match parent"
        )
    if _id(species) not in _publicly_seen_opponent_species(
        request.checkpoint_public_view
    ):
        raise ValueError(
            f"stat proposal {proposal.proposal_id!r} targets an unseen opponent"
        )

    parent_points = _stat_points_from_set(set_data)
    points = proposal.stat_point_dict
    if set(points) != set(_RECOVERY_STATS):
        raise ValueError(
            f"stat proposal {proposal.proposal_id!r} must specify all six stats"
        )
    if any(
        not isinstance(points[stat], int)
        or points[stat] < 0
        or points[stat] > CHAMPIONS_STAT_POINT_CAP
        for stat in _RECOVERY_STATS
    ):
        raise ValueError(
            f"stat proposal {proposal.proposal_id!r} has invalid stat points"
        )
    if sum(points.values()) > CHAMPIONS_TOTAL_STAT_POINTS:
        raise ValueError(
            f"stat proposal {proposal.proposal_id!r} exceeds the total stat cap"
        )
    if points["hp"] != parent_points["hp"]:
        raise ValueError(
            f"stat proposal {proposal.proposal_id!r} changes HP points"
        )

    changed = tuple(
        stat
        for stat in _RECOVERY_NON_HP_STATS
        if points[stat] != parent_points[stat]
    )
    if not changed:
        raise ValueError(
            f"stat proposal {proposal.proposal_id!r} changes no recoverable stat"
        )
    expected_dimensions = tuple(
        "opponent."
        f"member{proposal.root_pokemon_index}."
        f"{_id(species)}.stat_points.{stat}"
        for stat in changed
    )
    if proposal.changed_hidden_dimensions != expected_dimensions:
        raise ValueError(
            f"stat proposal {proposal.proposal_id!r} has inconsistent dimensions"
        )
    _matching_authority_roots(request, proposal)


def _materialize_stat_proposals(
    worker: RecoveryStatMaterializationWorker,
    *,
    request: RecoveryRequest,
    proposals: tuple[OpponentStatProposal, ...],
) -> RecoveryMaterializationReport:
    """Rebuild static proposals from trusted pre-opening authority states."""
    if not proposals:
        return RecoveryMaterializationReport((), ())

    opponent_side = "p2" if request.ai_side == "p1" else "p1"
    grouped: dict[int, list[tuple[OpponentStatProposal, str, int]]] = {}
    for proposal in proposals:
        _validate_typed_stat_proposal(request=request, proposal=proposal)
        for root_index, _root in _matching_authority_roots(request, proposal):
            input_index = _preopening_target_index(
                request,
                root_index=root_index,
                root_pokemon_index=proposal.root_pokemon_index,
            )
            materialization_id = f"{proposal.proposal_id}@root-{root_index}"
            grouped.setdefault(root_index, []).append(
                (proposal, materialization_id, input_index)
            )

    candidates: list[_MaterializedStatCandidate] = []
    failures: list[RecoveryMaterializationFailure] = []
    for root_index in sorted(grouped):
        root = request.authority_root_particles[root_index]
        opening = _opening_authority(request, root_index)
        batch = grouped[root_index]
        resolved = worker.materialize_recovery_opening_stat_proposals(
            battle_format=opening.battle_format,
            p1_team=opening.p1_team,
            p2_team=opening.p2_team,
            p1_name=opening.p1_name,
            p2_name=opening.p2_name,
            seed=opening.seed,
            side=opponent_side,
            p1_preview=opening.p1_preview_choice,
            p2_preview=opening.p2_preview_choice,
            proposals=[
                {
                    "proposal_id": materialization_id,
                    "pokemon_index": input_index,
                    "stat_points": proposal.stat_point_dict,
                }
                for proposal, materialization_id, input_index in batch
            ],
        )
        by_id = {
            str(result.get("proposal_id")): result
            for result in resolved
            if isinstance(result, dict)
        }
        for proposal, materialization_id, input_index in batch:
            result = by_id.get(materialization_id)
            if result is None:
                raise RuntimeError(
                    f"Showdown omitted stat proposal {materialization_id!r}"
                )
            state = result.get("state")
            if isinstance(state, dict):
                checkpoint_parent = request.checkpoint_particles[
                    proposal.parent_particle_index
                ]
                candidates.append(
                    _MaterializedStatCandidate(
                        candidate_id=materialization_id,
                        proposal_id=proposal.proposal_id,
                        parent_particle_index=proposal.parent_particle_index,
                        authority_root_particle_index=root_index,
                        root_pokemon_index=proposal.root_pokemon_index,
                        input_pokemon_index=input_index,
                        particle=BeliefParticle(
                            state=state,
                            weight=checkpoint_parent.weight,
                            world_id=checkpoint_parent.world_id,
                            history_id=(
                                f"{root.history_id}|recovery:{proposal.proposal_id}"
                            ).strip("|"),
                            p1_member_lineage=identity_member_lineage(state, "p1"),
                            p2_member_lineage=identity_member_lineage(state, "p2"),
                        ),
                        source="bounded-opponent-stat-points",
                        changed_hidden_dimensions=(
                            proposal.changed_hidden_dimensions
                        ),
                    )
                )
                continue
            reason = result.get("rejected")
            failures.append(
                RecoveryMaterializationFailure(
                    proposal=proposal,
                    reason=(
                        str(reason)
                        if isinstance(reason, str) and reason
                        else "showdown-opening-materialization-rejected"
                    ),
                )
            )

    return RecoveryMaterializationReport(tuple(candidates), tuple(failures))


class RecoveryCandidateStatus(str, Enum):
    UNAUTHORIZED_STATE_DELTA = "unauthorized-state-delta"
    AUTHORITY_ROOT_MISMATCH = "authority-root-mismatch"
    HISTORY_MISMATCH = "history-mismatch"
    KNOWN_STATE_MISMATCH = "known-state-mismatch"
    CHECKPOINT_PARENT_MISMATCH = "checkpoint-parent-mismatch"
    REPLAY_MISMATCH = "replay-mismatch"
    SAMPLING_EXHAUSTED = "sampling-exhausted"
    VALIDATED = "validated"


@dataclass(frozen=True)
class RecoveryCandidateValidation:
    candidate: _MaterializedStatCandidate
    status: RecoveryCandidateStatus
    checkpoint_compatible: bool | None
    authority_observations_replayed: int
    observations_replayed: int
    generated_branches: int
    matched_branches: int
    final_particles: tuple[BeliefParticle, ...] = ()

    @property
    def fully_validated(self) -> bool:
        return self.status is RecoveryCandidateStatus.VALIDATED


@dataclass(frozen=True)
class RecoveryValidationReport:
    """Typed static-stat recovery evidence; there is no install/apply operation."""

    candidate_results: tuple[RecoveryCandidateValidation, ...]
    materialization_failures: tuple[RecoveryMaterializationFailure, ...] = ()

    @property
    def validated_candidates(self) -> tuple[RecoveryCandidateValidation, ...]:
        return tuple(
            result for result in self.candidate_results if result.fully_validated
        )

    @property
    def validated_particles(self) -> tuple[BeliefParticle, ...]:
        return tuple(
            particle
            for result in self.validated_candidates
            for particle in result.final_particles
        )


    @property
    def inconclusive_candidates(self) -> tuple[RecoveryCandidateValidation, ...]:
        return tuple(
            result
            for result in self.candidate_results
            if result.status is RecoveryCandidateStatus.SAMPLING_EXHAUSTED
        )


class _ReplayStopReason(str, Enum):
    COMPLETE = "complete"
    SAMPLING_EXHAUSTED = "sampling-exhausted"


@dataclass(frozen=True)
class _ReplayOutcome:
    particles: tuple[BeliefParticle, ...]
    generated: int
    matched: int
    replayed: int
    stop_reason: _ReplayStopReason


def _validate_observation_chain(
    *,
    start_view: dict[str, Any],
    observations: tuple[RecoveryObservation, ...],
    label: str,
) -> str:
    previous_signature = public_observation_signature(start_view)
    for index, observation in enumerate(observations):
        if observation.previous_public_view is None:
            raise ValueError(
                f"{label} observation {index} is missing previous public view"
            )
        supplied_previous = public_observation_signature(
            observation.previous_public_view
        )
        if supplied_previous != previous_signature:
            raise ValueError(
                f"{label} observation history is not contiguous at index {index}"
            )
        previous_signature = public_observation_signature(
            observation.public_view
        )
    return previous_signature


def _validate_request(
    request: RecoveryRequest,
    authority_rng_seeds_by_observation: tuple[tuple[str | None, ...], ...],
    rng_seeds_by_observation: tuple[tuple[str | None, ...], ...],
) -> None:
    if _recovery_request_fingerprint(request) != request._authority_fingerprint:
        raise ValueError("recovery request authority inputs were mutated")
    if request.ai_side not in {"p1", "p2"}:
        raise ValueError("ai_side must be p1 or p2")
    if not request.authority_history_complete:
        raise ValueError("static recovery authority history is incomplete")
    if not request.authority_root_particles:
        raise ValueError("static recovery requires authority root particles")
    if len(request.opening_authorities) != len(
        request.authority_root_particles
    ):
        raise ValueError(
            "every static recovery root requires pre-opening authority"
        )
    for root_index, root in enumerate(request.authority_root_particles):
        opening = _opening_authority(request, root_index)
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (
                opening.battle_format,
                opening.p1_team,
                opening.p2_team,
                opening.p1_name,
                opening.p2_name,
                opening.seed,
                opening.p1_preview_choice,
                opening.p2_preview_choice,
            )
        ):
            raise ValueError(
                "opening authority requires exact creation and preview inputs"
            )
        for side_index, mapping in enumerate(
            (
                opening.p1_root_to_input,
                opening.p2_root_to_input,
            )
        ):
            sides = root.state.get("sides")
            if (
                not isinstance(sides, list)
                or len(sides) <= side_index
                or not isinstance(sides[side_index], dict)
                or not isinstance(sides[side_index].get("pokemon"), list)
            ):
                raise ValueError("static recovery root is missing side data")
            expected = len(sides[side_index]["pokemon"])
            if len(mapping) != expected or len(set(mapping)) != len(mapping):
                raise ValueError("opening input member lineage is incomplete")
        for side in ("p1", "p2"):
            lineage = particle_member_lineage(
                root,
                side,
                require_tracked=True,
            )
            if lineage != identity_member_lineage(root.state, side):
                raise ValueError(
                    "static recovery authority root member lineage is not identity"
                )
    for particle in request.checkpoint_particles:
        for side in ("p1", "p2"):
            particle_member_lineage(
                particle,
                side,
                require_tracked=True,
            )
    root_turn = request.authority_root_public_view.get("turn")
    if root_turn != 1:
        raise ValueError("static recovery authority root must be post-preview turn 1")
    if any(
        particle.state.get("turn") != 1
        for particle in request.authority_root_particles
    ):
        raise ValueError("static recovery authority particles must be turn-1 roots")
    if not request.checkpoint_particles:
        raise ValueError("static recovery requires checkpoint particles")
    if not request.observations:
        raise ValueError("recovery requires at least one retained observation")
    if len(authority_rng_seeds_by_observation) != len(
        request.authority_observations
    ):
        raise ValueError(
            "every authority observation requires an RNG seed set"
        )
    if len(rng_seeds_by_observation) != len(request.observations):
        raise ValueError("every recovery observation requires an RNG seed set")
    if any(not seeds for seeds in authority_rng_seeds_by_observation):
        raise ValueError("authority RNG seed sets must not be empty")
    if any(not seeds for seeds in rng_seeds_by_observation):
        raise ValueError("recovery RNG seed sets must not be empty")
    all_observations = (
        *request.authority_observations,
        *request.observations,
    )
    if any(
        not isinstance(observation.ai_choice, str)
        or not observation.ai_choice.strip()
        for observation in all_observations
    ):
        raise ValueError("recovery history requires exact AI commands")
    prefix_end = _validate_observation_chain(
        start_view=request.authority_root_public_view,
        observations=request.authority_observations,
        label="authority",
    )
    checkpoint_signature = public_observation_signature(
        request.checkpoint_public_view
    )
    if prefix_end != checkpoint_signature:
        raise ValueError(
            "authority history does not terminate at the recovery checkpoint"
        )
    _validate_observation_chain(
        start_view=request.checkpoint_public_view,
        observations=request.observations,
        label="recovery",
    )


def _exact_ai_side(state: dict[str, Any], ai_side: SideId) -> object:
    sides = state.get("sides")
    index = 0 if ai_side == "p1" else 1
    if not isinstance(sides, list) or len(sides) <= index:
        raise ValueError("recovery candidate state is missing exact side data")
    return sides[index]


def _replay_observations(
    worker: RecoveryStatValidationWorker,
    *,
    particles: tuple[BeliefParticle, ...],
    request: RecoveryRequest,
    observations: tuple[RecoveryObservation, ...],
    rng_seeds_by_observation: tuple[tuple[str | None, ...], ...],
) -> _ReplayOutcome:
    """Replay retained observations without treating finite RNG misses as proof.

    The supplied RNG seed sets are bounded samples, not exhaustive mechanics
    enumeration. A matching branch is positive evidence of reachability. Failure to
    produce one is only sampling exhaustion, even when every sampled mismatch looks
    structural or sampled states cannot reproduce the public action evidence.
    """
    current = particles
    generated = 0
    matched = 0
    replayed = 0
    for observation, rng_seeds in zip(
        observations,
        rng_seeds_by_observation,
        strict=True,
    ):
        update = condition_particles(
            worker,
            particles=current,
            ai_side=request.ai_side,
            ai_choice=observation.ai_choice,
            actual_public_view=observation.public_view,
            previous_public_view=observation.previous_public_view,
            rng_seeds=rng_seeds,
            previews=request.previews,
        )
        generated += update.generated
        matched += update.matched
        if not update.particles:
            return _ReplayOutcome(
                particles=(),
                generated=generated,
                matched=matched,
                replayed=replayed,
                stop_reason=_ReplayStopReason.SAMPLING_EXHAUSTED,
            )
        current = update.particles
        replayed += 1

    return _ReplayOutcome(
        particles=current,
        generated=generated,
        matched=matched,
        replayed=replayed,
        stop_reason=_ReplayStopReason.COMPLETE,
    )

def _validate_materialized_stat_candidates(
    worker: RecoveryStatValidationWorker,
    *,
    request: RecoveryRequest,
    candidates: tuple[_MaterializedStatCandidate, ...],
    proposals_by_id: dict[str, OpponentStatProposal],
    authority_rng_seeds_by_observation: tuple[tuple[str | None, ...], ...],
    rng_seeds_by_observation: tuple[tuple[str | None, ...], ...],
) -> RecoveryValidationReport:
    """Rebuild static hypotheses at root and replay all public history."""
    _validate_request(
        request,
        authority_rng_seeds_by_observation,
        rng_seeds_by_observation,
    )

    candidate_ids = [candidate.candidate_id for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("materialized recovery candidate ids must be unique")

    wanted_root = public_observation_signature(
        request.authority_root_public_view
    )
    opponent_side = "p2" if request.ai_side == "p1" else "p1"
    results: list[RecoveryCandidateValidation] = []

    for root_index in sorted(
        {candidate.authority_root_particle_index for candidate in candidates}
    ):
        opening = _opening_authority(request, root_index)
        root = request.authority_root_particles[root_index]
        if not worker.validate_recovery_opening_authority(
            battle_format=opening.battle_format,
            p1_team=opening.p1_team,
            p2_team=opening.p2_team,
            p1_name=opening.p1_name,
            p2_name=opening.p2_name,
            seed=opening.seed,
            root_state=deepcopy(root.state),
            p1_preview=opening.p1_preview_choice,
            p2_preview=opening.p2_preview_choice,
            p1_root_to_input=opening.p1_root_to_input,
            p2_root_to_input=opening.p2_root_to_input,
        ):
            raise ValueError(
                "pre-opening authority does not mechanically reproduce "
                f"root {root_index}"
            )

    for candidate in candidates:
        proposal = proposals_by_id.get(candidate.proposal_id)
        if proposal is None:
            raise ValueError(
                f"materialized candidate {candidate.candidate_id!r} has no typed proposal"
            )
        if not 0 <= candidate.authority_root_particle_index < len(
            request.authority_root_particles
        ):
            raise ValueError(
                f"recovery candidate {candidate.candidate_id!r} has invalid root"
            )
        authority_root = request.authority_root_particles[
            candidate.authority_root_particle_index
        ]
        checkpoint_parent = request.checkpoint_particles[
            proposal.parent_particle_index
        ]
        checkpoint_parent_view = worker.state_view(
            state=checkpoint_parent.state,
            side=request.ai_side,
            previews=request.previews,
        )
        if public_observation_signature(
            checkpoint_parent_view
        ) != public_observation_signature(request.checkpoint_public_view):
            results.append(
                RecoveryCandidateValidation(
                    candidate=candidate,
                    status=RecoveryCandidateStatus.CHECKPOINT_PARENT_MISMATCH,
                    checkpoint_compatible=False,
                    authority_observations_replayed=0,
                    observations_replayed=0,
                    generated_branches=0,
                    matched_branches=0,
                )
            )
            continue

        opening = _opening_authority(
            request,
            candidate.authority_root_particle_index,
        )
        if not worker.validate_recovery_opening_stat_candidate(
            battle_format=opening.battle_format,
            p1_team=opening.p1_team,
            p2_team=opening.p2_team,
            p1_name=opening.p1_name,
            p2_name=opening.p2_name,
            seed=opening.seed,
            candidate_state=deepcopy(candidate.particle.state),
            side=opponent_side,
            pokemon_index=candidate.input_pokemon_index,
            stat_points=proposal.stat_point_dict,
            p1_preview=opening.p1_preview_choice,
            p2_preview=opening.p2_preview_choice,
        ):
            results.append(
                RecoveryCandidateValidation(
                    candidate=candidate,
                    status=RecoveryCandidateStatus.UNAUTHORIZED_STATE_DELTA,
                    checkpoint_compatible=False,
                    authority_observations_replayed=0,
                    observations_replayed=0,
                    generated_branches=0,
                    matched_branches=0,
                )
            )
            continue
        if _exact_ai_side(
            candidate.particle.state,
            request.ai_side,
        ) != _exact_ai_side(authority_root.state, request.ai_side):
            results.append(
                RecoveryCandidateValidation(
                    candidate=candidate,
                    status=RecoveryCandidateStatus.KNOWN_STATE_MISMATCH,
                    checkpoint_compatible=False,
                    authority_observations_replayed=0,
                    observations_replayed=0,
                    generated_branches=0,
                    matched_branches=0,
                )
            )
            continue

        root_view = worker.state_view(
            state=candidate.particle.state,
            side=request.ai_side,
            previews=request.previews,
        )
        if public_observation_signature(root_view) != wanted_root:
            results.append(
                RecoveryCandidateValidation(
                    candidate=candidate,
                    status=RecoveryCandidateStatus.AUTHORITY_ROOT_MISMATCH,
                    checkpoint_compatible=False,
                    authority_observations_replayed=0,
                    observations_replayed=0,
                    generated_branches=0,
                    matched_branches=0,
                )
            )
            continue

        prefix = _replay_observations(
            worker,
            particles=(candidate.particle,),
            request=request,
            observations=request.authority_observations,
            rng_seeds_by_observation=authority_rng_seeds_by_observation,
        )
        if prefix.stop_reason is not _ReplayStopReason.COMPLETE:
            results.append(
                RecoveryCandidateValidation(
                    candidate=candidate,
                    status=RecoveryCandidateStatus.SAMPLING_EXHAUSTED,
                    checkpoint_compatible=None,
                    authority_observations_replayed=prefix.replayed,
                    observations_replayed=0,
                    generated_branches=prefix.generated,
                    matched_branches=prefix.matched,
                )
            )
            continue

        checkpoint_particles = tuple(
            particle
            for particle in prefix.particles
            if (
                _exact_ai_side(
                    particle.state,
                    request.ai_side,
                )
                == _exact_ai_side(checkpoint_parent.state, request.ai_side)
                and particle_member_lineage(
                    particle,
                    "p1",
                    require_tracked=True,
                )
                == particle_member_lineage(
                    checkpoint_parent,
                    "p1",
                    require_tracked=True,
                )
                and particle_member_lineage(
                    particle,
                    "p2",
                    require_tracked=True,
                )
                == particle_member_lineage(
                    checkpoint_parent,
                    "p2",
                    require_tracked=True,
                )
            )
        )
        if not checkpoint_particles:
            results.append(
                RecoveryCandidateValidation(
                    candidate=candidate,
                    status=RecoveryCandidateStatus.SAMPLING_EXHAUSTED,
                    checkpoint_compatible=None,
                    authority_observations_replayed=prefix.replayed,
                    observations_replayed=0,
                    generated_branches=prefix.generated,
                    matched_branches=prefix.matched,
                )
            )
            continue

        suffix = _replay_observations(
            worker,
            particles=checkpoint_particles,
            request=request,
            observations=request.observations,
            rng_seeds_by_observation=rng_seeds_by_observation,
        )
        status = (
            RecoveryCandidateStatus.VALIDATED
            if suffix.stop_reason is _ReplayStopReason.COMPLETE
            else RecoveryCandidateStatus.SAMPLING_EXHAUSTED
        )
        results.append(
            RecoveryCandidateValidation(
                candidate=candidate,
                status=status,
                checkpoint_compatible=True,
                authority_observations_replayed=prefix.replayed,
                observations_replayed=suffix.replayed,
                generated_branches=prefix.generated + suffix.generated,
                matched_branches=prefix.matched + suffix.matched,
                final_particles=(
                    suffix.particles
                    if status is RecoveryCandidateStatus.VALIDATED
                    else ()
                ),
            )
        )

    return RecoveryValidationReport(tuple(results))


def validate_stat_recovery_proposals(
    worker: RecoveryStatValidationWorker,
    *,
    request: RecoveryRequest,
    proposals: tuple[OpponentStatProposal, ...],
    authority_rng_seeds_by_observation: tuple[
        tuple[str | None, ...],
        ...,
    ],
    rng_seeds_by_observation: tuple[tuple[str | None, ...], ...],
) -> RecoveryValidationReport:
    """Validate lifelong stat proposals from root through all retained history.

    Static stat proposals are applied only to trusted battle-creation inputs.
    Pinned Showdown must construct a fresh battle, resolve the exact preview choices
    and opening mechanics, independently prove the returned turn-one candidate,
    and then reproduce every retained public transition through the current
    checkpoint before any recovery suffix is considered. Finite RNG samples may
    witness compatibility, but failure to sample a witness is reported as
    SAMPLING_EXHAUSTED rather than mechanical incompatibility.
    """
    _validate_request(
        request,
        authority_rng_seeds_by_observation,
        rng_seeds_by_observation,
    )
    proposal_ids = [proposal.proposal_id for proposal in proposals]
    if len(proposal_ids) != len(set(proposal_ids)):
        raise ValueError("recovery stat proposal ids must be unique")

    materialized = _materialize_stat_proposals(
        worker,
        request=request,
        proposals=proposals,
    )
    _validate_request(
        request,
        authority_rng_seeds_by_observation,
        rng_seeds_by_observation,
    )
    validated = _validate_materialized_stat_candidates(
        worker,
        request=request,
        candidates=materialized.candidates,
        proposals_by_id={proposal.proposal_id: proposal for proposal in proposals},
        authority_rng_seeds_by_observation=authority_rng_seeds_by_observation,
        rng_seeds_by_observation=rng_seeds_by_observation,
    )
    return RecoveryValidationReport(
        candidate_results=validated.candidate_results,
        materialization_failures=materialized.failures,
    )
