"""Queue continuation may not turn sampled misses into exclusions."""

from types import SimpleNamespace
from time import perf_counter

import pytest

from champions_practice.observation_beliefs import BeliefParticle, ParticleUpdate
from champions_practice.queue_shadow import condition_queue_histories
from champions_practice.search_worker import FORCED_WAIT_CHOICE


def run(monkeypatch, *, choices, impossible=False, unsupported=False):
    update = ParticleUpdate(
        particles=(), generated=1, matched=0, deduplicated=0,
        sampled_unresolved_world_ids=("queue-a",),
        unsupported_public_evidence=("unknown-event",) if unsupported else (),
    )
    engine = SimpleNamespace(
        _condition_adaptive=lambda *args, **kwargs: update,
        rng_sample_batches=(1,), previews={},
    )
    worker = SimpleNamespace(legal_choices=lambda **kwargs: choices)
    calls = []

    def probe(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            leaves_examined=3,
            evidence=SimpleNamespace(status="unresolved", establishes_impossibility=impossible),
        )

    monkeypatch.setattr("champions_practice.queue_shadow.finite_public_transition_reachability", probe)
    result = condition_queue_histories(
        worker, engine,
        particles=(BeliefParticle(state={}, weight=1, world_id="queue-a"),),
        own_choice="switch 4, pass",
        before={"phase": "switch", "request": {"forceSwitch": [True, False]}},
        after={}, deadline=perf_counter() + 5,
    )
    return result, calls


@pytest.mark.parametrize("choices", ([], ["move 1"], [FORCED_WAIT_CHOICE, "move 1"]))
def test_pause_with_new_opponent_choices_cannot_use_forced_wait_probe(monkeypatch, choices):
    result, calls = run(monkeypatch, choices=choices)
    assert calls == []
    assert result.sampled_unresolved_world_ids == ("queue-a",)
    assert not result.particles


def test_incomplete_finite_probe_cannot_exclude_queue_class(monkeypatch):
    result, calls = run(monkeypatch, choices=[FORCED_WAIT_CHOICE])
    assert calls[0]["p1_choice"] == FORCED_WAIT_CHOICE
    assert result.sampled_unresolved_world_ids == ("queue-a",)
    assert result.exhaustively_excluded_world_ids == ()
    assert not result.particles


def test_complete_negative_evidence_excludes_only_sampled_history(monkeypatch):
    result, calls = run(monkeypatch, choices=[FORCED_WAIT_CHOICE], impossible=True)
    assert len(calls) == 1
    assert result.exhaustively_excluded_world_ids == ("queue-a",)
    assert result.sampled_unresolved_world_ids == ()
    assert not result.particles


def test_unsupported_public_evidence_blocks_continuation_probe(monkeypatch):
    result, calls = run(monkeypatch, choices=[FORCED_WAIT_CHOICE], unsupported=True)
    assert calls == []
    assert result.unsupported_public_evidence == ("unknown-event",)
