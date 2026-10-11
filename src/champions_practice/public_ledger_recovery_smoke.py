"""Pinned berry/stat-block protocol controls and optional frozen-game replay."""

import argparse
import json
from pathlib import Path

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.diversity_league import ROSTERS, team_text
from champions_practice.search_worker import ShowdownSearchWorker


def native_controls(worker):
    team = team_text(ROSTERS["balance"])
    previews = {side: list(ROSTERS["balance"]) for side in ("p1", "p2")}
    current = worker.create_state(battle_format=CHAMPIONS_FORMAT,
        p1_team=team, p2_team=team, p1_preview="team 3124", p2_preview="team 4312",
        seed="sodium,00000001000000020000000300000004")
    ledger = PublicConstraintLedger.from_public_view(worker.state_view(state=current, side="p2", previews=previews))
    observed = set()
    for p1, p2 in (
        ("move protect, move fakeout +1", "move protect, switch 3"),
        ("move protect, move flareblitz +2", "move stompingtantrum +2, move darkestlariat +2"),
    ):
        current = worker.branch_many(state=current, branches=[{
            "p1_choice": p1, "p2_choice": p2, "include_state": True,
        }])[0]["state"]
        view = worker.state_view(state=current, side="p2", previews=previews)
        ledger = ledger.advance(view)
        for event in view["public_event_delta"]["events"]:
            if event == ["-enditem", "p1b", "shucaberry", "[weaken]"]:
                observed.add("berry")
            if event[:4] == ["-fail", "p1a", "unboost", "atk"] and "[from]:ability:innerfocus" in event:
                observed.add("stat-block")
    assert observed == {"berry", "stat-block"}, observed
    assert ledger.current_turn == view["turn"]
    assert any("[weaken]" in record.payload for record in ledger.records)
    print('Pinned public ledger: consumed resistance berry and Intimidate/stat-block evidence retained')


def replay_frozen(worker, path):
    report = json.loads(path.read_text())
    game = report["games"][0]
    team = team_text(ROSTERS["balance"])
    previews = {side: list(ROSTERS["balance"]) for side in ("p1", "p2")}
    current = worker.create_state(battle_format=CHAMPIONS_FORMAT,
        p1_team=team, p2_team=team, p1_preview="team 1234", p2_preview="team 1234",
        p1_name="League Baseline", p2_name="League Bot", seed=game["session_seed"])
    ledger = PublicConstraintLedger.from_public_view(worker.state_view(state=current, side="p2", previews=previews))
    for trace in game["decision_trace"]:
        before = worker.state_view(state=current, side="p2", previews=previews)
        assert before == trace["bot_public_before"], trace["decision_index"]
        current = worker.branch_many(state=current, branches=[{
            "p1_choice": trace["baseline_action"], "p2_choice": trace["chosen_action"], "include_state": True,
        }])[0]["state"]
        after = worker.state_view(state=current, side="p2", previews=previews)
        assert after == trace["bot_public_after"], trace["decision_index"]
        previous = ledger
        ledger = ledger.advance(after)
        assert ledger.records[:len(previous.records)] == previous.records
    print(f'Frozen game replay: all {len(game["decision_trace"])} public boundaries validated; history retained')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    with ShowdownSearchWorker() as worker:
        native_controls(worker)
        if args.report:
            replay_frozen(worker, args.report)


if __name__ == "__main__":
    main()
