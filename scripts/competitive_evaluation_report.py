"""Validate evaluation traces and compute paired cluster summaries offline."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import random
from statistics import fmean


def score(game, agent):
    if game["status"] != "complete":
        return None
    side = next(side for side, name in game["agents"].items() if name == agent)
    return .5 if not game["winner"] else float(game["winner"] == side.upper())


def interval(values):
    if not values:
        return None
    rng = random.Random(54701)
    samples = sorted(fmean(rng.choices(values, k=len(values))) for _ in range(5000))
    return [samples[125], samples[4874]]


def analyze(report):
    expected = {case["id"]: case for case in report["cases"]}
    if len(expected) != len(report["cases"]):
        raise ValueError("duplicate manifest case")
    pairs = defaultdict(list)
    for case in expected.values():
        pairs[case["pair"]].append(case)
    for pair in pairs.values():
        if len(pair) != 2 or pair[0]["teams"] != pair[1]["teams"] or pair[0]["battle_seed"] != pair[1]["battle_seed"]:
            raise ValueError("missing or unequal paired cases")
        if pair[0]["category"] != pair[1]["category"]:
            raise ValueError("paired categories differ")
        assignments = {tuple(case["agents"][s] for s in ("p1", "p2")) for case in pair}
        if pair[0]["category"] == "common-pressure":
            if assignments not in ({("v2", "pressure"), ("production", "pressure")},
                                   {("pressure", "v2"), ("pressure", "production")}):
                raise ValueError("unmatched common opponent")
        elif assignments != {("v2", "production"), ("production", "v2")}:
            raise ValueError("direct match lacks side swap")
    games = {game["id"]: game for game in report["games"]}
    if len(games) != len(report["games"]) or games.keys() != expected.keys():
        raise ValueError("incomplete or duplicate evaluated case set")
    for key, game in games.items():
        for field in ("agents", "teams", "battle_seed", "pair", "category"):
            if game[field] != expected[key][field]:
                raise ValueError("manifest mismatch: " + field)
        if game["budget_seconds"] != report["budget_seconds"]:
            raise ValueError("unequal decision budgets")
        if game["status"] == "complete" and game["winner"] not in ("P1", "P2", None, ""):
            raise ValueError("invalid winner")
        for row in game["rows"]:
            for side, detail in row["sides"].items():
                if detail["action"] not in detail["public_choices"]:
                    raise ValueError("action outside public menu")
                if detail["agent"] != game["agents"][side]:
                    raise ValueError("policy identity mismatch")
    result = {"schema": "paired-competitive-analysis-v1", "source_identity": report["source_identity"],
              "policy_sha256": report["policy_sha256"], "production_sha256": report["production_sha256"],
              "validated_games": len(games), "statuses": dict(Counter(g["status"] for g in games.values())),
              "pairing_verified": True, "equal_budgets_verified": True, "strata": {},
              "promotion_ready": False}
    for category in ("heldout-direct", "reference-direct", "common-pressure"):
        selected = [g for g in games.values() if g["category"] == category]
        clusters = defaultdict(list)
        for game in selected:
            if game["status"] != "complete":
                continue
            cluster = tuple(game["pair"].split("-")[1:3])
            clusters[cluster].append(game)
        agent_data = {}
        for agent in ("v2", "production"):
            values = [score(g, agent) for g in selected if agent in g["agents"].values() and g["status"] == "complete"]
            cluster_values = []
            for group in clusters.values():
                values_in_group = [score(g, agent) for g in group if agent in g["agents"].values()]
                if values_in_group:
                    cluster_values.append(fmean(values_in_group))
            agent_data[agent] = {"completed_games": len(values), "wins": sum(v == 1 for v in values),
                                 "draws": sum(v == .5 for v in values),
                                 "score_rate": fmean(values) if values else None,
                                 "seed_team_cluster_resampling_95band": interval(cluster_values),
                                 "resampling_degenerate": len(set(cluster_values)) <= 1}
        result["strata"][category] = {"completed_games": sum(g["status"] == "complete" for g in selected),
                                     "seed_team_clusters": len(clusters), "agents": agent_data}
    result["interval_scope"] = "descriptive resampling over tested team/seed clusters, not a population confidence interval; constant observed scores give a degenerate band"
    production = [detail for g in games.values() for row in g["rows"] for detail in row["sides"].values()
                  if detail["agent"] == "production"]
    search = [detail for detail in production if detail["telemetry"]["mode"] == "belief-search"]
    result["production_diagnostics"] = {
        "fallback_reasons": dict(Counter(detail["telemetry"]["detail"].get("fallback_reason") or "unspecified"
                                        for detail in production if detail["telemetry"]["mode"] == "fallback")),
        "conditioning_budget_overruns": sum(detail.get("conditioning_over_budget", False) for detail in production),
        "search_decisions": len(search),
        "search_bounded_material_flags": sum(detail.get("tactical_diagnostic", {}).get("dominated_on_both_samples", False) for detail in search),
        "search_shadow_v2_material_dominance": sum(detail.get("shadow_v2", {}).get("action") in
            detail.get("tactical_diagnostic", {}).get("improving_alternatives", []) for detail in search),
        "scope": "hindsight fixed-response two-sample material comparisons; not proof V2 beats admitted search generally"}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(json.loads(args.report.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
