"""Isolated finite stochastic domains backed directly by pinned Showdown.

These types describe mechanics primitives only. They do not establish that a
complete public transition is reachable or impossible, and they have no live
belief-admission or recovery-install operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


DAMAGE_ROLL_DOMAIN = "showdown-battle-randomizer-v1"
DAMAGE_ROLL_SOURCE = "Battle#randomizer"
DAMAGE_ROLL_BUCKETS = 16
JS_MAX_SAFE_INTEGER = 2**53 - 1


class DamageRollWorker(Protocol):
    def enumerate_damage_rolls(
        self,
        *,
        state: dict[str, Any],
        base_damage: int,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DamageRollOutcome:
    """One equivalence class of Showdown's finite random(16) damage factor."""

    bucket: int
    damage: int
    rng_draw_count: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.bucket, bool)
            or not isinstance(self.bucket, int)
            or self.bucket not in range(DAMAGE_ROLL_BUCKETS)
        ):
            raise ValueError("damage-roll bucket must be an integer from 0 through 15")
        if (
            isinstance(self.damage, bool)
            or not isinstance(self.damage, int)
            or self.damage < 0
        ):
            raise ValueError("damage-roll damage must be a non-negative integer")
        if (
            isinstance(self.rng_draw_count, bool)
            or not isinstance(self.rng_draw_count, int)
            or self.rng_draw_count != 1
        ):
            raise ValueError(
                "each damage-roll bucket must consume exactly one PRNG draw"
            )


@dataclass(frozen=True)
class DamageRollDomain:
    """Exhaustive finite output of the pinned Showdown damage randomizer.

    Exhaustive here is intentionally scoped only to Battle#randomizer's
    random(16) dimension for one supplied base-damage value. It is not
    transition-level negative authority.
    """

    base_damage: int
    outcomes: tuple[DamageRollOutcome, ...]
    domain: str = DAMAGE_ROLL_DOMAIN
    source: str = DAMAGE_ROLL_SOURCE
    exhaustive: bool = True

    def __post_init__(self) -> None:
        if (
            isinstance(self.base_damage, bool)
            or not isinstance(self.base_damage, int)
            or self.base_damage < 1
            or self.base_damage > JS_MAX_SAFE_INTEGER
        ):
            raise ValueError("base_damage must be a positive safe integer")
        if self.domain != DAMAGE_ROLL_DOMAIN:
            raise ValueError("unexpected damage-roll domain identifier")
        if self.source != DAMAGE_ROLL_SOURCE:
            raise ValueError("unexpected damage-roll mechanics source")
        if self.exhaustive is not True:
            raise ValueError("damage-roll domain must be explicitly exhaustive")
        if len(self.outcomes) != DAMAGE_ROLL_BUCKETS:
            raise ValueError("damage-roll domain must contain exactly 16 buckets")
        buckets = tuple(outcome.bucket for outcome in self.outcomes)
        if buckets != tuple(range(DAMAGE_ROLL_BUCKETS)):
            raise ValueError(
                "damage-roll outcomes must contain buckets 0 through 15 in order"
            )

    @property
    def damages(self) -> tuple[int, ...]:
        return tuple(outcome.damage for outcome in self.outcomes)

    @property
    def unique_damages(self) -> tuple[int, ...]:
        return tuple(sorted(set(self.damages)))


def _parse_damage_roll_domain(
    raw: object,
    *,
    requested_base_damage: int,
) -> DamageRollDomain:
    if not isinstance(raw, dict):
        raise RuntimeError("Showdown damage-roll response must be a dictionary")
    expected_keys = {
        "domain",
        "source",
        "base_damage",
        "domain_size",
        "exhaustive",
        "outcomes",
    }
    if set(raw) != expected_keys:
        raise RuntimeError("Showdown damage-roll response has an unexpected schema")
    if raw["domain"] != DAMAGE_ROLL_DOMAIN:
        raise RuntimeError("Showdown returned an unknown damage-roll domain")
    if raw["source"] != DAMAGE_ROLL_SOURCE:
        raise RuntimeError("Showdown returned an unknown damage-roll source")
    if (
        isinstance(raw["base_damage"], bool)
        or not isinstance(raw["base_damage"], int)
        or raw["base_damage"] != requested_base_damage
    ):
        raise RuntimeError("Showdown damage-roll response changed base_damage")
    if (
        isinstance(raw["domain_size"], bool)
        or not isinstance(raw["domain_size"], int)
        or raw["domain_size"] != DAMAGE_ROLL_BUCKETS
    ):
        raise RuntimeError("Showdown damage-roll domain is not exactly 16 buckets")
    if raw["exhaustive"] is not True:
        raise RuntimeError("Showdown did not mark the damage-roll domain exhaustive")

    raw_outcomes = raw["outcomes"]
    if not isinstance(raw_outcomes, list):
        raise RuntimeError("Showdown damage-roll outcomes must be a list")

    outcomes: list[DamageRollOutcome] = []
    for index, value in enumerate(raw_outcomes):
        if not isinstance(value, dict) or set(value) != {
            "bucket",
            "damage",
            "rng_draw_count",
        }:
            raise RuntimeError(
                f"Showdown damage-roll outcome {index} has an invalid schema"
            )
        try:
            outcome = DamageRollOutcome(
                bucket=value["bucket"],
                damage=value["damage"],
                rng_draw_count=value["rng_draw_count"],
            )
        except ValueError as error:
            raise RuntimeError(
                f"Showdown damage-roll outcome {index} is invalid: {error}"
            ) from error
        outcomes.append(outcome)

    try:
        return DamageRollDomain(
            base_damage=requested_base_damage,
            outcomes=tuple(outcomes),
            domain=raw["domain"],
            source=raw["source"],
            exhaustive=raw["exhaustive"],
        )
    except ValueError as error:
        raise RuntimeError(f"Showdown damage-roll domain is invalid: {error}") from error


def enumerate_showdown_damage_rolls(
    worker: DamageRollWorker,
    *,
    state: dict[str, Any],
    base_damage: int,
) -> DamageRollDomain:
    """Enumerate all 16 pinned Showdown damage-randomizer buckets.

    This function deliberately returns no ReachabilityResult. Complete coverage
    of this primitive is not complete coverage of accuracy, crits, targeting,
    multihit count, secondary effects, speed ties, or any other transition RNG.
    """

    if not isinstance(state, dict) or not state:
        raise ValueError("damage-roll enumeration requires a serialized state")
    if (
        isinstance(base_damage, bool)
        or not isinstance(base_damage, int)
        or base_damage < 1
        or base_damage > JS_MAX_SAFE_INTEGER
    ):
        raise ValueError("base_damage must be a positive safe integer")

    raw = worker.enumerate_damage_rolls(
        state=state,
        base_damage=base_damage,
    )
    return _parse_damage_roll_domain(
        raw,
        requested_base_damage=base_damage,
    )
