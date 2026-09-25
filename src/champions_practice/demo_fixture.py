"""Fixed public-information fixture for the first playable local demo."""

from __future__ import annotations

from champions_practice.belief_worlds import PublicSetCandidate
from champions_practice.teams import SMOKE_TEAM

DEMO_PRESET_NAME = "Current roster mirror"
DEMO_AI_TEAM = SMOKE_TEAM
DEMO_HUMAN_TEAM = SMOKE_TEAM

# Lead Sneasler + Indeedee-F, with Gardevoir + Rillaboom in back.
# This is intentionally a sane fixed demo preview, not a claim of optimal preview play.
DEMO_AI_PREVIEW_CHOICE = "team 2135"


def _candidate(
    species: str,
    item: str,
    ability: str,
    nature: str,
    stat_points: tuple[tuple[str, int], ...],
    moves: tuple[str, ...],
    *,
    label: str = "standard",
    weight: float = 1.0,
) -> PublicSetCandidate:
    return PublicSetCandidate(
        species=species,
        item=item,
        ability=ability,
        nature=nature,
        stat_points=stat_points,
        moves=moves,
        label=label,
        weight=weight,
    )


def demo_public_priors() -> dict[str, tuple[PublicSetCandidate, ...]]:
    """Return the explicit public prior pool used by the v0 mirror-match demo."""
    return {
        "Indeedee-F": (
            _candidate(
                "Indeedee-F",
                "Colbur Berry",
                "Psychic Surge",
                "Relaxed",
                (("hp", 32), ("def", 32), ("spe", 2)),
                ("Psychic", "Follow Me", "Trick Room", "Imprison"),
            ),
        ),
        "Sneasler": (
            _candidate(
                "Sneasler",
                "Psychic Seed",
                "Unburden",
                "Adamant",
                (("hp", 2), ("atk", 32), ("spe", 32)),
                ("Close Combat", "Dire Claw", "Rock Slide", "Protect"),
            ),
        ),
        "Gardevoir": (
            _candidate(
                "Gardevoir",
                "Gardevoirite",
                "Trace",
                "Modest",
                (("hp", 4), ("spa", 32), ("spe", 30)),
                ("Expanding Force", "Hyper Voice", "Mystical Fire", "Protect"),
            ),
        ),
        "Armarouge": (
            _candidate(
                "Armarouge",
                "Life Orb",
                "Flash Fire",
                "Quiet",
                (("hp", 32), ("spa", 32), ("spd", 2)),
                ("Expanding Force", "Armor Cannon", "Wide Guard", "Protect"),
            ),
        ),
        "Rillaboom": (
            _candidate(
                "Rillaboom",
                "Sitrus Berry",
                "Grassy Surge",
                "Careful",
                (("hp", 32), ("atk", 2), ("spd", 32)),
                ("Grassy Glide", "Wood Hammer", "High Horsepower", "Protect"),
            ),
        ),
        "Metagross": (
            _candidate(
                "Metagross",
                "Metagrossite",
                "Clear Body",
                "Adamant",
                (("hp", 2), ("atk", 32), ("spe", 32)),
                ("Psychic Fangs", "Steel Roller", "Stomping Tantrum", "Protect"),
                label="mega",
                weight=2.0,
            ),
            _candidate(
                "Metagross",
                "Leftovers",
                "Light Metal",
                "Careful",
                (("hp", 32), ("def", 32), ("spd", 2)),
                ("Bullet Punch", "Zen Headbutt", "Ice Punch", "Protect"),
                label="bulky",
                weight=1.0,
            ),
        ),
    }
