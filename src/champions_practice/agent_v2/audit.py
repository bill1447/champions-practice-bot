"""Paired offline V2 pilot; baseline games also record V2 shadow decisions."""

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog, decide, observe
from champions_practice.belief_controller import choose_public_fallback
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.diversity_league import POLICIES, ROSTERS, policy_selector, team_text
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.strength_league import _git_commit, _showdown_revision, _source_identity


ROOT = Path(__file__).resolve().parents[3]


def game(worker, catalog, *, team, opponent, policy, side, seed, mode, budget_ms=100):
    teams = {side: team, "p2" if side == "p1" else "p1": opponent}
    session = worker.start_session(battle_format=CHAMPIONS_FORMAT, p1_team=teams["p1"],
        p2_team=teams["p2"], seed=seed, p1_name="P1", p2_name="P2")["session_id"]
    enemy_side = "p2" if side == "p1" else "p1"
    enemy_policy = policy_selector(policy, 52101)
    rows = []
    try:
        # Fixed selected four and order isolate move-policy changes from preview.
        worker.choose_session(session, p1_choice="team 1234", p2_choice="team 1234")
        for checkpoint in range(180):
            view = worker.session_view(session, side=side)["view"]
            if view["ended"]:
                return {"mode": mode, "policy": policy, "side": side,
                        "completed": True, "winner": view["winner"],
                        "outcome": "win" if view["winner"] == side.upper() else
                                   "draw" if not view["winner"] else "loss",
                        "turns": view["turn"], "decisions": rows}
            legal = worker.session_legal_choices(session, side=side)
            board = observe(view, legal, deadline=perf_counter() + budget_ms / 1000)
            decision = decide(board, catalog)
            baseline = choose_public_fallback(legal)
            if decision.action not in legal:
                raise AssertionError("V2 returned an action outside authoritative menu")
            submitted = decision.action if mode == "v2" else baseline
            enemy_legal = worker.session_legal_choices(session, side=enemy_side)
            commands = {side: submitted, enemy_side: enemy_policy(enemy_legal)}
            rows.append({"checkpoint": checkpoint, "turn": board.turn, "phase": board.phase,
                         "input": asdict(board), "v2": asdict(decision),
                         "baseline_action": baseline, "submitted_action": submitted,
                         "shadow_disagrees": decision.action != baseline})
            worker.choose_session(session, p1_choice=commands["p1"], p2_choice=commands["p2"])
        raise AssertionError("game failed to terminate within 180 submissions")
    finally:
        worker.close_session(session)


def run(output, *, seeds=1, seed_offset=0):
    catalog = PublicCatalog.load(ROOT)
    games = []
    report = {"schema": "public-policy-v2-pilot-v1", "baseline_commit": _git_commit(ROOT),
              "source_identity": _source_identity(ROOT), "showdown_revision": _showdown_revision(ROOT),
              "catalog_sha256": catalog.fingerprint, "production_changed": False,
              "comparison": "V2 versus choose_public_fallback; not full production search",
              "selected_four": "1234", "deadline_ms": 100,
              "seeds": seeds, "seed_offset": seed_offset,
              "limitations": ["small synthetic pilot, not a strength promotion",
                              "heuristic utilities and margins are uncalibrated",
                              "shadow decisions do not alter baseline battles"], "games": games}
    teams = {name: team_text(roster) for name, roster in ROSTERS.items()}
    report["team_sha256"] = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in teams.items()}
    names = tuple(teams)
    for index, (name, team) in enumerate(teams.items()):
        opponent_name = names[(index + 1) % len(names)]
        for policy in POLICIES:
            for side in ("p1", "p2"):
                for repetition in range(seeds):
                    seed_index = repetition + seed_offset
                    seed = "sodium," + hashlib.sha256(f"v2-pilot:{index}:{seed_index}".encode()).hexdigest()
                    for mode in ("baseline-shadow", "v2"):
                        with ShowdownSearchWorker() as worker:
                            result = game(worker, catalog, team=team, opponent=teams[opponent_name],
                                          policy=policy, side=side, seed=seed, mode=mode)
                        games.append({"team": name, "opponent_team": opponent_name,
                                      "seed_index": seed_index, **result})
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                        print(f'{name}/{policy}/{side}/{repetition}/{mode}: {result["outcome"]}', flush=True)
    rows = [row for g in games for row in g["decisions"]]
    report["summary"] = {
        "games": len(games), "complete_games": sum(g["completed"] for g in games),
        "outcomes": {mode: dict(Counter(g["outcome"] for g in games if g["mode"] == mode))
                     for mode in ("baseline-shadow", "v2")},
        "decisions": len(rows), "illegal_actions": 0,
        "deadline_exhaustions": sum(r["v2"]["deadline_exhausted"] for r in rows),
        "maximum_decision_ms": max(r["v2"]["elapsed_ms"] for r in rows),
        "shadow_disagreements": sum(r["shadow_disagrees"] for g in games
                                    if g["mode"] == "baseline-shadow" for r in g["decisions"]),
        "native_reconstruction_calls": 0, "promotion_ready": False}
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "runs/agent-v2/pilot.json")
    parser.add_argument("--seeds", type=int, default=1)
    parser.add_argument("--seed-offset", type=int, default=0)
    args = parser.parse_args()
    if not 1 <= args.seeds <= 20:
        parser.error("seeds must be between 1 and 20")
    if not 0 <= args.seed_offset <= 10000:
        parser.error("seed-offset must be between 0 and 10000")
    run(args.output, seeds=args.seeds, seed_offset=args.seed_offset)


if __name__ == "__main__":
    main()
