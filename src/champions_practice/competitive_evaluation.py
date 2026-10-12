"""Evaluation only: frozen V2 versus frozen production with isolated diagnostics."""

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog, decide, observe
from champions_practice.belief_controller import BeliefDecision, BeliefDecisionEngine
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.diversity_league import ROSTERS, catalog, team_text
from champions_practice.agent_v2.policy import rank_action
from champions_practice.search_worker import ShowdownSearchWorker, TeamValidationWorker
from champions_practice.strength_league import _git_commit, _showdown_revision, _source_identity
from champions_practice.teams import SMOKE_TEAM

ROOT = Path(__file__).resolve().parents[2]
FUTURE_SEEDS = ("sodium," + "6" * 64, "sodium," + "7" * 64)


def canonical_view(view, side):
    """Relabel public protocol side IDs for the unchanged p2 production engine."""
    if side == "p2":
        return deepcopy(view)
    if side != "p1":
        raise ValueError("invalid side")
    def flip(value):
        if isinstance(value, str):
            return re.sub(r"\bp([12])([a-z]?)(?=\b|:)",
                          lambda m: "p" + ("2" if m[1] == "1" else "1") + m[2], value)
        if isinstance(value, list):
            return [flip(v) for v in value]
        if isinstance(value, dict):
            return {flip(k): flip(v) for k, v in value.items()}
        return value
    return flip(view)


def fixtures():
    """Frozen prior catalog is constructed independently before held-out teams."""
    priors = catalog()
    teams = {
        "ground-spread": team_text(("Garchomp", "Metagross", "Dragonite", "Rotom-Wash", "Incineroar", "Venusaur"))
            .replace("Stomping Tantrum", "Earthquake"),
        "rain-bulk": team_text(("Pelipper", "Basculegion", "Archaludon", "Venusaur", "Gardevoir", "Rillaboom"))
            .replace("Weather Ball", "Surf").replace("2 HP / 32", "32 HP / 2"),
        "psychic-control": team_text(("Gardevoir", "Indeedee-F", "Venusaur", "Metagross", "Incineroar", "Rotom-Wash")),
        "mirror-reference": SMOKE_TEAM,
        "balance-reference": team_text(ROSTERS["balance"]),
    }
    return priors, teams


class Production:
    def __init__(self, team, priors, side, view, budget):
        self.side = side
        self.engine = BeliefDecisionEngine(ROOT, battle_format=CHAMPIONS_FORMAT,
            ai_team=team, opponent_priors=priors, decision_budget_seconds=budget,
            conditioning_budget_seconds=budget, particle_seed=53101)
        started = perf_counter()
        self.engine.initialize_preview(view=canonical_view(view, side), ai_choice="team 1234")
        self.initialization_seconds = perf_counter() - started

    def choose(self, view, choices, budget, metadata):
        if choices == ["wait"]:
            decision = BeliefDecision("wait", "forced-wait", len(self.engine.particles), 1, 0, 0)
        else:
            decision = self.engine.choose_ai_action(legal_live=choices)
        return decision.choice, {"mode": decision.mode, "detail": asdict(decision),
                                 "native_admission": deepcopy(self.engine.last_native_admission)}, decision

    def update(self, decision, view):
        return self.engine.observe_public_turn(decision=decision, view=canonical_view(view, self.side))


def v2_choice(view, choices, budget, metadata):
    result = decide(observe(view, choices, deadline=perf_counter() + budget), metadata)
    return result.action, {"mode": "forced-wait" if choices == ["wait"] else
                          "deadline-incumbent" if not result.evaluated_actions else "public-policy",
                          "detail": asdict(result)}, None


def pressure_choice(view, choices, budget, metadata):
    """Frozen evaluation opponent: public pressure plus single-target focus.

    Shares static utility with V2, so this is a related challenger, not an
    independent learned policy or an established stronger player.
    """
    board = observe(view, choices, deadline=perf_counter() + budget)
    scored = []
    for action in choices:
        if perf_counter() >= board.deadline:
            break
        candidate = rank_action(action, board, metadata)
        targets = re.findall(r"move\s+\S+\s+\+([12])", action)
        focus = 3 if len(targets) == 2 and targets[0] == targets[1] else 0
        scored.append((candidate.score + focus, action))
    action = max(scored, key=lambda item: item[0])[1] if scored else choices[0]
    return action, {"mode": "public-pressure" if scored else "deadline-incumbent",
                    "detail": {"evaluated_actions": len(scored), "focus_bonus": 3}}, None


def material(state, side):
    own, foe = state["sides"][0 if side == "p1" else 1], state["sides"][1 if side == "p1" else 0]
    return (sum(mon["hp"] > 0 for mon in own["pokemon"]),
            sum(mon["hp"] <= 0 for mon in foe["pokemon"]))


def diagnostic(worker, state, side, choices, commands, alternatives):
    """Oracle-only bounded one-turn diagnostic, after BOTH actions are sealed."""
    selected = commands[side]
    candidates = list(dict.fromkeys([selected, *alternatives]))[:4]
    candidates = [c for c in candidates if c in choices]
    outcomes = {}
    for seed in FUTURE_SEEDS:
        branches = [{"p1_choice": c if side == "p1" else commands["p1"],
                     "p2_choice": c if side == "p2" else commands["p2"],
                     "rng_seed": seed, "include_state": True} for c in candidates]
        outcomes[seed] = [material(r["state"], side) for r in worker.branch_many(state=state, branches=branches)]
    improving = []
    for i, candidate in enumerate(candidates[1:], 1):
        if all(values[i][0] >= values[0][0] and values[i][1] >= values[0][1] and
               values[i] != values[0] for values in outcomes.values()):
            improving.append(candidate)
    return {"scope": "bounded conditional one-turn material dominance; fixed submitted opponent response",
            "alternatives_tested": candidates, "sampled_futures": len(FUTURE_SEEDS),
            "dominated_on_both_samples": bool(improving), "improving_alternatives": improving,
            "not_strategic_optimality_or_exhaustive_regret": True}


def play(case, teams, priors, metadata, budget, output):
    rows, engines = [], {}
    report = {**case, "status": "running", "rows": rows, "budget_seconds": budget}
    session = None
    stage = "start"
    with ShowdownSearchWorker(ROOT) as worker, ShowdownSearchWorker(ROOT) as validator:
        try:
            session = worker.start_session(battle_format=CHAMPIONS_FORMAT,
                p1_team=teams[case["teams"]["p1"]], p2_team=teams[case["teams"]["p2"]],
                p1_name="P1", p2_name="P2", seed=case["battle_seed"])["session_id"]
            worker.choose_session(session, p1_choice="team 1234", p2_choice="team 1234")
            views = {s: worker.session_view(session, side=s)["view"] for s in ("p1", "p2")}
            stage = "production-initialization"
            for side in ("p1", "p2"):
                if case["agents"][side] == "production":
                    engines[side] = Production(teams[case["teams"][side]], priors, side, views[side], budget)
            report["initialization_seconds"] = {s: e.initialization_seconds for s, e in engines.items()}
            for checkpoint in range(120):
                if views["p1"]["ended"]:
                    report.update(status="complete", winner=views["p1"]["winner"], turns=views["p1"]["turn"])
                    break
                choices, commands, decisions = {}, {}, {}
                row = {"checkpoint": checkpoint, "turn": views["p1"]["turn"], "sides": {}}
                rows.append(row)
                for side in ("p1", "p2"):
                    stage = "decision:" + side
                    choices[side] = worker.session_public_choices(session, side=side)
                    started = perf_counter()
                    if side in engines:
                        command, telemetry, decision = engines[side].choose(views[side], choices[side], budget, metadata)
                    elif case["agents"][side] == "v2":
                        command, telemetry, decision = v2_choice(views[side], choices[side], budget, metadata)
                    else:
                        command, telemetry, decision = pressure_choice(views[side], choices[side], budget, metadata)
                    elapsed = perf_counter() - started
                    if command not in choices[side]:
                        raise AssertionError("agent action outside public request menu")
                    commands[side], decisions[side] = command, decision
                    row["sides"][side] = {"agent": case["agents"][side], "view": views[side],
                        "public_choices": choices[side], "action": command, "telemetry": telemetry,
                        "wall_seconds": elapsed, "budget_overrun": elapsed > budget}
                # No agent receives its opponent's chosen action. Diagnostics run only now.
                stage = "isolated-diagnostic"
                if views["p1"]["phase"] == "move":
                    state = worker.session_snapshot(session)["state"]
                    for side in ("p1", "p2"):
                        ranking = decide(observe(views[side], choices[side], deadline=perf_counter() + budget), metadata)
                        row["sides"][side]["shadow_v2"] = asdict(ranking)
                        row["sides"][side]["tactical_diagnostic"] = diagnostic(validator, state, side,
                            choices[side], commands, [a.action for a in ranking.alternatives])
                stage = "submit"
                worker.choose_session(session, p1_choice=commands["p1"], p2_choice=commands["p2"])
                views = {s: worker.session_view(session, side=s)["view"] for s in ("p1", "p2")}
                for side, engine in engines.items():
                    stage = "conditioning:" + side
                    update = engine.update(decisions[side], views[side])
                    row["sides"][side]["conditioning_seconds"] = update.conditioning_seconds
                    row["sides"][side]["conditioning_over_budget"] = update.conditioning_over_budget
                output.write_text(json.dumps(report) + "\n", encoding="utf-8")
            else:
                report.update(status="incomplete", failure_stage="submission-cap")
        except Exception as error:
            report.update(status="failed", failure_stage=stage, error_type=type(error).__name__)
            # Preserve safe checkpoints, not exception text or native oracle snapshots.
        finally:
            if session:
                worker.close_session(session)
    output.write_text(json.dumps(report) + "\n", encoding="utf-8")
    return report


def summarize(games):
    result = {"statuses": dict(Counter(g["status"] for g in games)), "agents": {}}
    result["transport_timeouts"] = sum("Timeout" in g.get("error_type", "") for g in games)
    for agent in ("v2", "production", "pressure"):
        entries = [(g, s) for g in games for s in ("p1", "p2") if g["agents"][s] == agent]
        complete = [(g, s) for g, s in entries if g["status"] == "complete"]
        win = sum(g["winner"] == s.upper() for g, s in complete)
        draws = sum(not g["winner"] for g, s in complete)
        rows = [r["sides"][s] for g, s in entries for r in g["rows"] if s in r["sides"]]
        actionable = [r for r in rows if r["public_choices"] != ["wait"]]
        fallback = sum(r["telemetry"]["mode"] in ("fallback", "deadline-incumbent") for r in actionable)
        times = sorted(r["wall_seconds"] for r in rows)
        result["agents"][agent] = {"appearances": len(entries), "completed": len(complete), "wins": win,
            "losses": len(complete) - win - draws, "draws": draws,
            "completed_score_rate": (win + draws / 2) / len(complete) if complete else None,
            "actionable_decisions": len(actionable), "fallbacks": fallback,
            "fallback_rate": fallback / len(actionable) if actionable else None,
            "search_decisions": sum(r["telemetry"]["mode"] == "belief-search" for r in actionable),
            "budget_overruns": sum(r["budget_overrun"] for r in rows),
            "latency_p50_seconds": times[len(times) // 2] if times else None,
            "latency_p95_seconds": times[min(len(times)-1, int(len(times)*.95))] if times else None,
            "latency_max_seconds": max(times) if times else None,
            "bounded_material_mistakes": sum(r.get("tactical_diagnostic", {}).get("dominated_on_both_samples", False) for r in rows),
            "diagnosed_decisions": sum("tactical_diagnostic" in r for r in rows)}
    result["strata"] = {category: summarize_subset([g for g in games if g.get("category") == category])
                        for category in sorted({g.get("category", "unspecified") for g in games})}
    result["promotion_ready"] = False
    return result


def summarize_subset(games):
    return {"completed": sum(g["status"] == "complete" for g in games),
            "v2_wins": sum(g["status"] == "complete" and bool(g.get("winner")) and
                           g["agents"].get(g["winner"].lower()) == "v2" for g in games),
            "production_wins": sum(g["status"] == "complete" and bool(g.get("winner")) and
                                   g["agents"].get(g["winner"].lower()) == "production" for g in games)}


def run(output, *, budget=8, seeds=5, smoke=False):
    output.mkdir(parents=True, exist_ok=True)
    priors, teams = fixtures()
    metadata = PublicCatalog.load(ROOT)
    with TeamValidationWorker(ROOT) as validator:
        for team in teams.values():
            result = validator.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=team)
            if not result["valid"]:
                raise ValueError("held-out team failed native format validation")
    matchups = [("ground-spread", "rain-bulk"), ("rain-bulk", "psychic-control"),
                ("psychic-control", "ground-spread"), ("mirror-reference", "balance-reference")]
    cases = []
    for matchup, (a, b) in enumerate(matchups[:1] if smoke else matchups):
        for seed_index in range(seeds):
            battle_seed = "sodium," + hashlib.sha256(f"competitive-heldout:{matchup}:{seed_index}".encode()).hexdigest()
            for side in ("p1", "p2"):
                cases.append({"id": f"direct-{matchup}-{seed_index}-{side}", "pair": f"direct-{matchup}-{seed_index}",
                    "category": "reference-direct" if matchup == 3 else "heldout-direct",
                    "teams": {"p1": a, "p2": b}, "battle_seed": battle_seed,
                    "agents": {side: "v2", "p2" if side == "p1" else "p1": "production"}})
                if not smoke and matchup < 3:
                    for agent in ("v2", "production"):
                        cases.append({"id": f"pressure-{matchup}-{seed_index}-{side}-{agent}",
                            "pair": f"pressure-{matchup}-{seed_index}-{side}", "category": "common-pressure",
                            "teams": {"p1": a, "p2": b}, "battle_seed": battle_seed,
                            "agents": {side: agent, "p2" if side == "p1" else "p1": "pressure"}})
    manifest = {"schema": "competitive-evaluation-v1", "baseline_commit": _git_commit(ROOT),
        "showdown_revision": _showdown_revision(ROOT), "source_identity": _source_identity(ROOT),
        "policy_sha256": hashlib.sha256((ROOT / "src/champions_practice/agent_v2/policy.py").read_bytes()).hexdigest(),
        "production_sha256": hashlib.sha256((ROOT / "src/champions_practice/belief_controller.py").read_bytes()).hexdigest(),
        "team_sha256": {k: hashlib.sha256(v.encode()).hexdigest() for k, v in teams.items()},
        "prior_sha256": hashlib.sha256(json.dumps({k: [asdict(v) for v in values] for k, values in priors.items()}, sort_keys=True).encode()).hexdigest(),
        "budget_seconds": budget, "cases": cases, "production_changed": False,
        "limitations": ["small paired head-to-head diagnostic, not a strength promotion",
            "side swaps exchange policy assignment with fixed teams and seed",
            "oracle diagnostics never feed actions; bounded fixed-response samples are not optimality",
            "production p1 uses public-label adapter; failed games are not losses"]}
    games = []
    for case in cases:
        result = play(case, teams, priors, metadata, budget, output / (case["id"] + ".json"))
        games.append(result)
        (output / "report.json").write_text(json.dumps({**manifest, "games": games, "summary": summarize(games)}) + "\n", encoding="utf-8")
        print(case["id"], result["status"], result.get("winner"), flush=True)
    print(json.dumps(summarize(games), indent=2))
    return {**manifest, "games": games, "summary": summarize(games)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "runs/competitive-evaluation")
    parser.add_argument("--budget", type=float, default=8)
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if not 0 < args.budget <= 30 or not 1 <= args.seeds <= 20:
        parser.error("budget must be (0,30] seconds and seeds 1..20")
    result = run(args.output, budget=args.budget, seeds=args.seeds, smoke=args.smoke)
    if any(g["status"] != "complete" for g in result["games"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
