"""Validate paired candidate evidence and optionally freeze lossless telemetry."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path


def analyze(reports):
    if not reports:
        raise ValueError("no reports")
    reference = reports[0]
    games = []
    for report in reports:
        for key in ("source_identity", "catalog_sha256", "team_sha256", "budget_seconds"):
            if report[key] != reference[key]:
                raise ValueError(f"inconsistent {key}")
        if report["scenario_weights_are_probabilities"] or not report["baseline_default_unchanged"]:
            raise ValueError("experiment boundary violated")
        games.extend(report["games"])
    if len({g["id"] for g in games}) != len(games):
        raise ValueError("duplicate game")
    pairs = {}
    for game in games:
        if game["status"] != "complete":
            raise ValueError("incomplete game cannot establish paired evidence")
        key = (game["seed"], game["side"], game["opponent"], game["p1_team"], game["p2_team"])
        members = pairs.setdefault(key, {})
        if game["agent"] in members:
            raise ValueError("duplicate pair member")
        members[game["agent"]] = game
        for row in game["rows"]:
            decision = row["decision"]
            if decision["action"] not in row["public_choices"]:
                raise ValueError("illegal decision")
            if row["budget_overrun"] != (row["elapsed_seconds"] > reference["budget_seconds"]):
                raise ValueError("incorrect deadline telemetry")
            if game["opponent"] == "guard" and row["enemy_trace"]["actual_opponent_plan_received"]:
                raise ValueError("guard received submitted plan")
            for assessment in decision.get("joint_analysis", []):
                if any(assessment[k] for k in ("guaranteed_ko", "weights_are_probabilities",
                        "mechanically_certified", "response_coverage_exhaustive",
                        "response_forecast_uses_private_owned_stats")):
                    raise ValueError("unsupported certainty claim")
    if any(set(members) != {"baseline", "risk"} for members in pairs.values()):
        raise ValueError("unpaired game")
    strata = {}
    for opponent in ("pressure", "guard"):
        for agent in ("baseline", "risk"):
            selected = [g for g in games if g["agent"] == agent and g["opponent"] == opponent]
            rows = [r for g in selected for r in g["rows"]]
            times = sorted(r["elapsed_seconds"] for r in rows)
            strata[agent+":"+opponent] = {
                "games": len(selected), "wins": sum(g["win"] for g in selected), "decisions": len(rows),
                "deadline_exhaustions": sum(r["decision"]["deadline_exhausted"] for r in rows),
                "budget_overruns": sum(r["budget_overrun"] for r in rows),
                "p50_seconds": times[len(times)//2] if times else 0,
                "p95_seconds": times[min(len(times)-1, int(len(times)*.95))] if times else 0,
                "maximum_seconds": max(times, default=0),
                "guard_protect_decisions": sum("protect" in r["enemy_action"] for r in rows) if opponent == "guard" else 0,
            }
    paired = {}
    for opponent in ("pressure", "guard"):
        selected = [p for key, p in pairs.items() if key[2] == opponent]
        paired[opponent] = dict(Counter(
            "both_win" if p["baseline"]["win"] and p["risk"]["win"] else
            "risk_only_win" if p["risk"]["win"] else
            "baseline_only_win" if p["baseline"]["win"] else "both_lose" for p in selected))
    return {"schema": "risk-joint-paired-analysis-v1", "source_identity": reference["source_identity"],
            "games_completed": len(games), "paired_cases": len(pairs), "strata": strata,
            "paired_outcomes": paired, "promotion_ready": False,
            "limitations": ["Small related synthetic opponents; not a competitive strength claim.",
                            "Approximate conditional outcomes; no certified KO or calibrated response probabilities."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--freeze", type=Path)
    args = parser.parse_args()
    raw = [path.read_bytes() for path in args.reports]
    analysis = analyze([json.loads(data) for data in raw])
    if args.freeze:
        args.freeze.mkdir(parents=True, exist_ok=True)
        artifacts = []
        for index, data in enumerate(raw):
            target = args.freeze/f"suite-{index+1}.json.gz"
            target.write_bytes(gzip.compress(data, mtime=0))
            artifacts.append({"path": target.name, "uncompressed_sha256": hashlib.sha256(data).hexdigest(),
                              "compressed_sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
        analysis["artifacts"] = artifacts
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(analysis, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(analysis, indent=2))


if __name__ == "__main__":
    main()
