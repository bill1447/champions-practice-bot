"""Observation-conditioned exact belief particles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from .search_worker import ShowdownSearchWorker


@dataclass(frozen=True)
class BeliefParticle:
    state: dict[str, Any]
    weight: float
    world_id: str = ""
    history_id: str = ""


@dataclass(frozen=True)
class ParticleUpdate:
    particles: tuple[BeliefParticle, ...]
    generated: int
    matched: int
    deduplicated: int


def public_observation_signature(view: dict[str, Any]) -> str:
    return json.dumps(view, sort_keys=True, separators=(",", ":"))


def _state_key(state: dict[str, Any]) -> str:
    return json.dumps(state, sort_keys=True, separators=(",", ":"))


def _normalize(particles: Iterable[BeliefParticle]) -> tuple[BeliefParticle, ...]:
    particles = tuple(particles)
    total = sum(particle.weight for particle in particles)
    if total <= 0:
        return ()
    return tuple(
        BeliefParticle(
            state=particle.state,
            weight=particle.weight / total,
            world_id=particle.world_id,
            history_id=particle.history_id,
        )
        for particle in particles
    )


def condition_particles(
    worker: ShowdownSearchWorker,
    *,
    particles: tuple[BeliefParticle, ...],
    ai_side: str,
    ai_choice: str,
    actual_public_view: dict[str, Any],
    opponent_choices: dict[str, tuple[str, ...]] | None = None,
    rng_seeds: tuple[str | None, ...] = (None,),
    previews: dict[str, list[str]] | None = None,
) -> ParticleUpdate:
    if ai_side not in {"p1", "p2"}:
        raise ValueError("ai_side must be p1 or p2")
    if not particles:
        return ParticleUpdate((), 0, 0, 0)

    opponent_side = "p2" if ai_side == "p1" else "p1"
    wanted = public_observation_signature(actual_public_view)
    survivors: list[BeliefParticle] = []
    generated = 0
    matched = 0

    for particle in particles:
        legal_responses = tuple(
            worker.legal_choices(state=particle.state, side=opponent_side)
        )
        if opponent_choices is None:
            responses = legal_responses
        else:
            requested = opponent_choices.get(particle.world_id)
            if requested is None:
                responses = legal_responses
            else:
                legal_set = set(legal_responses)
                responses = tuple(
                    response for response in requested if response in legal_set
                )
        if not responses:
            continue

        branch_count = len(responses) * len(rng_seeds)
        branch_weight = particle.weight / branch_count
        branches = []
        identities = []
        for response in responses:
            for rng_seed in rng_seeds:
                branch = {
                    "p1_choice": ai_choice if ai_side == "p1" else response,
                    "p2_choice": ai_choice if ai_side == "p2" else response,
                    "include_state": True,
                }
                if rng_seed is not None:
                    branch["rng_seed"] = rng_seed
                branches.append(branch)
                identities.append((response, rng_seed))

        resolved = worker.branch_many(state=particle.state, branches=branches)
        generated += len(resolved)
        for result, identity in zip(resolved, identities, strict=True):
            response, rng_seed = identity
            state = result.get("state")
            if not isinstance(state, dict):
                raise RuntimeError("particle branch did not return exact state")
            view = worker.state_view(state=state, side=ai_side, previews=previews)
            if public_observation_signature(view) != wanted:
                continue
            matched += 1
            rng_label = "native" if rng_seed is None else rng_seed
            history = f"{particle.history_id}|{response}|{rng_label}".strip("|")
            survivors.append(
                BeliefParticle(
                    state=state,
                    weight=branch_weight,
                    world_id=particle.world_id,
                    history_id=history,
                )
            )

    merged: dict[str, BeliefParticle] = {}
    for particle in survivors:
        key = _state_key(particle.state)
        previous = merged.get(key)
        if previous is None:
            merged[key] = particle
        else:
            merged[key] = BeliefParticle(
                state=previous.state,
                weight=previous.weight + particle.weight,
                world_id=previous.world_id or particle.world_id,
                history_id=previous.history_id,
            )

    posterior = _normalize(merged.values())
    return ParticleUpdate(
        particles=posterior,
        generated=generated,
        matched=matched,
        deduplicated=len(survivors) - len(posterior),
    )
