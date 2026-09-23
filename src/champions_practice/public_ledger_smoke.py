"""Integration smoke for persistent public opponent HP/status evidence."""

from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM

SEED = "sodium,00000011000000120000001300000014"
P1_PREVIEW = "team 4156"
P2_PREVIEW = "team 3214"

OBSERVER_TEAM = SMOKE_TEAM.replace(
    "- Mystical Fire\n- Protect\n",
    "- Mystical Fire\n- Will-O-Wisp\n",
)


def main() -> None:
    if OBSERVER_TEAM == SMOKE_TEAM:
        raise SystemExit("ERROR: ledger fixture did not add Will-O-Wisp")

    with ShowdownSearchWorker() as worker:
        started = worker.start_session(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=SMOKE_TEAM,
            p2_team=OBSERVER_TEAM,
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
            p1_choice="move wideguard, move trickroom",
            p2_choice="move willowisp +1, move closecombat +1",
        )
        after_damage = worker.session_view(session_id, side="p2")["view"]
        active_armarouge = after_damage["opponent"]["active"][0]
        if active_armarouge["base_species"] != "Armarouge":
            raise SystemExit("ERROR: expected Armarouge in opponent slot one")
        if not 0 < active_armarouge["hp_percent"] < 100:
            raise SystemExit("ERROR: Armarouge did not take public damage")
        if active_armarouge["status"] != "brn":
            raise SystemExit("ERROR: Armarouge was not publicly burned")

        expected_hp = active_armarouge["hp_percent"]

        worker.choose_session(
            session_id,
            p1_choice="switch 3, move imprison",
            p2_choice="switch 3, switch 4",
        )
        after_switch = worker.session_view(session_id, side="p2")["view"]
        worker.close_session(session_id)

    revealed = {
        entry["species"]: entry
        for entry in after_switch["opponent"]["revealed"]
    }
    armarouge_public = revealed["Armarouge"]
    if armarouge_public["hp_percent"] != expected_hp:
        raise SystemExit(
            "ERROR: benched Armarouge lost its last-known public HP"
        )
    if armarouge_public["status"] != "brn":
        raise SystemExit(
            "ERROR: benched Armarouge lost its public status"
        )

    belief = build_public_opponent_belief(after_switch)
    armarouge_belief = next(
        pokemon
        for pokemon in belief.pokemon
        if pokemon.species == "Armarouge"
    )
    if armarouge_belief.active_slot is not None:
        raise SystemExit("ERROR: Armarouge should be benched")
    if armarouge_belief.hp_percent != expected_hp:
        raise SystemExit("ERROR: belief lost benched Armarouge HP")
    if armarouge_belief.status != "brn":
        raise SystemExit("ERROR: belief lost benched Armarouge status")

    print("Persistent public opponent ledger")
    print(f"Armarouge last-known HP: {expected_hp:.1f}%")
    print("Armarouge persistent status: brn")
    print("Source: sanitized Showdown-visible battle log only")
    print("Belief: benched HP/status retained after switch")
    print("RESULT: public bench evidence persists without hidden-state access")


if __name__ == "__main__":
    main()
