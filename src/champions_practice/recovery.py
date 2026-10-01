"""Mechanics-authoritative recovery contracts and replay validation.

This module is intentionally not integrated into the live decision controller yet.
Candidate generation may propose alternate *checkpoint* belief states, but proposals
have no authority until the pinned Showdown runtime reproduces the complete retained
public history from that checkpoint.

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
    resolved_opponent_choice: str | None
    previous_public_view: dict[str, Any] | None
    public_view: dict[str, Any]


@dataclass(frozen=True)
class RecoveryRequest:
    """Trusted static-history root, current checkpoint, and retained suffix evidence.

    Static hidden dimensions such as stat points are lifelong. A proposal therefore
    cannot gain authority by mutating a midgame checkpoint and replaying only later
    observations. authority_root_particles and authority_observations provide the
    mechanically replayable prefix from post-preview through checkpoint_public_view.
    """

    authority_root_particles: tuple[BeliefParticle, ...]
    authority_root_public_view: dict[str, Any]
    authority_observations: tuple[RecoveryObservation, ...]
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
            }
            for particle in request.authority_root_particles
        ],
        "authority_root_public_view": request.authority_root_public_view,
        "authority_observations": [
            {
                "ai_choice": observation.ai_choice,
                "resolved_opponent_choice": observation.resolved_opponent_choice,
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
            }
            for particle in request.checkpoint_particles
        ],
        "checkpoint_public_view": request.checkpoint_public_view,
        "observations": [
            {
                "ai_choice": observation.ai_choice,
                "resolved_opponent_choice": observation.resolved_opponent_choice,
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
        ranked: list[tuple[int, int, int, tuple[int, ...], OpponentStatProposal]] = []

        for parent_index, particle in enumerate(request.checkpoint_particles):
            sides = particle.state.get("sides")
            if not isinstance(sides, list) or len(sides) <= opponent_side_index:
                raise ValueError("checkpoint particle is missing opponent side data")
            pokemon = sides[opponent_side_index].get("pokemon")
            if not isinstance(pokemon, list):
                raise ValueError("checkpoint particle is missing opponent Pokemon")

            for pokemon_index, mon in enumerate(pokemon):
                if not isinstance(mon, dict):
                    continue
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
                            f"p{parent_index}-m{pokemon_index}-"
                            + "-".join(
                                f"{stat}{variant[stat]}" for stat in _RECOVERY_STATS
                            )
                        ),
                        parent_particle_index=parent_index,
                        pokemon_index=pokemon_index,
                        species=species,
                        stat_points=tuple(
                            (stat, variant[stat]) for stat in _RECOVERY_STATS
                        ),
                        changed_hidden_dimensions=tuple(
                            f"opponent.{_id(species)}.stat_points.{stat}"
                            for stat in changed
                        ),
                    )
                    ranked.append(
                        (distance, parent_index, pokemon_index, signature, proposal)
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


class RecoveryStatValidationWorker(
    RecoveryStatMaterializationWorker,
    Protocol,
):
    """Typed static-stat recovery needs materialization plus hypothetical replay."""

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
                pokemon_index=proposal.pokemon_index,
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
        f"opponent.{_id(species)}.stat_points.{stat}" for stat in changed
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
    """Materialize static stat proposals only at replayable authority roots."""
    if not proposals:
        return RecoveryMaterializationReport((), ())

    opponent_side = "p2" if request.ai_side == "p1" else "p1"
    grouped: dict[int, list[tuple[OpponentStatProposal, str]]] = {}
    for proposal in proposals:
        _validate_typed_stat_proposal(request=request, proposal=proposal)
        for root_index, _root in _matching_authority_roots(request, proposal):
            materialization_id = f"{proposal.proposal_id}@root-{root_index}"
            grouped.setdefault(root_index, []).append(
                (proposal, materialization_id)
            )

    candidates: list[_MaterializedStatCandidate] = []
    failures: list[RecoveryMaterializationFailure] = []
    for root_index in sorted(grouped):
        root = request.authority_root_particles[root_index]
        batch = grouped[root_index]
        resolved = worker.materialize_recovery_stat_proposals(
            state=deepcopy(root.state),
            side=opponent_side,
            proposals=[
                {
                    "proposal_id": materialization_id,
                    "pokemon_index": proposal.pokemon_index,
                    "stat_points": proposal.stat_point_dict,
                }
                for proposal, materialization_id in batch
            ],
        )
        by_id = {
            str(result.get("proposal_id")): result
            for result in resolved
            if isinstance(result, dict)
        }
        for proposal, materialization_id in batch:
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
                        particle=BeliefParticle(
                            state=state,
                            weight=checkpoint_parent.weight,
                            world_id=checkpoint_parent.world_id,
                            history_id=(
                                f"{root.history_id}|recovery:{proposal.proposal_id}"
                            ).strip("|"),
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
                        else "showdown-materialization-rejected"
                    ),
                )
            )

    return RecoveryMaterializationReport(tuple(candidates), tuple(failures))


class RecoveryCandidateStatus(str, Enum):
    UNAUTHORIZED_STATE_DELTA = "unauthorized-state-delta"
    AUTHORITY_ROOT_MISMATCH = "authority-root-mismatch"
    HISTORY_MISMATCH = "history-mismatch"
    KNOWN_STATE_MISMATCH = "known-state-mismatch"
    REPLAY_MISMATCH = "replay-mismatch"
    VALIDATED = "validated"


@dataclass(frozen=True)
class RecoveryCandidateValidation:
    candidate: _MaterializedStatCandidate
    status: RecoveryCandidateStatus
    checkpoint_compatible: bool
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
    if not request.authority_root_particles:
        raise ValueError("static recovery requires authority root particles")
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


def _state_without_allowed_stat_delta(
    state: dict[str, Any],
    *,
    ai_side: SideId,
    pokemon_index: int,
) -> dict[str, Any]:
    reduced = deepcopy(state)
    target = _target_pokemon(
        reduced,
        ai_side=ai_side,
        pokemon_index=pokemon_index,
    )
    set_data = target.get("set")
    if not isinstance(set_data, dict):
        raise ValueError("recovery target Pokemon is missing set data")
    set_data.pop("evs", None)
    target.pop("baseStoredStats", None)
    target.pop("storedStats", None)
    target.pop("speed", None)
    return reduced


def _stat_candidate_delta_authorized(
    *,
    authority_root: BeliefParticle,
    candidate: _MaterializedStatCandidate,
    proposal: OpponentStatProposal,
    ai_side: SideId,
) -> bool:
    if candidate.parent_particle_index != proposal.parent_particle_index:
        return False
    if candidate.proposal_id != proposal.proposal_id:
        return False

    root_target = _target_pokemon(
        authority_root.state,
        ai_side=ai_side,
        pokemon_index=proposal.pokemon_index,
    )
    candidate_target = _target_pokemon(
        candidate.particle.state,
        ai_side=ai_side,
        pokemon_index=proposal.pokemon_index,
    )
    root_set = root_target.get("set")
    candidate_set = candidate_target.get("set")
    if not isinstance(root_set, dict) or not isinstance(candidate_set, dict):
        return False

    try:
        root_points = _stat_points_from_set(root_set)
        candidate_points = _stat_points_from_set(candidate_set)
    except ValueError:
        return False
    candidate_raw_points = candidate_set.get("evs")
    if candidate_raw_points != proposal.stat_point_dict:
        return False
    if candidate_points != proposal.stat_point_dict:
        return False
    if candidate_points["hp"] != root_points["hp"]:
        return False

    root_reduced = _state_without_allowed_stat_delta(
        authority_root.state,
        ai_side=ai_side,
        pokemon_index=proposal.pokemon_index,
    )
    candidate_reduced = _state_without_allowed_stat_delta(
        candidate.particle.state,
        ai_side=ai_side,
        pokemon_index=proposal.pokemon_index,
    )
    return root_reduced == candidate_reduced


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
) -> tuple[tuple[BeliefParticle, ...], int, int, int]:
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
            resolved_opponent_choice=observation.resolved_opponent_choice,
            rng_seeds=rng_seeds,
            previews=request.previews,
        )
        generated += update.generated
        matched += update.matched
        if not update.particles:
            return (), generated, matched, replayed
        current = update.particles
        replayed += 1
    return current, generated, matched, replayed


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
    results: list[RecoveryCandidateValidation] = []

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

        if not _stat_candidate_delta_authorized(
            authority_root=authority_root,
            candidate=candidate,
            proposal=proposal,
            ai_side=request.ai_side,
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

        (
            checkpoint_particles,
            prefix_generated,
            prefix_matched,
            prefix_replayed,
        ) = _replay_observations(
            worker,
            particles=(candidate.particle,),
            request=request,
            observations=request.authority_observations,
            rng_seeds_by_observation=authority_rng_seeds_by_observation,
        )
        if prefix_replayed != len(request.authority_observations):
            results.append(
                RecoveryCandidateValidation(
                    candidate=candidate,
                    status=RecoveryCandidateStatus.HISTORY_MISMATCH,
                    checkpoint_compatible=False,
                    authority_observations_replayed=prefix_replayed,
                    observations_replayed=0,
                    generated_branches=prefix_generated,
                    matched_branches=prefix_matched,
                )
            )
            continue

        checkpoint_particles = tuple(
            particle
            for particle in checkpoint_particles
            if _exact_ai_side(
                particle.state,
                request.ai_side,
            ) == _exact_ai_side(checkpoint_parent.state, request.ai_side)
        )
        if not checkpoint_particles:
            results.append(
                RecoveryCandidateValidation(
                    candidate=candidate,
                    status=RecoveryCandidateStatus.KNOWN_STATE_MISMATCH,
                    checkpoint_compatible=False,
                    authority_observations_replayed=prefix_replayed,
                    observations_replayed=0,
                    generated_branches=prefix_generated,
                    matched_branches=prefix_matched,
                )
            )
            continue

        (
            final_particles,
            suffix_generated,
            suffix_matched,
            suffix_replayed,
        ) = _replay_observations(
            worker,
            particles=checkpoint_particles,
            request=request,
            observations=request.observations,
            rng_seeds_by_observation=rng_seeds_by_observation,
        )
        status = (
            RecoveryCandidateStatus.VALIDATED
            if suffix_replayed == len(request.observations) and final_particles
            else RecoveryCandidateStatus.REPLAY_MISMATCH
        )
        results.append(
            RecoveryCandidateValidation(
                candidate=candidate,
                status=status,
                checkpoint_compatible=True,
                authority_observations_replayed=prefix_replayed,
                observations_replayed=suffix_replayed,
                generated_branches=prefix_generated + suffix_generated,
                matched_branches=prefix_matched + suffix_matched,
                final_particles=(
                    final_particles
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
    ] = (),
    rng_seeds_by_observation: tuple[tuple[str | None, ...], ...],
) -> RecoveryValidationReport:
    """Validate lifelong stat proposals from root through all retained history.

    Static stat proposals are materialized only at matching post-preview authority
    roots. The changed hypothesis must then mechanically reproduce every retained
    public transition through the current checkpoint before any recovery suffix is
    considered. A copied midgame ledger or final-board match has no authority.
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
