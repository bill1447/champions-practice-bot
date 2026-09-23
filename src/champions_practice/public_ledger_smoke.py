"""Integration smoke for persistent public opponent HP/status evidence."""

from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM

SEED = "sodium,00000011000000120000001300000014"
P1_PREVIEW = "team 5614"
P2_PREVIEW = "team 3214"

OPPONENT_TEAM = (
    SMOKE_TEAM.replace("Rillaboom @ Sitrus Berry", "Rillaboom @ Flame Orb")
    .replace("- Wood Hammer\n", "- Swords Dance\n")
)


def main() -> None:
    if OPPONENT_TEAM == SMOKE_TEAM:
        raise SystemExit("ERROR: ledger fixture did not modify Rillaboom")

    with ShowdownSearchWorker() as worker:
        started = worker.start_session(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=OPPONENT_TEAM,
            p2_team=SMOKE_TEAM,
            p1_name="Opponent",
            p2_name="Observer",
            seed=SEED,
        )
        session_id = started["session_id"]
        worker.choose_session(
            session_id,
            p1_choice=P1_PREVIEW,
            p2_choice=P2_PREVIEW,
        )

        worker.choose_session(
            session_id,
            p1_choice="move swordsdance, move protect",
            p2_choice="move hypervoice, move protect",
        )
        after_damage = worker.session_view(session_id, side="p2")["view"]
        active_rillaboom = after_damage["opponent"]["active"][0]
        if active_rillaboom["base_species"] != "Rillaboom":
            raise SystemExit("ERROR: expected Rillaboom in opponent slot one")
        if not 0 < active_rillaboom["hp_percent"] < 100:
            raise SystemExit("ERROR: Rillaboom did not take public damage")
        if active_rillaboom["status"] != "brn":
            raise SystemExit("ERROR: Flame Orb burn was not publicly observed")

        expected_hp = active_rillaboom["hp_percent"]

        worker.choose_session(
            session_id,
            p1_choice="switch 3, move protect",
            p2_choice="move protect, move protect",
        )
        after_switch = worker.session_view(session_id, side="p2")["view"]
        worker.close_session(session_id)

    revealed = {
        entry["species"]: entry
        for entry in after_switch["opponent"]["revealed"]
    }
    rillaboom_public = revealed["Rillaboom"]
    if rillaboom_public["hp_percent"] != expected_hp:
        raise SystemExit(
            "ERROR: benched Rillaboom lost its last-known public HP"
        )
    if rillaboom_public["status"] != "brn":
        raise SystemExit(
            "ERROR: benched Rillaboom lost its public status"
        )

    belief = build_public_opponent_belief(after_switch)
    rillaboom_belief = next(
        pokemon
        for pokemon in belief.pokemon
        if pokemon.species == "Rillaboom"
    )
    if rillaboom_belief.active_slot is not None:
        raise SystemExit("ERROR: Rillaboom should be benched")
    if rillaboom_belief.hp_percent != expected_hp:
        raise SystemExit("ERROR: belief lost benched Rillaboom HP")
    if rillaboom_belief.status != "brn":
        raise SystemExit("ERROR: belief lost benched Rillaboom status")

    print("Persistent public opponent ledger")
    print(f"Rillaboom last-known HP: {expected_hp:.1f}%")
    print("Rillaboom persistent status: brn")
    print("Source: sanitized Showdown-visible battle log only")
    print("Belief: benched HP/status retained after switch")
    print("RESULT: public bench evidence persists without hidden-state access")


if __name__ == "__main__":
    main()
