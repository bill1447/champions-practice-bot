"""Prove public beliefs are invariant to hidden opponent set changes."""

from __future__ import annotations

from champions_practice.beliefs import (
    build_public_opponent_belief,
    public_response_hypotheses,
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

        if standard_belief != variant_belief:
            raise SystemExit("ERROR: hidden opponent set changed the public belief")
        if standard_hypotheses != variant_hypotheses:
            raise SystemExit("ERROR: hidden opponent set changed response hypotheses")
        if len(standard_belief.pokemon) != 6:
            raise SystemExit("ERROR: opponent bring-four leaked through the belief")
        if len(standard_belief.active) != 2:
            raise SystemExit("ERROR: expected two public opposing active Pokemon")
        if len(standard_hypotheses) != 21:
            raise SystemExit("ERROR: unexpected initial public response family count")

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

        worker.close_session(standard_id)
        worker.close_session(variant_id)

    print("Public-information opponent belief")
    print("Public roster: 6 preview species; selected four remains hidden")
    print("Initial response families: 21 from unknown moves and possible switches")
    print("Reveals: used moves and Mega Stone entered the belief after public events")
    print("Anti-cheat: hidden moves, item, ability, nature, and stats changed nothing")
    print("Isolation: live CTS exact recommendation remains disabled")
    print("RESULT: belief inputs are derived only from the player's public view")


if __name__ == "__main__":
    main()
