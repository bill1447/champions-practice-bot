"""Pinned-native controls for scoped approximate joint mechanics, not full support."""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog, observe
from champions_practice.agent_v2.joint import Part, Response, damage_range, parse, simulate
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.diversity_league import team_text
from champions_practice.search_worker import ShowdownSearchWorker, TeamValidationWorker


ROOT = Path(__file__).resolve().parents[1]


def main():
    metadata = PublicCatalog.load(ROOT)
    support = team_text(("Metagross", "Indeedee-F", "Garchomp", "Dragonite", "Pelipper", "Rotom-Wash"))
    support = support.replace("Steel Roller", "Bullet Punch")
    spread = team_text(("Pelipper", "Metagross", "Garchomp", "Dragonite", "Indeedee-F", "Rotom-Wash"))
    spread = spread.replace("Weather Ball", "Surf")
    retarget = team_text(("Gardevoir", "Metagross", "Garchomp", "Dragonite", "Pelipper", "Rotom-Wash"))
    retarget = retarget.replace("Mystical Fire", "Moonblast")
    foe = team_text(("Garchomp", "Metagross", "Dragonite", "Rotom-Wash", "Incineroar", "Venusaur"))
    with TeamValidationWorker(ROOT) as validator:
        for team in (support, spread, foe, retarget):
            assert validator.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=team)["valid"]
    result = {"catalog_sha256": metadata.fingerprint, "scope": "selected simple native controls, not global mechanics certification"}
    with ShowdownSearchWorker(ROOT) as worker:
        def opening(team, preview, enemy_preview, index):
            seed = "sodium," + hashlib.sha256(f"joint-native-control:{index}".encode()).hexdigest()
            session = worker.start_session(battle_format=CHAMPIONS_FORMAT, p1_team=team,
                p2_team=foe, p1_name="P1", p2_name="P2", seed=seed)["session_id"]
            worker.choose_session(session, p1_choice=preview, p2_choice=enemy_preview)
            return session, worker.session_view(session, side="p1")["view"]

        def advance(session, own, enemy):
            assert own in worker.session_public_choices(session, side="p1"), str(worker.session_public_choices(session, side="p1")[:8])
            assert enemy in worker.session_public_choices(session, side="p2")
            worker.choose_session(session, p1_choice=own, p2_choice=enemy)
            return worker.session_view(session, side="p1")["view"]

        repetitions = []
        for index in range(8):
            session, before = opening(support, "team 1345", "team 3142", index)
            try:
                first = advance(session, "move protect, move protect", "move dragonclaw +1, move dragonclaw +2")
                assert [m["hp"] for m in before["player"]["active_details"]] == [m["hp"] for m in first["player"]["active_details"]]
                board = observe(first, worker.session_public_choices(session, side="p1"), deadline=perf_counter()+1)
                assert board.recent_own_protect == (0, 1)
                plan = parse("move protect, move protect", board)
                reply = Response("attacks", (Part("move", "dragonclaw", 1), Part("move", "dragonclaw", 2)), 1)
                low = simulate(plan, reply, board, metadata, adverse=True)
                high = simulate(plan, reply, board, metadata, adverse=False)
                assert low["own_damage"] > high["own_damage"]
                second = advance(session, "move protect, move protect", "move dragonclaw +1, move dragonclaw +2")
                changes = [a["hp"]-b["hp"] for a, b in zip(first["player"]["active_details"], second["player"]["active_details"], strict=True)]
                repetitions.append({"seed_index": index, "first_shields_successful": True,
                                    "repeat_damage": changes, "modeled_success_and_failure_retained": True})
            finally:
                worker.close_session(session)
        assert any(any(d > 0 for d in r["repeat_damage"]) for r in repetitions)
        assert any(any(d == 0 for d in r["repeat_damage"]) for r in repetitions)
        result["repeated_protect"] = repetitions

        session, before = opening(support, "team 1234", "team 3142", 10)
        try:
            after = advance(session, "move protect, move followme", "move dragonclaw +1, move dragonclaw +1")
            assert after["player"]["active_details"][0]["hp"] == before["player"]["active_details"][0]["hp"]
            assert after["player"]["active_details"][1]["hp"] < before["player"]["active_details"][1]["hp"]
            result["redirection"] = {"metagross_preserved": True, "indeedee_took_redirected_hits": True}
        finally:
            worker.close_session(session)

        session, before = opening(spread, "team 1234", "team 3142", 11)
        try:
            board = observe(before, worker.session_public_choices(session, side="p1"), deadline=perf_counter()+1)
            bounds = damage_range(board.owned_active[0], board.owned_active[1], "surf", metadata,
                                  spread=True, weather=board.weather)
            after = advance(session, "move surf, move psychicfangs +1", "move protect, move protect")
            native_damage = before["player"]["active_details"][1]["hp"] - after["player"]["active_details"][1]["hp"]
            assert native_damage > 0
            assert bounds[0] <= native_damage <= bounds[1]
            result["spread"] = {"native_partner_damage": native_damage, "conditional_model_range": bounds,
                                "native_damage_within_selected_control_range": True,
                                "owned_stats_copied": asdict(board.owned_active[0])["stats"]}
        finally:
            worker.close_session(session)

        priorities = []
        for preview, terrain in (("team 1534", False), ("team 1234", True)):
            session, before = opening(support, preview, "team 1342", 12)
            try:
                command = "move bulletpunch +1, move trickroom" if terrain else "move bulletpunch +1, move protect"
                after = advance(session, command, "move dragonclaw +2, move protect")
                damage = before["opponent"]["active"][0]["hp_percent"] - after["opponent"]["active"][0]["hp_percent"]
                assert (damage == 0) == terrain
                board = observe(before, worker.session_public_choices(session, side="p1"), deadline=perf_counter()+1)
                modeled = simulate(parse(command, board),
                    Response("attack/protect", (Part("move", "dragonclaw", 2), Part("move", "protect")), 1), board, metadata, adverse=False)
                assert (modeled["opponent_pressure"] == 0) == terrain
                moves = [event[2] for event in after["public_event_delta"]["events"] if len(event) >= 3 and event[0] == "move"]
                assert moves.index("bulletpunch") < moves.index("dragonclaw")
                priorities.append({"psychic_terrain": terrain, "native_opponent_hp_percent_lost": damage,
                                   "priority_before_regular_attack": True, "modeled_priority_block_agrees": True})
            finally:
                worker.close_session(session)
        result["priority"] = priorities
        session, before = opening(retarget, "team 1234", "team 1342", 13)
        try:
            after = advance(session, "move moonblast +1 mega, move psychicfangs +1", "move dragonclaw +2, move dragonclaw +2")
            assert after["opponent"]["active"][0]["fainted"]
            assert after["opponent"]["active"][1]["hp_percent"] < before["opponent"]["active"][1]["hp_percent"]
            result["retargeting"] = {"selected_garchomp_fainted": True, "second_attack_hit_surviving_dragonite": True}
        finally:
            worker.close_session(session)
    output = ROOT/"runs/risk-joint/native-controls.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
