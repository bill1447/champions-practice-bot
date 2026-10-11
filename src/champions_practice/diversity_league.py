"""Offline synthetic team/policy coverage matrix; no ladder-strength claim."""

import argparse
import hashlib
import json
import random
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from champions_practice.belief_worlds import PublicSetCandidate
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.demo_fixture import demo_public_priors
from champions_practice.search_worker import TeamValidationWorker
from champions_practice.strength_league import (
    LeagueConfig, _atomic_write_json, _baseline_choice, _git_commit,
    _showdown_revision, _source_identity, run_game, summarize_games,
)


def candidate(species, item, ability, nature, offensive, moves):
    return PublicSetCandidate(species, item, ability, nature,
        (("hp", 2), (offensive, 32), ("spe", 32)), tuple(moves), label="synthetic-diversity-v1")


def catalog():
    pool = demo_public_priors()
    additions = (
        candidate("Incineroar", "Shuca Berry", "Intimidate", "Adamant", "atk",
                  ("Fake Out", "Flare Blitz", "Darkest Lariat", "Parting Shot")),
        candidate("Venusaur", "Coba Berry", "Chlorophyll", "Modest", "spa",
                  ("Sleep Powder", "Sludge Bomb", "Energy Ball", "Protect")),
        candidate("Dragonite", "Lum Berry", "Inner Focus", "Adamant", "atk",
                  ("Extreme Speed", "Dragon Claw", "Stomping Tantrum", "Protect")),
        candidate("Rotom-Wash", "Leftovers", "Levitate", "Modest", "spa",
                  ("Hydro Pump", "Thunderbolt", "Will-O-Wisp", "Protect")),
        candidate("Pelipper", "Focus Sash", "Drizzle", "Modest", "spa",
                  ("Hurricane", "Weather Ball", "Tailwind", "Protect")),
        candidate("Archaludon", "Dragon Fang", "Stamina", "Modest", "spa",
                  ("Electro Shot", "Flash Cannon", "Dragon Pulse", "Protect")),
        candidate("Basculegion", "Mystic Water", "Swift Swim", "Adamant", "atk",
                  ("Wave Crash", "Phantom Force", "Aqua Jet", "Protect")),
        candidate("Tyranitar", "Chople Berry", "Sand Stream", "Adamant", "atk",
                  ("Rock Slide", "Crunch", "Low Kick", "Protect")),
        candidate("Excadrill", "Life Orb", "Sand Rush", "Adamant", "atk",
                  ("High Horsepower", "Iron Head", "Rock Slide", "Protect")),
        candidate("Garchomp", "Haban Berry", "Rough Skin", "Jolly", "atk",
                  ("Dragon Claw", "Stomping Tantrum", "Rock Slide", "Protect")),
    )
    pool.update({mon.species: (mon,) for mon in additions})
    return pool


ROSTERS = {
    "balance": ("Incineroar", "Venusaur", "Dragonite", "Metagross", "Rotom-Wash", "Rillaboom"),
    "rain": ("Pelipper", "Archaludon", "Basculegion", "Gardevoir", "Rillaboom", "Venusaur"),
    "sand": ("Tyranitar", "Excadrill", "Garchomp", "Rotom-Wash", "Incineroar", "Metagross"),
}
POLICIES = ("attack-first", "seeded-mixed", "support-switch")


def team_text(roster):
    pool = catalog()
    return "\n\n".join(pool[species][0].team_text for species in roster) + "\n"


def policy_selector(policy, seed):
    """Only command strings enter these deterministic policy baselines."""
    if policy not in POLICIES:
        raise ValueError("unknown diversity policy")
    rng = random.Random(seed)
    count = 0

    def select(choices):
        nonlocal count
        count += 1
        if policy == "attack-first" or len(choices) == 1:
            return _baseline_choice(choices)
        # Exclude deliberate ally attacks, while preserving all legal switches.
        safe = tuple(sorted(choice for choice in choices if not any(
            token in {"-1", "-2"} for part in choice.split(",")
            for token in part.split()[2:]))) or tuple(sorted(choices))
        if policy == "seeded-mixed":
            return rng.choice(safe)
        if count % 4 == 0:
            switches = tuple(choice for choice in safe if "switch " in choice)
            if switches:
                return rng.choice(switches)
        if count % 3 == 1:
            support = tuple(choice for choice in safe if any(move in choice.lower() for move in
                ("fakeout", "sleeppowder", "tailwind", "trickroom", "partingshot", "willowisp")))
            if support:
                return rng.choice(support)
        return _baseline_choice(safe)

    return select


def audit_report(report):
    """Reconcile persisted traces; absent telemetry remains explicitly unknown."""
    traces = [trace for game in report["games"] for trace in game["decision_trace"]]
    modes = Counter(trace["mode"] for trace in traces)
    admission = Counter()
    native_totals = Counter()
    errors = []
    for trace in traces:
        if not trace.get("complete"):
            errors.append("incomplete-decision")
        if trace["chosen_action"] not in trace["ai_public_choices_before"]:
            errors.append("chosen-action-not-publicly-legal")
        if trace["mode"] == "belief-search" and (trace["particle_count"] <= 0 or trace["branch_count"] <= 0):
            errors.append("search-without-particles-or-branches")
        detail = trace.get("native_admission")
        if not detail:
            admission["not-recorded"] += 1
            continue
        admission[f'{detail["path"]}:{detail["status"]}'] += 1
        for key in ("roots_tried", "native_candidates", "positive_matches", "admitted_particles",
                    "historical_witnesses", "exhaustively_excluded_worlds"):
            native_totals[key] += detail.get(key, 0)
        if detail["status"] == "admitted" and detail.get("positive_matches", 0) <= 0:
            errors.append("admitted-without-positive-match")
    summary = report["summary"]["decisions"]
    expected = {"total": len(traces), "search": modes["belief-search"],
                "forced_wait": modes["forced-wait"],
                "fallback": len(traces) - modes["belief-search"] - modes["forced-wait"],
                "branches": sum(trace["branch_count"] for trace in traces)}
    for key, value in expected.items():
        if summary[key] != value:
            errors.append(f"summary-mismatch:{key}")
    return {"run_id": report["run_id"], "modes": dict(modes), "native_admission": dict(admission),
            "native_totals": dict(native_totals), "errors": errors}


def run_matrix(root, *, budget=8.0, seed=15701):
    pool = catalog()  # Fixed before any hidden match truth is selected.
    teams = {name: team_text(roster) for name, roster in ROSTERS.items()}
    with TeamValidationWorker(root) as validator:
        for name, text in teams.items():
            validation = validator.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=text)
            if not validation.get("valid"):
                raise ValueError(f"invalid synthetic roster {name}: {validation.get('problems')}")
    config = LeagueConfig(battles=9, decision_budget_seconds=budget,
                          conditioning_budget_seconds=budget, seed=seed)
    source = _source_identity(root)
    identity = {"schema": "team-policy-diversity-v1", "config": asdict(config),
                "git_commit": _git_commit(root), "showdown_revision": _showdown_revision(root),
                "source_identity": source, "rosters": ROSTERS, "policies": POLICIES,
                "teams_sha256": {name: hashlib.sha256(text.encode()).hexdigest() for name, text in teams.items()},
                "prior_catalog_sha256": hashlib.sha256("\n".join(
                    mon.team_text for candidates in pool.values() for mon in candidates).encode()).hexdigest()}
    run_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    output = root / "runs" / "diversity-league" / run_id
    games, cells, failures = [], [], []
    names = tuple(ROSTERS)
    for team_index, name in enumerate(names):
        for policy_index, policy in enumerate(POLICIES):
            index = team_index * len(POLICIES) + policy_index
            own = names[(team_index + policy_index) % len(names)]
            cell = {"opponent_roster": name, "own_roster": own, "opponent_policy": policy}

            def retain(trace, stage):
                _atomic_write_json(output / "partial-report.json", {
                    **identity, "run_id": run_id, "cells": cells, "games": [asdict(g) for g in games],
                    "failed_cells": failures,
                    "active_cell": cell, "stage": stage, "decision_trace": trace})

            try:
                result = run_game(config, game_index=index, project_root=root,
                    baseline_selector=policy_selector(policy, seed + index), trace_sink=retain,
                    fixture_override={"ai_team": teams[own], "opponent_team": teams[name],
                        "opponent_priors": pool, "ai_preview": "team 1234", "opponent_preview": "team 1234"})
            except RuntimeError as error:
                # Preserve the last public checkpoint, never exception text or
                # sealed native data. A failed cell is not a completed loss.
                saved = json.loads((output / "partial-report.json").read_text())
                _atomic_write_json(output / f"failed-cell-{index}.json", saved)
                failures.append({**cell, "game_index": index, "error_type": type(error).__name__,
                                 "checkpoint": f"failed-cell-{index}.json"})
                print(f'{name}/{policy}: failed {type(error).__name__}', flush=True)
                continue
            games.append(result)
            cells.append(cell)
            print(f'{name}/{policy} own={own}: {result.decisions} decisions, {result.fallback_decisions} fallbacks', flush=True)
    if _source_identity(root) != source or _git_commit(root) != identity["git_commit"]:
        raise RuntimeError("source changed during diversity matrix")
    report = {**identity, "run_id": run_id, "cells": cells, "failed_cells": failures,
              "games": [asdict(g) for g in games], "summary": summarize_games(tuple(games)),
              "limitations": ["Synthetic fixed public catalog; no external corpus or uncertainty calibration.",
                              "One seed per cell; baselines are command policies, not ladder opponents.",
                              "Own and opponent rosters vary; cell differences are not causal policy comparisons."]}
    report["audit"] = audit_report(report)
    _atomic_write_json(output / "report.json", report)
    print(output / "report.json", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=float, default=8.0)
    parser.add_argument("--seed", type=int, default=15701)
    args = parser.parse_args()
    run_matrix(Path(__file__).resolve().parents[2], budget=args.budget, seed=args.seed)


if __name__ == "__main__":
    main()
