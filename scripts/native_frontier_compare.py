"""Compare paired offline native-generation reports without feeding a tracker."""

import argparse
from collections import Counter
import json
from pathlib import Path


def verified_games(report):
    if report.get("audit_failed"):
        raise ValueError("cannot compare a failed audit")
    games = {}
    outcomes = Counter()
    for game in report["games"]:
        key = (game["fixture"], game["policy"])
        if key in games:
            raise ValueError("duplicate reference fixture/policy")
        rows = game["checkpoints"]
        if not game["completed_reference_game"] or not rows or not rows[-1]["terminal"]:
            raise ValueError("reference game did not reach terminal")
        continuous = all(row["continuous_mechanical_witnesses"] > 0 for row in rows)
        if continuous != game["continuous_mechanical_lineage_to_terminal"]:
            raise ValueError("terminal lineage claim disagrees with checkpoint ancestry")
        for row in rows:
            expected = "witnessed" if row["validator"]["mechanical_witnesses"] else "unresolved"
            if row["outcome"] != expected:
                raise ValueError("checkpoint outcome disagrees with mechanical validation")
            if row["continuous_mechanical_witnesses"] > row["validator"]["mechanical_witnesses"]:
                raise ValueError("continuous witness has no current mechanical witness")
            outcomes.update([row["outcome"]])
        games[key] = game
    if dict(outcomes) != report["checkpoint_outcomes"]:
        raise ValueError("checkpoint totals disagree with raw data")
    if sum(game["continuous_mechanical_lineage_to_terminal"] for game in games.values()) != report["continuous_mechanical_games"]:
        raise ValueError("complete lineage totals disagree with raw data")
    return games


def counts(games):
    rows = [row for game in games.values() for row in game["checkpoints"]]
    witnessed = sum(row["outcome"] == "witnessed" for row in rows)
    return {"checkpoints": len(rows), "witnessed": witnessed, "unresolved": len(rows) - witnessed,
            "unresolved_percent": 100 * (len(rows) - witnessed) / len(rows),
            "continuous_witnessed_checkpoints": sum(row["continuous_mechanical_witnesses"] > 0 for row in rows),
            "continuous_games": sum(game["continuous_mechanical_lineage_to_terminal"] for game in games.values()),
            "terminal_witnesses": sum(game["terminal_outcome"] == "witnessed" for game in games.values())}


def compare(baseline, candidate):
    for key in ("showdown_revision", "samples_per_checkpoint", "checkpoint_budget_ms",
                "oracle_seed_offset", "include_mixed_policy"):
        if baseline.get(key) is None or baseline[key] != candidate.get(key):
            raise ValueError("comparison configuration mismatch: " + key)
    identity = baseline.get("source_identity", {}).get("sha256")
    if not identity or identity != candidate.get("source_identity", {}).get("sha256"):
        raise ValueError("comparison runtime source identity mismatch")
    before, after = verified_games(baseline), verified_games(candidate)
    if before.keys() != after.keys():
        raise ValueError("comparison reference cases differ")
    for key in before:
        if not before[key].get("reference_trace_fingerprint") or before[key]["reference_trace_fingerprint"] != after[key].get("reference_trace_fingerprint"):
            raise ValueError("comparison public observation/command traces differ")
    lost = [key for key in before if before[key]["continuous_mechanical_lineage_to_terminal"] and
            not after[key]["continuous_mechanical_lineage_to_terminal"]]
    gained = [key for key in before if not before[key]["continuous_mechanical_lineage_to_terminal"] and
              after[key]["continuous_mechanical_lineage_to_terminal"]]
    return {"schema": "native-frontier-paired-comparison-v1", "source_sha256": identity,
            "paired_reference_games": len(before), "identical_reference_traces": True,
            "baseline_generation": baseline["generation"], "candidate_generation": candidate["generation"],
            "baseline": counts(before), "candidate": counts(after),
            "continuous_regressions": lost, "continuous_gains": gained,
            "production_fallback_measured": False, "promotion_ready": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(json.loads(args.baseline.read_text(encoding="utf-8")),
                     json.loads(args.candidate.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
