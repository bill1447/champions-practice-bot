"""Observation-conditioned exact belief particles."""

from __future__ import annotations

import copy
import json
import random
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
    """Return a stable signature for mechanically relevant public information.

    Reconstructed Showdown states may use different display names from the live
    session. Names do not affect the battle state, so normalize a winner to its
    player/opponent role and remove cosmetic names before comparing observations.
    """
    normalized = copy.deepcopy(view)
    player = normalized.get("player")
    opponent = normalized.get("opponent")
    player_name = player.get("name") if isinstance(player, dict) else None
    opponent_name = opponent.get("name") if isinstance(opponent, dict) else None

    winner = normalized.get("winner")
    if isinstance(winner, str):
        if winner == player_name:
            normalized["winner"] = "player"
        elif winner == opponent_name:
            normalized["winner"] = "opponent"

    if isinstance(player, dict):
        player.pop("name", None)
    if isinstance(opponent, dict):
        opponent.pop("name", None)

    request = normalized.get("request")
    if isinstance(request, dict):
        request_side = request.get("side")
        if isinstance(request_side, dict):
            request_side.pop("name", None)

    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


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


def resample_particles(
    particles: tuple[BeliefParticle, ...],
    *,
    limit: int,
    seed: int = 0,
) -> tuple[BeliefParticle, ...]:
    """Bound a posterior with deterministic systematic resampling.

    Resampling operates only on already-conditioned particles. It never consults
    the live battle state or hidden opponent information.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")

    normalized = _normalize(particles)
    if len(normalized) <= limit:
        return normalized

    rng = random.Random(seed)
    step = 1.0 / limit
    target = rng.random() * step
    index = 0
    cumulative = normalized[0].weight
    counts: dict[str, tuple[BeliefParticle, int]] = {}

    for sample_index in range(limit):
        position = target + sample_index * step
        while position > cumulative and index < len(normalized) - 1:
            index += 1
            cumulative += normalized[index].weight
        particle = normalized[index]
        key = _state_key(particle.state)
        previous = counts.get(key)
        if previous is None:
            counts[key] = (particle, 1)
        else:
            counts[key] = (previous[0], previous[1] + 1)

    return tuple(
        BeliefParticle(
            state=particle.state,
            weight=count / limit,
            world_id=particle.world_id,
            history_id=particle.history_id,
        )
        for particle, count in counts.values()
    )


def resample_particles_by_world(
    particles: tuple[BeliefParticle, ...],
    *,
    limit: int,
    seed: int = 0,
) -> tuple[BeliefParticle, ...]:
    """Bound particles while preserving surviving hidden-world diversity."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    normalized = _normalize(particles)
    if len(normalized) <= limit:
        return normalized

    groups: dict[str, list[BeliefParticle]] = {}
    for particle in normalized:
        key = particle.world_id or "<unlabeled>"
        groups.setdefault(key, []).append(particle)

    if len(groups) > limit:
        return resample_particles(normalized, limit=limit, seed=seed)

    masses = {
        key: sum(particle.weight for particle in group)
        for key, group in groups.items()
    }
    slots = {key: 1 for key in groups}
    remaining = limit - len(groups)
    if remaining > 0:
        total_mass = sum(masses.values())
        raw = {
            key: remaining * masses[key] / total_mass
            for key in groups
        }
        for key in groups:
            slots[key] += int(raw[key])
        leftover = limit - sum(slots.values())
        order = sorted(
            groups,
            key=lambda key: (-(raw[key] - int(raw[key])), -masses[key], key),
        )
        for key in order[:leftover]:
            slots[key] += 1

    sampled: list[BeliefParticle] = []
    for offset, key in enumerate(sorted(groups)):
        group = tuple(groups[key])
        group_mass = masses[key]
        local = _normalize(group)
        chosen = resample_particles(
            local,
            limit=slots[key],
            seed=seed + offset + 1,
        )
        sampled.extend(
            BeliefParticle(
                state=particle.state,
                weight=particle.weight * group_mass,
                world_id=particle.world_id,
                history_id=particle.history_id,
            )
            for particle in chosen
        )
    return _normalize(sampled)


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
                    "view_side": ai_side,
                }
                if previews is not None:
                    branch["previews"] = previews
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
            view = result.get("view")
            if not isinstance(view, dict):
                view = worker.state_view(
                    state=state,
                    side=ai_side,
                    previews=previews,
                )
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
