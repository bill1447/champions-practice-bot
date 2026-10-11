from copy import deepcopy

import pytest

from champions_practice.observation_beliefs import BeliefParticle
from champions_practice.queue_retention import pending_queue_key, retain_pending_queues


def particle(world="set-a", move="partingshot", target=1, weight=1, **action):
    return BeliefParticle(
        state={"queue": [{"choice": "move", "moveid": move, "targetLoc": target, **action}]},
        weight=weight,
        world_id=world,
    )


def test_every_set_move_and_target_class_survives_even_with_tiny_mass():
    batch = (
        particle(weight=1000),
        particle(target=2, weight=0.001),
        particle(move="darkestlariat"),
        particle(world="set-b"),
    )
    kept = retain_pending_queues(batch, limit=4)
    assert kept.unresolved_reason is None
    assert {(p.world_id, pending_queue_key(p.state)) for p in kept.particles} == {
        (p.world_id, pending_queue_key(p.state)) for p in batch
    }
    assert sum(p.weight for p in kept.particles) == pytest.approx(1)


def test_capacity_exhaustion_retains_no_installable_batch():
    result = retain_pending_queues((particle(), particle(target=2)), limit=1)
    assert result.classes == 2
    assert result.particles == ()
    assert result.unresolved_reason == "pending-queue-capacity"


def test_rng_sample_limit_is_separate_and_native_states_are_not_modified():
    batch = tuple(particle(weight=i + 1) for i in range(10)) + (particle(world="set-b"),)
    original = deepcopy(batch)
    kept = retain_pending_queues(batch, limit=5, samples_per_class=2)
    assert len(kept.particles) == 3
    assert batch == original
    assert sum(p.weight for p in kept.particles if p.world_id == "set-a") == pytest.approx(55 / 56)


def test_native_order_and_transformation_flags_are_not_merged():
    batch = (particle(speed=1), particle(speed=2), particle(mega=True))
    assert retain_pending_queues(batch).classes == 3


@pytest.mark.parametrize(
    "state", ({}, {"queue": None}, {"queue": [None]}, {"queue": [{"speed": float("nan")}]})
)
def test_unknown_queue_or_nonfinite_values_are_unresolved(state):
    result = retain_pending_queues((BeliefParticle(state=state, weight=1, world_id="a"),))
    assert result.unresolved_reason == "invalid-native-queue"
    assert not result.particles
