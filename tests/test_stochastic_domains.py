from __future__ import annotations

import copy
from typing import Any

import pytest

from champions_practice.stochastic_domains import (
    DAMAGE_ROLL_BUCKETS,
    DAMAGE_ROLL_DOMAIN,
    DAMAGE_ROLL_SOURCE,
    DamageRollDomain,
    DamageRollOutcome,
    enumerate_showdown_damage_rolls,
)


def _raw_domain(*, base_damage: int = 137) -> dict[str, Any]:
    return {
        "domain": DAMAGE_ROLL_DOMAIN,
        "source": DAMAGE_ROLL_SOURCE,
        "base_damage": base_damage,
        "domain_size": DAMAGE_ROLL_BUCKETS,
        "exhaustive": True,
        "outcomes": [
            {
                "bucket": bucket,
                "damage": 100 - bucket,
                "rng_draw_count": 1,
            }
            for bucket in range(DAMAGE_ROLL_BUCKETS)
        ],
    }


class _FakeDamageRollWorker:
    def __init__(self, response: object):
        self.response = response
        self.calls = 0

    def enumerate_damage_rolls(
        self,
        *,
        state: dict[str, Any],
        base_damage: int,
    ) -> dict[str, Any]:
        self.calls += 1
        return copy.deepcopy(self.response)


def test_damage_roll_domain_accepts_all_16_ordered_buckets():
    worker = _FakeDamageRollWorker(_raw_domain())

    domain = enumerate_showdown_damage_rolls(
        worker,
        state={"serialized": True},
        base_damage=137,
    )

    assert isinstance(domain, DamageRollDomain)
    assert domain.exhaustive
    assert len(domain.outcomes) == 16
    assert tuple(outcome.bucket for outcome in domain.outcomes) == tuple(range(16))
    assert worker.calls == 1


def test_damage_roll_domain_allows_observationally_equivalent_damage_buckets():
    raw = _raw_domain(base_damage=1)
    for outcome in raw["outcomes"]:
        outcome["damage"] = 0
    domain = enumerate_showdown_damage_rolls(
        _FakeDamageRollWorker(raw),
        state={"serialized": True},
        base_damage=1,
    )
    assert domain.unique_damages == (0,)
    assert len(domain.outcomes) == 16


@pytest.mark.parametrize(
    "mutator",
    (
        lambda raw: raw.update(domain="future-domain"),
        lambda raw: raw.update(source="PythonFormula"),
        lambda raw: raw.update(base_damage=999),
        lambda raw: raw.update(domain_size=15),
        lambda raw: raw.update(exhaustive=False),
        lambda raw: raw["outcomes"].pop(),
        lambda raw: raw["outcomes"].__setitem__(
            15,
            {
                "bucket": 14,
                "damage": 86,
                "rng_draw_count": 1,
            },
        ),
        lambda raw: raw["outcomes"][0].update(rng_draw_count=2),
        lambda raw: raw["outcomes"][0].update(damage=-1),
    ),
)
def test_malformed_worker_damage_roll_domains_fail_closed(mutator):
    raw = _raw_domain()
    mutator(raw)
    with pytest.raises(RuntimeError):
        enumerate_showdown_damage_rolls(
            _FakeDamageRollWorker(raw),
            state={"serialized": True},
            base_damage=137,
        )


def test_extra_worker_damage_roll_metadata_fails_closed():
    raw = _raw_domain()
    raw["authority"] = "transition-impossible"
    with pytest.raises(RuntimeError, match="unexpected schema"):
        enumerate_showdown_damage_rolls(
            _FakeDamageRollWorker(raw),
            state={"serialized": True},
            base_damage=137,
        )


@pytest.mark.parametrize("base_damage", (True, False, 0, -1, 1.5, "137"))
def test_damage_roll_request_rejects_invalid_base_damage(base_damage):
    worker = _FakeDamageRollWorker(_raw_domain())
    with pytest.raises(ValueError, match="positive integer"):
        enumerate_showdown_damage_rolls(
            worker,
            state={"serialized": True},
            base_damage=base_damage,
        )
    assert worker.calls == 0


def test_damage_roll_outcome_rejects_non_integer_bucket_and_damage():
    with pytest.raises(ValueError):
        DamageRollOutcome(bucket=True, damage=10, rng_draw_count=1)
    with pytest.raises(ValueError):
        DamageRollOutcome(bucket=0, damage=True, rng_draw_count=1)


def test_damage_roll_domain_has_no_transition_authority_surface():
    domain = enumerate_showdown_damage_rolls(
        _FakeDamageRollWorker(_raw_domain()),
        state={"serialized": True},
        base_damage=137,
    )
    assert not hasattr(domain, "establishes_impossibility")
    assert not hasattr(domain, "establishes_reachability")
