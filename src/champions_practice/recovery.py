"""Mechanics-authoritative recovery contracts and replay validation.

This module is intentionally not integrated into the live decision controller yet.
Candidate generation may propose alternate *checkpoint* belief states, but proposals
have no authority until the pinned Showdown runtime reproduces the complete retained
public history from that checkpoint.

The live session's exact hidden state is never an input to this API.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, Protocol

from champions_practice.observation_beliefs import (
    BeliefParticle,
    condition_particles,
    public_observation_signature,
)

SideId = Literal["p1", "p2"]


@dataclass(frozen=True)
class RecoveryObservation:
    """One already-resolved public transition that a candidate must replay."""

    ai_choice: str
    resolved_opponent_choice: str | None
    previous_public_view: dict[str, Any] | None
    public_view: dict[str, Any]


@dataclass(frozen=True)
class RecoveryRequest:
    """Inputs available to a recovery candidate generator.

    checkpoint_particles are the engine's last-good hypothetical belief states.
    checkpoint_public_view and observations are sanitized public information.
    No live-session worker, session identifier, or authoritative hidden state is
    exposed to candidate generation.
    """

    checkpoint_particles: tuple[BeliefParticle, ...]
    checkpoint_public_view: dict[str, Any]
    observations: tuple[RecoveryObservation, ...]
    ai_side: SideId
    previews: dict[str, list[str]] | None = None


@dataclass(frozen=True)
class RecoveryCandidate:
    """One proposed hidden-world variant at the last-good checkpoint."""

    candidate_id: str
    particle: BeliefParticle
    source: str
    changed_hidden_dimensions: tuple[str, ...] = ()


class RecoveryCandidateGenerator(Protocol):
    """Public/belief-only proposal boundary.

    Generators receive RecoveryRequest only. Mechanics authority belongs to
    validate_recovery_candidates(), which uses a hypothetical Showdown worker.
    """

    def generate(
        self,
        request: RecoveryRequest,
    ) -> tuple[RecoveryCandidate, ...]: ...


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


class RecoveryCandidateStatus(str, Enum):
    CHECKPOINT_MISMATCH = "checkpoint-mismatch"
    REPLAY_MISMATCH = "replay-mismatch"
    VALIDATED = "validated"


@dataclass(frozen=True)
class RecoveryCandidateValidation:
    candidate: RecoveryCandidate
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
    """Validation evidence only; there is deliberately no install/apply operation."""

    candidate_results: tuple[RecoveryCandidateValidation, ...]

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


def validate_recovery_candidates(
    worker: RecoveryReplayWorker,
    *,
    request: RecoveryRequest,
    candidates: tuple[RecoveryCandidate, ...],
    rng_seeds_by_observation: tuple[tuple[str | None, ...], ...],
) -> RecoveryValidationReport:
    """Replay candidate checkpoint states through all retained public evidence.

    A proposal is valid only when:
      1. its checkpoint state reproduces the last-good public view, and
      2. pinned mechanics replay reproduces every queued observation in order.

    Candidate metadata, mismatch classification, or final-board similarity never
    authorizes a state. This function does not mutate the live belief engine.
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
