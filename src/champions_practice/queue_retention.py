"""Offline retention of native pending-command witnesses.

This preserves every queue class in a positive batch, not every possible hidden
history. It has no production admission or exclusion authority. RNG histories
within a class remain bounded samples; an oversized discrete domain is unresolved.
"""

from dataclasses import dataclass, replace
import json
import math
import random

from champions_practice.observation_beliefs import BeliefParticle


@dataclass(frozen=True)
class QueueRetention:
    particles: tuple[BeliefParticle, ...]
    classes: int
    unresolved_reason: str | None = None


def pending_queue_key(state: dict) -> str:
    queue = state.get("queue")
    if not isinstance(queue, list) or any(not isinstance(action, dict) for action in queue):
        raise ValueError("native queue is missing or malformed")
    # Preserve the entire serialized action, including targets, ordering,
    # transformation flags and native speed. Unknown fields remain distinct.
    return json.dumps(queue, sort_keys=True, separators=(",", ":"), allow_nan=False)


def retain_pending_queues(
    particles: tuple[BeliefParticle, ...],
    *,
    limit: int = 24,
    samples_per_class: int = 1,
    seed: int = 0,
) -> QueueRetention:
    if (
        type(limit) is not int
        or limit < 1
        or type(samples_per_class) is not int
        or samples_per_class < 1
    ):
        raise ValueError("positive integer retention bounds required")
    groups = {}
    for particle in particles:
        if not particle.world_id or not math.isfinite(particle.weight) or particle.weight <= 0:
            return QueueRetention((), len(groups), "invalid-witness-metadata")
        try:
            key = (particle.world_id, pending_queue_key(particle.state))
        except (ValueError, TypeError):
            return QueueRetention((), len(groups), "invalid-native-queue")
        groups.setdefault(key, []).append(particle)
    if len(groups) > limit:
        return QueueRetention((), len(groups), "pending-queue-capacity")
    if not groups:
        return QueueRetention((), 0, "no-positive-witnesses")
    total_mass = sum(p.weight for p in particles)
    if not math.isfinite(total_mass):
        return QueueRetention((), len(groups), "invalid-witness-metadata")
    retained = []
    rng = random.Random(seed)
    # One slot per set/queue class is mandatory. Extra stochastic samples have
    # a separate bound and can only consume capacity after every class fits.
    extra = limit - len(groups)
    for key in sorted(groups):
        group = groups[key]
        count = 1 + min(samples_per_class - 1, len(group) - 1, extra)
        extra -= count - 1
        available = list(group)
        chosen = []
        for _ in range(count):
            weights = [p.weight for p in available]
            index = rng.choices(range(len(available)), weights=weights, k=1)[0]
            chosen.append(available.pop(index))
        mass = sum(p.weight for p in group) / total_mass
        retained.extend(replace(p, weight=mass / count) for p in chosen)
    return QueueRetention(tuple(retained), len(groups))
