"""Native positive control for V2 spread friendly-fire scoring."""

import json
from pathlib import Path
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog, observe
from champions_practice.agent_v2.policy import rank_action
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.diversity_league import ROSTERS, team_text
from champions_practice.search_worker import ShowdownSearchWorker, TeamValidationWorker
from champions_practice.teams import SMOKE_TEAM


def main():
    root = Path(__file__).resolve().parents[1]
    catalog = PublicCatalog.load(root)
    assert catalog.moves["earthquake"]["target"] == "allAdjacent"
    assert catalog.moves["surf"]["target"] == "allAdjacent"
    assert catalog.moves["rockslide"]["target"] == "allAdjacentFoes"
    team = team_text(ROSTERS["sand"]).replace("Stomping Tantrum", "Earthquake")
    with TeamValidationWorker(root) as validator:
        assert validator.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=team)["valid"]
    with ShowdownSearchWorker() as worker:
        session = worker.start_session(battle_format=CHAMPIONS_FORMAT,
            p1_team=team, p2_team=SMOKE_TEAM, p1_name="P1", p2_name="P2",
            seed="sodium," + "1" * 64)["session_id"]
        try:
            worker.choose_session(session, p1_choice="team 3612", p2_choice="team 3214")
            before = worker.session_view(session, side="p1")["view"]
            legal = worker.session_legal_choices(session, side="p1")
            command = "move earthquake, move psychicfangs +1"
            assert command in legal
            board = observe(before, legal, deadline=perf_counter() + 1)
            scored = rank_action(command, board, catalog)
            assert any("friendly-fire" in reason for reason in scored.reasons)
            worker.choose_session(session, p1_choice=command, p2_choice="move protect, move protect")
            after = worker.session_view(session, side="p1")["view"]
            old_hp = before["player"]["active_details"][1]["hp"]
            new_hp = after["player"]["active_details"][1]["hp"]
            assert new_hp < old_hp, "native Earthquake failed to damage unprotected partner"
            report = {"native_targets": {m: catalog.moves[m]["target"]
                                         for m in ("earthquake", "surf", "rockslide")},
                      "catalog_sha256": catalog.fingerprint, "legal_command": command,
                      "partner_hp_before": old_hp, "partner_hp_after": new_hp,
                      "policy_reasons": scored.reasons, "native_control_passed": True}
            output = root / "runs/agent-v2/spread-native-control.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, indent=2))
        finally:
            worker.close_session(session)


if __name__ == "__main__":
    main()
