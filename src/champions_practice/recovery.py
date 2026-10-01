"""Mechanics-authoritative recovery contracts and replay validation.

This module is intentionally not integrated into the live decision controller yet.
Candidate generation may propose alternate *checkpoint* belief states, but proposals
have no authority until the pinned Showdown runtime reproduces the complete retained
public history from that checkpoint.

The live session's exact hidden state is never an input to this API.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
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
    """Trusted last-good checkpoint plus sanitized retained public evidence."""

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
    """Internal result of trusted Showdown stat materialization.

    Public recovery authority APIs never accept this serialized state from callers.
    """

    candidate_id: str
    parent_particle_index: int
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
    """Typed stat recovery needs materialization plus hypothetical replay."""

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


class RecoveryReplayWorker(Protocol):
    """Minimal hypothetical mechanics capability required for validation."""

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
    target = _target_pokemon(
        parent.state,
        ai_side=request.ai_side,
        pokemon_index=proposal.pokemon_index,
    )
    set_data = target.get("set")
    if not isinstance(set_data, dict):
        raise ValueError("stat proposal target is missing set data")

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


def _materialize_stat_proposals(
    worker: RecoveryStatMaterializationWorker,
    *,
    request: RecoveryRequest,
    proposals: tuple[OpponentStatProposal, ...],
) -> RecoveryMaterializationReport:
    """Ask Showdown to rebuild coherent checkpoint states for stat proposals."""
    if not proposals:
        return RecoveryMaterializationReport((), ())

    opponent_side = "p2" if request.ai_side == "p1" else "p1"
    grouped: dict[int, list[OpponentStatProposal]] = {}
    for proposal in proposals:
        _validate_typed_stat_proposal(request=request, proposal=proposal)
        grouped.setdefault(proposal.parent_particle_index, []).append(proposal)

    candidates: list[_MaterializedStatCandidate] = []
    failures: list[RecoveryMaterializationFailure] = []
    for parent_index in sorted(grouped):
        parent = request.checkpoint_particles[parent_index]
        batch = grouped[parent_index]
        resolved = worker.materialize_recovery_stat_proposals(
            state=parent.state,
            side=opponent_side,
            proposals=[
                {
                    "proposal_id": proposal.proposal_id,
                    "pokemon_index": proposal.pokemon_index,
                    "stat_points": proposal.stat_point_dict,
                }
                for proposal in batch
            ],
        )
        by_id = {
            str(result.get("proposal_id")): result
            for result in resolved
            if isinstance(result, dict)
        }
        for proposal in batch:
            result = by_id.get(proposal.proposal_id)
            if result is None:
                raise RuntimeError(
                    f"Showdown omitted stat proposal {proposal.proposal_id!r}"
                )
            state = result.get("state")
            if isinstance(state, dict):
                candidates.append(
                    _MaterializedStatCandidate(
                        candidate_id=proposal.proposal_id,
                        parent_particle_index=proposal.parent_particle_index,
                        particle=BeliefParticle(
                            state=state,
                            weight=parent.weight,
                            world_id=parent.world_id,
                            history_id=(
                                f"{parent.history_id}|recovery:{proposal.proposal_id}"
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
    KNOWN_STATE_MISMATCH = "known-state-mismatch"
    CHECKPOINT_MISMATCH = "checkpoint-mismatch"
    REPLAY_MISMATCH = "replay-mismatch"
    VALIDATED = "validated"


@dataclass(frozen=True)
class RecoveryCandidateValidation:
    candidate: _MaterializedStatCandidate
    status: RecoveryCandidateStatus
    checkpoint_compatible: bool
    observations_replayed: int
    generated_branches: int
    matched_branches: int
    final_particles: tuple[BeliefParticle, ...] = ()

    @property
    def fully_validated(self) -> bool:
        return self.status is RecoveryCandidateStatus.VALIDATED


@dataclass(frozen=True)
class RecoveryValidationReport:
    """Typed stat-recovery evidence; there is no install/apply operation."""

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


def _validate_request(
    request: RecoveryRequest,
    rng_seeds_by_observation: tuple[tuple[str | None, ...], ...],
) -> None:
    if _recovery_request_fingerprint(request) != request._authority_fingerprint:
        raise ValueError("recovery request authority inputs were mutated")
    if request.ai_side not in {"p1", "p2"}:
        raise ValueError("ai_side must be p1 or p2")
    if not request.observations:
        raise ValueError("recovery requires at least one retained observation")
    if len(rng_seeds_by_observation) != len(request.observations):
        raise ValueError("every recovery observation requires an RNG seed set")
    if any(not seeds for seeds in rng_seeds_by_observation):
        raise ValueError("recovery RNG seed sets must not be empty")

    checkpoint_signature = public_observation_signature(
        request.checkpoint_public_view
    )
    previous_signature = checkpoint_signature
    for index, observation in enumerate(request.observations):
        if observation.previous_public_view is not None:
            supplied_previous = public_observation_signature(
                observation.previous_public_view
            )
            if supplied_previous != previous_signature:
                raise ValueError(
                    "recovery observation history is not contiguous at "
                    f"index {index}"
                )
        previous_signature = public_observation_signature(
            observation.public_view
        )


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
    parent: BeliefParticle,
    candidate: _MaterializedStatCandidate,
    proposal: OpponentStatProposal,
    ai_side: SideId,
) -> bool:
    if candidate.parent_particle_index != proposal.parent_particle_index:
        return False
    if candidate.candidate_id != proposal.proposal_id:
        return False

    parent_target = _target_pokemon(
        parent.state,
        ai_side=ai_side,
        pokemon_index=proposal.pokemon_index,
    )
    candidate_target = _target_pokemon(
        candidate.particle.state,
        ai_side=ai_side,
        pokemon_index=proposal.pokemon_index,
    )
    parent_set = parent_target.get("set")
    candidate_set = candidate_target.get("set")
    if not isinstance(parent_set, dict) or not isinstance(candidate_set, dict):
        return False

    try:
        parent_points = _stat_points_from_set(parent_set)
        candidate_points = _stat_points_from_set(candidate_set)
    except ValueError:
        return False
    candidate_raw_points = candidate_set.get("evs")
    if candidate_raw_points != proposal.stat_point_dict:
        return False
    if candidate_points != proposal.stat_point_dict:
        return False
    if candidate_points["hp"] != parent_points["hp"]:
        return False

    parent_reduced = _state_without_allowed_stat_delta(
        parent.state,
        ai_side=ai_side,
        pokemon_index=proposal.pokemon_index,
    )
    candidate_reduced = _state_without_allowed_stat_delta(
        candidate.particle.state,
        ai_side=ai_side,
        pokemon_index=proposal.pokemon_index,
    )
    return parent_reduced == candidate_reduced


def _exact_ai_side(state: dict[str, Any], ai_side: SideId) -> object:
    sides = state.get("sides")
    index = 0 if ai_side == "p1" else 1
    if not isinstance(sides, list) or len(sides) <= index:
        raise ValueError("recovery candidate state is missing exact side data")
    return sides[index]


def _validate_materialized_stat_candidates(
    worker: RecoveryReplayWorker,
    *,
    request: RecoveryRequest,
    candidates: tuple[_MaterializedStatCandidate, ...],
    proposals_by_id: dict[str, OpponentStatProposal],
    rng_seeds_by_observation: tuple[tuple[str | None, ...], ...],
) -> RecoveryValidationReport:
    """Validate only Showdown-materialized typed stat proposals.

    The serialized candidate is not trusted merely because it came back from a
    proposal step. Before any public replay, its delta from the trusted parent
    must be confined to the target Pokemon's set.evs plus simulator-derived
    base/stored stat and speed fields.
    """
    _validate_request(request, rng_seeds_by_observation)

    candidate_ids = [candidate.candidate_id for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("recovery candidate ids must be unique")

    wanted_checkpoint = public_observation_signature(
        request.checkpoint_public_view
    )
    results: list[RecoveryCandidateValidation] = []

    for candidate in candidates:
        proposal = proposals_by_id.get(candidate.candidate_id)
        if proposal is None:
            raise ValueError(
                f"materialized candidate {candidate.candidate_id!r} has no typed proposal"
            )
        if not 0 <= candidate.parent_particle_index < len(
            request.checkpoint_particles
        ):
            raise ValueError(
                f"recovery candidate {candidate.candidate_id!r} has invalid parent"
            )
        parent = request.checkpoint_particles[candidate.parent_particle_index]
        if not _stat_candidate_delta_authorized(
            parent=parent,
            candidate=candidate,
            proposal=proposal,
            ai_side=request.ai_side,
        ):
            results.append(
                RecoveryCandidateValidation(
                    candidate=candidate,
                    status=RecoveryCandidateStatus.UNAUTHORIZED_STATE_DELTA,
                    checkpoint_compatible=False,
                    observations_replayed=0,
                    generated_branches=0,
                    matched_branches=0,
                )
            )
            continue
        if _exact_ai_side(candidate.particle.state, request.ai_side) != _exact_ai_side(
            parent.state,
            request.ai_side,
        ):
            results.append(
                RecoveryCandidateValidation(
                    candidate=candidate,
                    status=RecoveryCandidateStatus.KNOWN_STATE_MISMATCH,
                    checkpoint_compatible=False,
                    observations_replayed=0,
                    generated_branches=0,
                    matched_branches=0,
                )
            )
            continue

        checkpoint_view = worker.state_view(
            state=candidate.particle.state,
            side=request.ai_side,
            previews=request.previews,
        )
        if public_observation_signature(checkpoint_view) != wanted_checkpoint:
            results.append(
                RecoveryCandidateValidation(
                    candidate=candidate,
                    status=RecoveryCandidateStatus.CHECKPOINT_MISMATCH,
                    checkpoint_compatible=False,
                    observations_replayed=0,
                    generated_branches=0,
                    matched_branches=0,
                )
            )
            continue

        particles = (candidate.particle,)
        generated = 0
        matched = 0
        observations_replayed = 0

        for observation, rng_seeds in zip(
            request.observations,
            rng_seeds_by_observation,
            strict=True,
        ):
            update = condition_particles(
                worker,
                particles=particles,
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
                break
            particles = update.particles
            observations_replayed += 1

        status = (
            RecoveryCandidateStatus.VALIDATED
            if observations_replayed == len(request.observations) and particles
            else RecoveryCandidateStatus.REPLAY_MISMATCH
        )
        results.append(
            RecoveryCandidateValidation(
                candidate=candidate,
                status=status,
                checkpoint_compatible=True,
                observations_replayed=observations_replayed,
                generated_branches=generated,
                matched_branches=matched,
                final_particles=particles if status is RecoveryCandidateStatus.VALIDATED else (),
            )
        )

    return RecoveryValidationReport(tuple(results))


def validate_stat_recovery_proposals(
    worker: RecoveryStatValidationWorker,
    *,
    request: RecoveryRequest,
    proposals: tuple[OpponentStatProposal, ...],
    rng_seeds_by_observation: tuple[tuple[str | None, ...], ...],
) -> RecoveryValidationReport:
    """Materialize and validate typed stat proposals from trusted parents.

    Callers cannot supply serialized candidate states. The only candidate states
    considered for authority are produced internally from request checkpoint
    parents by the hypothetical Showdown stat materializer, then checked against
    a strict serialized-state delta allowlist before replay.
    """
    _validate_request(request, rng_seeds_by_observation)
    proposal_ids = [proposal.proposal_id for proposal in proposals]
    if len(proposal_ids) != len(set(proposal_ids)):
        raise ValueError("recovery stat proposal ids must be unique")

    materialized = _materialize_stat_proposals(
        worker,
        request=request,
        proposals=proposals,
    )
    validated = _validate_materialized_stat_candidates(
        worker,
        request=request,
        candidates=materialized.candidates,
        proposals_by_id={proposal.proposal_id: proposal for proposal in proposals},
        rng_seeds_by_observation=rng_seeds_by_observation,
    )
    return RecoveryValidationReport(
        candidate_results=validated.candidate_results,
        materialization_failures=materialized.failures,
    )
