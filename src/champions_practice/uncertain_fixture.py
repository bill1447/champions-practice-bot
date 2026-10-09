"""Deterministic, synthetic spread-uncertainty benchmark fixture.

This is deliberately NOT a VGCPastes-derived corpus or competitive-strength
benchmark. Opponent truth is selected offline and passed only to battle.start;
the bot receives the same fixed three-candidate prior pool for every game.
"""

from __future__ import annotations

from dataclasses import replace

from champions_practice.belief_worlds import PublicSetCandidate
from champions_practice.demo_fixture import demo_public_priors

FIXTURE_ID = "synthetic-spread-uncertainty-v1"
SOURCE_LABEL = "synthetic-in-repository-not-vgcpastes"

# Each profile uses exactly 66 Champions Stat Points with <=32 in one stat.
# Same legal moves/items isolate unknown nature/spread as the experimental axis.
# The first choice for every species is the existing smoke-team set.
_ALTERNATIVES: dict[
    str,
    tuple[tuple[str, tuple[tuple[str, int], ...]], ...],
] = {
    "Indeedee-F": (
        ("Modest", (("hp", 2), ("spa", 32), ("spe", 32))),
        ("Calm", (("hp", 32), ("def", 2), ("spd", 32))),
    ),
    "Sneasler": (
        ("Jolly", (("hp", 2), ("atk", 32), ("spe", 32))),
        ("Adamant", (("hp", 32), ("atk", 32), ("spd", 2))),
    ),
    "Gardevoir": (
        ("Timid", (("hp", 2), ("spa", 32), ("spe", 32))),
        ("Modest", (("hp", 32), ("spa", 32), ("spd", 2))),
    ),
    "Armarouge": (
        ("Modest", (("hp", 2), ("spa", 32), ("spe", 32))),
        ("Quiet", (("hp", 32), ("def", 2), ("spd", 32))),
    ),
    "Rillaboom": (
        ("Adamant", (("hp", 2), ("atk", 32), ("spe", 32))),
        ("Impish", (("hp", 32), ("def", 32), ("atk", 2))),
    ),
    "Metagross": (
        ("Jolly", (("hp", 2), ("atk", 32), ("spe", 32))),
        ("Adamant", (("hp", 32), ("atk", 32), ("spd", 2))),
    ),
}


def public_priors() -> dict[str, tuple[PublicSetCandidate, ...]]:
    """Identical public pool regardless of the selected true opponent team."""
    base = demo_public_priors()
    result: dict[str, tuple[PublicSetCandidate, ...]] = {}
    for species, profiles in _ALTERNATIVES.items():
        original = replace(base[species][0], label="baseline", weight=1.0)
        candidates = [original]
        for index, (nature, points) in enumerate(profiles, start=1):
            candidates.append(
                replace(
                    original,
                    nature=nature,
                    stat_points=points,
                    label=f"synthetic-{index}",
                    weight=1.0,
                )
            )
        result[species] = tuple(candidates)
    return result


def opponent_selection(seed: int, game_index: int) -> tuple[int, ...]:
    """Stable variation that covers all three sets per species in eight games."""
    if game_index < 0:
        raise ValueError("game_index must be nonnegative")
    return tuple(
        (
            game_index // (3 if species_index % 2 else 1)
            + species_index + seed % 3
        ) % 3
        for species_index in range(len(_ALTERNATIVES))
    )


def opponent_team(seed: int, game_index: int) -> str:
    """Offline truth only. Never derive priors from this chosen team."""
    pool = public_priors()
    variants = opponent_selection(seed, game_index)
    return "\n\n".join(
        pool[species][choice].team_text
        for (species, choice) in zip(pool, variants, strict=True)
    ) + "\n"
