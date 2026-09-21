"""Prove public beliefs and materialized worlds ignore hidden opponent truth."""

from __future__ import annotations

import subprocess
from pathlib import Path

from champions_practice.beliefs import (
    build_public_opponent_belief,
    public_response_hypotheses,
)
from champions_practice.belief_worlds import (
    PublicSetCandidate,
    materialize_public_belief_worlds,
)
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM

SEED = "sodium,00000001000000020000000300000004"

ORIGINAL_METAGROSS = """Metagross @ Metagrossite
Ability: Clear Body
Level: 50
EVs: 2 HP / 32 Atk / 32 Spe
Adamant Nature
- Psychic Fangs
- Steel Roller
- Stomping Tantrum
- Protect
"""

HIDDEN_VARIANT_METAGROSS = """Metagross @ Leftovers
Ability: Light Metal
Level: 50
EVs: 32 HP / 32 Def / 2 SpD
Careful Nature
- Bullet Punch
- Zen Headbutt
- Ice Punch
- Protect
"""


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


def _public_priors() -> dict[str, tuple[PublicSetCandidate, ...]]:
    """Small explicit public prior pool for the integration fixture."""
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


def _hidden_variant_team() -> str:
    variant = SMOKE_TEAM.replace(ORIGINAL_METAGROSS, HIDDEN_VARIANT_METAGROSS)
    if variant == SMOKE_TEAM:
        raise SystemExit("ERROR: hidden-set fixture did not replace Metagross")
    return variant


def _start_turn_one(worker: ShowdownSearchWorker, opponent_team: str) -> str:
    started = worker.start_session(
        battle_format=CHAMPIONS_FORMAT,
        p1_team=SMOKE_TEAM,
        p2_team=opponent_team,
        p1_name="Human",
        p2_name="AI",
        seed=SEED,
    )
    session_id = started["session_id"]
    worker.choose_session(
        session_id,
        p1_choice="team 1235",
        p2_choice="team 6412",
    )
    return session_id


def _validate_world_teams(worlds) -> int:
    root = Path(__file__).resolve().parents[2]
    showdown = root / "external" / "pokemon-showdown"
    cli = showdown / "pokemon-showdown"
    unique_teams = {world.team_text for world in worlds}
    for team_text in unique_teams:
        result = subprocess.run(
            ["node", str(cli), "validate-team", CHAMPIONS_FORMAT],
            cwd=showdown,
            input=team_text,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise SystemExit(f"ERROR: Showdown rejected a materialized world: {detail}")
    return len(unique_teams)


def main() -> None:
    with ShowdownSearchWorker() as worker:
        standard_id = _start_turn_one(worker, SMOKE_TEAM)
        variant_id = _start_turn_one(worker, _hidden_variant_team())

        standard_view = worker.session_view(standard_id)["view"]
        variant_view = worker.session_view(variant_id)["view"]
        standard_state = worker.session_snapshot(standard_id)["state"]
        variant_state = worker.session_snapshot(variant_id)["state"]

        if standard_state == variant_state:
            raise SystemExit("ERROR: hidden-set fixtures unexpectedly have equal states")
        if standard_view != variant_view:
            raise SystemExit("ERROR: hidden opponent set changed the public view")

        standard_belief = build_public_opponent_belief(standard_view)
        variant_belief = build_public_opponent_belief(variant_view)
        standard_hypotheses = public_response_hypotheses(standard_belief)
        variant_hypotheses = public_response_hypotheses(variant_belief)
        priors = _public_priors()
        standard_worlds = materialize_public_belief_worlds(
            standard_belief,
            priors,
            limit=32,
        )
        variant_worlds = materialize_public_belief_worlds(
            variant_belief,
            priors,
            limit=32,
        )

        if standard_belief != variant_belief:
            raise SystemExit("ERROR: hidden opponent set changed the public belief")
        if standard_hypotheses != variant_hypotheses:
            raise SystemExit("ERROR: hidden opponent set changed response hypotheses")
        if standard_worlds != variant_worlds:
            raise SystemExit("ERROR: hidden opponent set changed materialized worlds")
        if len(standard_belief.pokemon) != 6:
            raise SystemExit("ERROR: opponent bring-four leaked through the belief")
        if len(standard_belief.active) != 2:
            raise SystemExit("ERROR: expected two public opposing active Pokemon")
        if len(standard_hypotheses) != 21:
            raise SystemExit("ERROR: unexpected initial public response family count")
        if len(standard_worlds) != 12:
            raise SystemExit(
                f"ERROR: expected 12 initial public-prior worlds, got {len(standard_worlds)}"
            )

        legal_team_count = _validate_world_teams(standard_worlds)

        worker.choose_session(
            standard_id,
            p1_choice="move followme, move rockslide",
            p2_choice="move psychicfangs +1 mega, move wideguard",
        )
        revealed = build_public_opponent_belief(
            worker.session_view(standard_id)["view"]
        )
        metagross = next(
            pokemon for pokemon in revealed.pokemon if pokemon.species == "Metagross"
        )
        armarouge = next(
            pokemon for pokemon in revealed.pokemon if pokemon.species == "Armarouge"
        )
        if metagross.revealed_moves != ("psychicfangs",):
            raise SystemExit("ERROR: publicly used Metagross move was not recorded")
        if metagross.revealed_items != ("metagrossite",):
            raise SystemExit("ERROR: publicly revealed Mega Stone was not recorded")
        if armarouge.revealed_moves != ("wideguard",):
            raise SystemExit("ERROR: publicly used Armarouge move was not recorded")

        revealed_worlds = materialize_public_belief_worlds(
            revealed,
            priors,
            limit=32,
        )
        if len(revealed_worlds) != 6:
            raise SystemExit(
                f"ERROR: expected 6 worlds after reveal filtering, got {len(revealed_worlds)}"
            )
        if {
            world.set_for_species("Metagross").label for world in revealed_worlds
        } != {"mega"}:
            raise SystemExit("ERROR: reveals did not eliminate incompatible Metagross priors")

        worker.close_session(standard_id)
        worker.close_session(variant_id)

    print("Public-information opponent belief")
    print("Public roster: 6 preview species; selected four remains hidden")
    print("Initial response families: 21 from unknown moves and possible switches")
    print(
        "Materialized worlds: "
        f"{len(standard_worlds)} weighted worlds from {legal_team_count} legal team sets"
    )
    print("Reveal filtering: Metagross evidence reduced the world set from 12 to 6")
    print("Reveals: used moves and Mega Stone entered the belief after public events")
    print("Anti-cheat: hidden moves, item, ability, nature, and stats changed nothing")
    print("Isolation: live CTS exact recommendation remains disabled")
    print("RESULT: beliefs and opponent worlds derive only from public view + public priors")


if __name__ == "__main__":
    main()
