"""Offline candidate/baseline comparison with public pressure and protective guards."""

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog, observe
from champions_practice.agent_v2.policy import decide_baseline, decide_risk, ident, rank_action
from champions_practice.agent_v2.joint import damage_range, parse
from champions_practice.competitive_evaluation import fixtures, pressure_choice
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import ShowdownSearchWorker, TeamValidationWorker
from champions_practice.strength_league import _git_commit, _showdown_revision

ROOT = Path(__file__).resolve().parents[2]


def guard_choice(view, choices, budget, metadata):
    """Forecast focus from public type/damage exposure, never the submitted plan."""
    board = observe(view, choices, deadline=perf_counter()+budget)
    incoming = [0.0] * len(board.owned_active)
    for foe in board.opponents:
        if not foe or foe.fainted:
            continue
        move_type = metadata.species.get(ident(foe.species), ["Normal"])[0]
        move = f"generic:{move_type}:0"
        possible = [(i, damage_range(foe, mon, move, metadata)[1])
                    for i, mon in enumerate(board.owned_active) if mon and not mon.fainted]
        if possible:
            target, amount = max(possible, key=lambda pair: pair[1]/max(1, board.owned_active[pair[0]].hp or 1))
            incoming[target] += amount
    best, score = choices[0], float("-inf")
    for action in choices:
        if perf_counter() >= board.deadline:
            break
        value = rank_action(action, board, metadata).score
        for slot, part in enumerate(parse(action, board)):
            if part.move in {"protect", "detect"} and slot < len(board.owned_active) and board.owned_active[slot]:
                ratio = incoming[slot] / max(1, board.owned_active[slot].hp or 1)
                value += min(26, 18 * ratio) * (.1 if slot in board.recent_own_protect else 1)
        if value > score:
            best, score = action, value
    return best, {"incoming_public_forecast": incoming, "actual_opponent_plan_received": False,
                  "probabilities_calibrated": False}


def play(case, teams, metadata, budget):
    rows = []
    side = case["side"]
    other = "p2" if side == "p1" else "p1"
    with ShowdownSearchWorker(ROOT) as worker:
        session = worker.start_session(battle_format=CHAMPIONS_FORMAT,
            p1_team=teams[case["p1_team"]], p2_team=teams[case["p2_team"]],
            p1_name="P1", p2_name="P2", seed=case["seed"])["session_id"]
        try:
            worker.choose_session(session, p1_choice="team 1234", p2_choice="team 1234")
            for checkpoint in range(120):
                view = worker.session_view(session, side=side)["view"]
                if view["ended"]:
                    return {**case, "status": "complete", "winner": view["winner"],
                            "win": view["winner"] == side.upper(), "rows": rows}
                choices = worker.session_public_choices(session, side=side)
                started = perf_counter()
                board = observe(view, choices, deadline=started+budget)
                decision = (decide_risk if case["agent"] == "risk" else decide_baseline)(board, metadata)
                elapsed = perf_counter()-started
                enemy_view = worker.session_view(session, side=other)["view"]
                enemy_choices = worker.session_public_choices(session, side=other)
                if case["opponent"] == "guard":
                    enemy_action, enemy_trace = guard_choice(enemy_view, enemy_choices, budget, metadata)
                else:
                    enemy_action, enemy_trace, _ = pressure_choice(enemy_view, enemy_choices, budget, metadata)
                assert decision.action in choices and enemy_action in enemy_choices
                rows.append({"checkpoint": checkpoint, "view": view, "public_choices": choices,
                             "decision": asdict(decision), "elapsed_seconds": elapsed,
                             "budget_overrun": elapsed > budget, "enemy_view": enemy_view,
                             "enemy_action": enemy_action, "enemy_trace": enemy_trace})
                commands = {side: decision.action, other: enemy_action}
                worker.choose_session(session, p1_choice=commands["p1"], p2_choice=commands["p2"])
            return {**case, "status": "incomplete", "rows": rows}
        except Exception as error:
            return {**case, "status": "failed", "error_type": type(error).__name__, "rows": rows}
        finally:
            worker.close_session(session)


def source_identity():
    # Bind the experiment to its baseline and actual changed runtime graph.
    # Unrelated, untracked work in the shared checkout is not a dependency.
    files = ("src/champions_practice/agent_v2/policy.py", "src/champions_practice/agent_v2/joint.py",
             "src/champions_practice/risk_joint_audit.py", "tools/agent-v2-catalog.js")
    hashes = {path: hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in files}
    identity = {"baseline": _git_commit(ROOT), "files": hashes, "showdown": _showdown_revision(ROOT)}
    return {"schema": "risk-runtime-graph-sha256-v1", "sha256": hashlib.sha256(
        json.dumps(identity, sort_keys=True).encode()).hexdigest(), **identity}


def run(output, seeds=2, budget=8, smoke=False, seed_offset=0):
    output.mkdir(parents=True, exist_ok=True)
    _, teams = fixtures()
    names = list(teams)[:3]
    metadata = PublicCatalog.load(ROOT)
    with TeamValidationWorker(ROOT) as validator:
        for team in teams.values():
            assert validator.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=team)["valid"]
    report = {"schema": "risk-joint-candidate-v1", "git_commit": _git_commit(ROOT),
              "source_identity": source_identity(), "showdown_revision": _showdown_revision(ROOT),
              "catalog_sha256": metadata.fingerprint,
              "team_sha256": {name: hashlib.sha256(team.encode()).hexdigest() for name, team in teams.items()},
              "seeds": seeds, "seed_offset": seed_offset,
              "budget_seconds": budget, "baseline_default_unchanged": True,
              "scenario_weights_are_probabilities": False, "games": []}
    for index, name in enumerate(names[:1] if smoke else names):
        for seed_index in range(seeds):
            actual_index = seed_index+seed_offset
            seed = "sodium," + hashlib.sha256(f"risk-joint-heldout:{index}:{actual_index}".encode()).hexdigest()
            for side in ("p1", "p2"):
                for opponent in ("pressure", "guard"):
                    for agent in ("baseline", "risk"):
                        case = {"id": f"{index}-{actual_index}-{side}-{opponent}-{agent}", "side": side,
                                "p1_team": name, "p2_team": names[(index+1)%3], "seed": seed,
                                "agent": agent, "opponent": opponent}
                        try:
                            game = play(case, teams, metadata, budget)
                        except Exception as error:
                            game = {**case, "status": "failed", "error_type": type(error).__name__, "rows": []}
                        report["games"].append(game)
                        (output/"report.json").write_text(json.dumps(report)+"\n", encoding="utf-8")
                        print(case["id"], game["status"], game.get("win"), flush=True)
    report["summary"] = {"statuses": dict(Counter(g["status"] for g in report["games"])), "strata": {},
                         "promotion_ready": False}
    for agent in ("baseline", "risk"):
        for opponent in ("pressure", "guard"):
            games = [g for g in report["games"] if g["agent"] == agent and g["opponent"] == opponent]
            rows = [r for g in games for r in g["rows"]]
            report["summary"]["strata"][agent+":"+opponent] = {
                "games": len(games), "completed": sum(g["status"] == "complete" for g in games),
                "wins": sum(g.get("win", False) for g in games), "decisions": len(rows),
                "deadline_exhaustions": sum(r["decision"]["deadline_exhausted"] for r in rows),
                "budget_overruns": sum(r["budget_overrun"] for r in rows),
                "maximum_seconds": max((r["elapsed_seconds"] for r in rows), default=0)}
    (output/"report.json").write_text(json.dumps(report)+"\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT/"runs/risk-joint")
    parser.add_argument("--seeds", type=int, default=2)
    parser.add_argument("--budget", type=float, default=8)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--seed-offset", type=int, default=0)
    args = parser.parse_args()
    if not 1 <= args.seeds <= 10 or not 0 < args.budget <= 8 or not 0 <= args.seed_offset <= 10000:
        parser.error("seeds must be 1..10 and budget (0,8]")
    report = run(args.output, args.seeds, args.budget, args.smoke, args.seed_offset)
    if any(g["status"] != "complete" for g in report["games"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
