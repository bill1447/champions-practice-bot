"""11B: known teams/actions, unknown RNG, complete-game isolated audit."""

import argparse
from collections import Counter
import json
import hashlib
from pathlib import Path
from time import perf_counter
import tracemalloc

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.diversity_league import ROSTERS, policy_selector, team_text
from champions_practice.native_stochastic_tracker import NativeStochasticTracker, PROJECT_ROOT
from champions_practice.native_stochastic_validator import (
    continuous_witness_lineages, first_difference, mechanical_projection, validate_checkpoint,
)
from champions_practice.observation_beliefs import public_observation_signature
from champions_practice.persistent_admission_smoke import SEEDS, SPECIES, fixture
from champions_practice.search_worker import ShowdownRequestError, ShowdownSearchWorker
from champions_practice.strength_league import _git_commit, _showdown_revision, _source_identity
from champions_practice.teams import SMOKE_TEAM


def run_game(oracle, chance_validator, *, label, p1_team, p2_team, policy, oracle_seed, samples, budget_ms,
             script=(), max_submissions=180, generation="sampled"):
    with NativeStochasticTracker() as tracker:
        p1_team = tracker.canonical_team(p1_team)
        p2_team = tracker.canonical_team(p2_team)
        # Canonical export blocks begin with the species; do not parse move lines.
        previews = {side: [block.splitlines()[0].split(" (")[0].split(" @")[0].strip()
                           for block in team.strip().split("\n\n")]
                    for side, team in (("p1", p1_team), ("p2", p2_team))}
        preview = script[0] if script else ("team 1234", "team 1234")
        session = oracle.start_session(battle_format=CHAMPIONS_FORMAT,
            p1_team=p1_team, p2_team=p2_team, seed=oracle_seed,
            p1_name="Search P1", p2_name="Search P2")["session_id"]
        selectors = [policy_selector(policy, 31101), policy_selector(policy, 31102)]
        rows = []
        continuous_lineages = set()
        started = perf_counter()
        try:
            oracle.choose_session(session, p1_choice=preview[0], p2_choice=preview[1])
            view = oracle.session_view(session, side="p1")["view"]
            opening = tracker.initialize(p1_team=p1_team, p2_team=p2_team,
                p1_preview=preview[0], p2_preview=preview[1], public_view=view)
            telemetry = opening
            for checkpoint in range(max_submissions + 1):
                if view["ended"]:
                    commands = None
                else:
                    commands = tuple(selectors[i](oracle.session_legal_choices(session, side=side))
                                     for i, side in enumerate(("p1", "p2")))
                    if checkpoint + 1 < len(script):
                        commands = script[checkpoint + 1]
                inspection = tracker.inspection_for_validator()
                validation = validate_checkpoint(oracle, session, inspection, view, previews, commands)
                continuous_lineages = continuous_witness_lineages(continuous_lineages,
                    validation.get("witness_ancestry", []), opening=checkpoint == 0)
                outcome = "witnessed" if validation["mechanical_witnesses"] else "unresolved"
                row = {"checkpoint": checkpoint, "turn": view["turn"], "phase": view["phase"],
                       "terminal": view["ended"], "outcome": outcome,
                       "public_current": inspection["current"], "tracker": telemetry, "validator": validation,
                       "continuous_mechanical_witnesses": len(continuous_lineages),
                       "public_observation_fingerprint": hashlib.sha256(
                           public_observation_signature(view).encode()).hexdigest(),
                       "submitted_commands": commands,
                       "python_current_bytes": tracemalloc.get_traced_memory()[0],
                       "python_peak_bytes": tracemalloc.get_traced_memory()[1]}
                if inspection["current"] and not validation["mechanical_witnesses"]:
                    row["failure_stage"] = (
                        "particle-selection-loss" if validation["oracle_mechanical_fingerprint"] in
                        telemetry.get("public_match_mechanical_keys", []) else
                        "branch-generation-unrepresented-native-history"
                    )
                elif not inspection["current"]:
                    row["failure_stage"] = telemetry.get("reason")
                rows.append(row)
                if view["ended"]:
                    break
                if checkpoint == max_submissions:
                    raise AssertionError("reference game did not terminate")
                # Oracle-only check: never returns its tape or a repair to tracker.
                before = oracle.session_snapshot(session)["state"]
                instrumentation = chance_validator.request("validate_chance_trace", state=before,
                    p1_choice=commands[0], p2_choice=commands[1], previews=previews)
                row["isolated_chance_instrumentation"] = instrumentation
                oracle.choose_session(session, p1_choice=commands[0], p2_choice=commands[1])
                view = oracle.session_view(session, side="p1")["view"]
                telemetry = tracker.advance(p1_choice=commands[0], p2_choice=commands[1], public_view=view,
                                            samples=samples, milliseconds=budget_ms, generation=generation)
            return {"fixture": label, "policy": policy, "completed_reference_game": True,
                    "checkpoints": rows, "seconds": perf_counter() - started,
                    "terminal_outcome": rows[-1]["outcome"],
                    "continuous_mechanical_lineage_to_terminal": bool(continuous_lineages),
                    "reference_trace_fingerprint": hashlib.sha256(json.dumps([
                        (row["public_observation_fingerprint"], row["submitted_commands"]) for row in rows
                    ], separators=(",", ":")).encode()).hexdigest(),
                    "outcomes": dict(Counter(row["outcome"] for row in rows))}
        finally:
            oracle.close_session(session)


def positive_and_negative_controls(oracle):
    team, _ = fixture()
    with NativeStochasticTracker() as tracker:
        team = tracker.canonical_team(team)
        session = oracle.start_session(battle_format=CHAMPIONS_FORMAT, p1_team=team, p2_team=team,
            seed=SEEDS[0], p1_name="Search P1", p2_name="Search P2")["session_id"]
        try:
            oracle.choose_session(session, p1_choice="team 4123", p2_choice="team 2314")
            opening = oracle.session_view(session)["view"]
            tracker.initialize(p1_team=team, p2_team=team, p1_preview="team 4123", p2_preview="team 2314",
                               public_view=opening)
            commands = ("move willowisp +1, move protect", "move dragonclaw -2, move protect")
            oracle.choose_session(session, p1_choice=commands[0], p2_choice=commands[1])
            target = oracle.session_view(session)["view"]
            reference = oracle.session_snapshot(session)["state"]
            if not any(mon["status"] == "brn" for mon in reference["sides"][1]["pokemon"]):
                raise AssertionError("positive control oracle did not realize reachable burn")
            missed = tracker.advance(p1_choice=commands[0], p2_choice=commands[1], public_view=target,
                                     samples=1, force_chance_false=True, milliseconds=1000)
            if missed["outcome"] != "unresolved" or missed["public_matches"] != 0:
                raise AssertionError("known reachable unsampled outcome was incorrectly classified")
            reached = tracker.finite_control(p1_choice=commands[0], p2_choice=commands[1], public_view=target)
            if reached["outcome"] != "witnessed":
                raise AssertionError("finite control did not witness known reachable outcome")
            mismatch = first_difference(mechanical_projection(reference), mechanical_projection(reached["witness"]))
            if mismatch:
                raise AssertionError("finite witness native mechanics mismatch: " + mismatch)
            # The positive target contains a burn; all-Protect cannot create it.
            impossible = tracker.finite_control(p1_choice="move protect, move protect",
                p2_choice="move protect, move protect", public_view=target)
            if impossible["outcome"] != "disproved" or not impossible["exhaustive"]:
                raise AssertionError("finite negative control was not exhaustively disproved")
            bounded = tracker.finite_control(p1_choice=commands[0], p2_choice=commands[1],
                                            public_view=target, max_nodes=1)
            if bounded["outcome"] != "unresolved":
                raise AssertionError("finite budget exhaustion became disproof")
            with NativeStochasticTracker() as guided:
                guided.initialize(p1_team=team, p2_team=team, p1_preview="team 4123",
                                  p2_preview="team 2314", public_view=opening)
                guided_result = guided.advance(p1_choice=commands[0], p2_choice=commands[1],
                    public_view=target, generation="guided", samples=512, milliseconds=5000)
                guided_validation = validate_checkpoint(oracle, session, guided.inspection_for_validator(),
                    target, {"p1": list(SPECIES), "p2": list(SPECIES)})
                if not guided_validation["mechanical_witnesses"]:
                    raise AssertionError("guided generation lost the known reachable burn control")
                zero_budget = guided.advance(p1_choice="move protect, move protect",
                    p2_choice="move protect, move protect", public_view=target, milliseconds=0)
                if zero_budget["outcome"] != "unresolved" or not zero_budget["deadline_exhausted"]:
                    raise AssertionError("zero-budget sampled transition did not remain unresolved")
            with NativeStochasticTracker() as frontier:
                frontier.initialize(p1_team=team, p2_team=team, p1_preview="team 4123",
                                    p2_preview="team 2314", public_view=opening)
                frontier_result = frontier.advance(p1_choice=commands[0], p2_choice=commands[1],
                    public_view=target, generation="frontier", samples=512, milliseconds=5000)
                frontier_validation = validate_checkpoint(oracle, session, frontier.inspection_for_validator(),
                    target, {"p1": list(SPECIES), "p2": list(SPECIES)})
                if not frontier_validation["mechanical_witnesses"]:
                    raise AssertionError("public-first frontier lost the known reachable burn control")
            discovery_controls = {}
            for mode in ("guided", "frontier"):
                with NativeStochasticTracker() as discovery:
                    discovery.initialize(p1_team=team, p2_team=team, p1_preview="team 4123",
                                         p2_preview="team 2314", public_view=opening)
                    discovery_controls[mode] = discovery.advance(p1_choice=commands[0], p2_choice=commands[1],
                        public_view=target, generation=mode, samples=max(1, guided_result["first_public_match_call"] - 1),
                        milliseconds=5000)
            for key in ("generated_branches", "public_matches", "incomplete_prefixes", "public_prefix_pruned",
                        "parent_call_counts", "first_public_match_call"):
                if discovery_controls["guided"][key] != discovery_controls["frontier"][key]:
                    raise AssertionError("frontier changed guided discovery before first public match: " + key)
            if any(lane["calls"] for lane in discovery_controls["frontier"]["frontier_lanes"][1:]):
                raise AssertionError("frontier spent discovery budget on alternate lanes before a public match")
            with NativeStochasticTracker() as storage:
                storage.initialize(p1_team=team, p2_team=team, p1_preview="team 4123",
                                   p2_preview="team 2314", public_view=opening)
                storage_control = storage.advance(p1_choice=commands[0], p2_choice=commands[1],
                    public_view=target, generation="frontier", samples=512, milliseconds=5000, max_bytes=1)
                if (storage_control["outcome"] != "unresolved" or not storage_control["public_matches"] or
                        storage_control["reason"] != "particle-storage-budget-exhausted"):
                    raise AssertionError("particle-storage exhaustion did not remain explicitly unresolved")
            return {"initial_sample": missed, "reachable_finite_outcome": {
                        key: value for key, value in reached.items() if key != "witness"},
                    "native_mechanics_equal": True,
                    "rng_serialization_differs": reference["prng"] != reached["witness"]["prng"],
                    "exhaustive_negative": impossible, "budget_control": bounded,
                    "guided_positive": guided_result,
                    "guided_positive_mechanical_witnesses": guided_validation["mechanical_witnesses"],
                    "frontier_positive": frontier_result,
                    "frontier_positive_mechanical_witnesses": frontier_validation["mechanical_witnesses"],
                    "pre_match_discovery_parity": discovery_controls,
                    "storage_budget_control": storage_control,
                    "zero_budget_control": zero_budget,
                    "oracle_seed_or_state_given_to_tracker": False}
        finally:
            oracle.close_session(session)


def run(samples=96, budget_ms=600, generation="sampled", oracle_seed_offset=0, include_mixed=False):
    tracemalloc.start()
    games = []
    with ShowdownSearchWorker() as oracle, ShowdownSearchWorker(
        worker_script=PROJECT_ROOT / "tools/native-stochastic-validator.js"
    ) as chance_validator:
        controls = positive_and_negative_controls(oracle)
        controls["privacy_canary_rejections"] = privacy_controls()
        teams = {"mirror": SMOKE_TEAM, **{label: team_text(roster) for label, roster in ROSTERS.items()}}
        for index, (label, team) in enumerate(teams.items()):
            for policy in (("attack-first", "support-switch", "seeded-mixed") if include_mixed else
                           ("attack-first", "support-switch")):
                games.append(run_game(oracle, chance_validator, label=label, p1_team=team, p2_team=teams["balance"],
                    policy=policy, oracle_seed=SEEDS[(index + oracle_seed_offset) % len(SEEDS)], samples=samples, budget_ms=budget_ms,
                    generation=generation))
        team, _ = fixture()
        for label, script in (
            ("burn-bench-return", (("team 4123", "team 2314"),
                ("move willowisp +1, move protect", "move dragonclaw +2, move protect"),
                ("move protect, move protect", "switch 3, move protect"),
                ("move protect, move protect", "switch 3, move protect"))),
            ("pivot-queue", (("team 1234", "team 1234"),
                ("move partingshot +1, move protect", "move partingshot +1, move protect"))),
        ):
            games.append(run_game(oracle, chance_validator, label=label, p1_team=team, p2_team=team,
                policy="attack-first", oracle_seed=SEEDS[oracle_seed_offset], samples=samples, budget_ms=budget_ms, script=script,
                generation=generation))
    rows = [row for game in games for row in game["checkpoints"]]
    first_losses = []
    for game in games:
        first = next((row for row in game["checkpoints"] if row["outcome"] == "unresolved"), None)
        if first:
            first_losses.append({"fixture": game["fixture"], "policy": game["policy"],
                **{key: first.get(key) for key in ("checkpoint", "turn", "phase", "failure_stage")},
                "generated_branches": first["tracker"].get("generated_branches", 0),
                "public_matches": first["tracker"].get("public_matches", 0),
                "selection_losses": first["tracker"].get("selection_losses", 0),
                "public_match_diversity": first["tracker"].get("public_match_diversity"),
                "retained_diversity": first["tracker"].get("retained_diversity"),
                "parent_diversity": first["tracker"].get("parent_diversity"),
                "first_public_match_call": first["tracker"].get("first_public_match_call"),
                "native_mismatch_paths": first["validator"]["native_mismatch_paths"]})
    instrumentation = [row["isolated_chance_instrumentation"] for row in rows
                       if "isolated_chance_instrumentation" in row]
    if any(row["tracker"].get("sampled_miss_disproved", False) for row in rows):
        raise AssertionError("sampled uncertainty was treated as disproof")
    return {"schema": "continuous-native-unknown-rng-v1", "phase": "11B",
        "git_commit": _git_commit(PROJECT_ROOT), "showdown_revision": _showdown_revision(PROJECT_ROOT),
        "source_identity": _source_identity(PROJECT_ROOT), "production_changed": False,
        "samples_per_checkpoint": samples, "checkpoint_budget_ms": budget_ms,
        "generation": generation,
        "oracle_seed_offset": oracle_seed_offset, "include_mixed_policy": include_mixed,
        "controls": controls, "games": games, "completed_reference_games": len(games),
        "checkpoint_outcomes": dict(Counter(row["outcome"] for row in rows)),
        "terminal_outcomes": dict(Counter(game["terminal_outcome"] for game in games)),
        "continuous_mechanical_games": sum(game["continuous_mechanical_lineage_to_terminal"] for game in games),
        "generated_branches": sum(row["tracker"].get("generated_branches", 0) for row in rows),
        "public_prefix_pruned": sum(row["tracker"].get("public_prefix_pruned", 0) for row in rows),
        "future_comparisons": sum(row["validator"]["future_comparisons"] for row in rows),
        "first_losses": first_losses,
        "isolated_chance_checks": dict(Counter("native-equal" if check["supported"] else
                                              "unsupported" for check in instrumentation)),
        "resources": {
            "deadline_exhaustions": sum(row["tracker"].get("deadline_exhausted", False) for row in rows),
            "selection_losses": sum(row["tracker"].get("selection_losses", 0) for row in rows),
            **{f"maximum_{key}": max(row["tracker"].get(key, 0) for row in rows)
               for key in ("particles", "particle_bytes", "worker_rss_bytes", "worker_heap_bytes", "processing_ms")},
            "python_peak_bytes": tracemalloc.get_traced_memory()[1],
            "deadline_scope": "cooperative, checked between native branches; eight-second transport timeout",
        },
        "diversity": {f"maximum_{stage}_{field}": max(row["tracker"].get(stage, {}).get(field, 0) for row in rows)
                      for stage in ("public_match_diversity", "retained_diversity", "parent_diversity")
                      for field in ("speed_order_classes", "damage_history_classes")},
        "observed_false_exclusions": 0,
        "promotion_ready": False,
        "current_mechanics_not_prng_identity": True,
        "limitations": ["Witnessed is existence of a retained mechanically equivalent native history, not exhaustive coverage",
            "Finite-tape chance inputs do not certify a single cryptographic seed for an entire history",
            "Sample proposal weights are not a calibrated posterior",
            "No catch-up after first unresolved public transition; stale states are never current",
            "No production fallback or strength measurement"],
    }


def privacy_controls():
    rejected = 0
    with ShowdownSearchWorker(worker_script=PROJECT_ROOT / "tools/native-stochastic-worker.js") as worker:
        for operation, payload in (
            ("initialize", {"seed": "oracle-private-canary"}),
            ("advance", {"state": {"prng": "oracle-private-canary"}}),
            ("advance", {"view": {"prng": "oracle-private-canary"}}),
            ("advance", {"view": {"seed": "oracle-private-canary"}}),
            ("session_snapshot", {"session_id": "oracle-private-canary"}),
        ):
            try:
                worker.request(operation, **payload)
            except ShowdownRequestError:
                rejected += 1
            else:
                raise AssertionError("experimental tracker accepted a privileged canary")
    return rejected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs/native-stochastic/report.json"))
    parser.add_argument("--samples", type=int, default=96)
    parser.add_argument("--budget-ms", type=int, default=600)
    parser.add_argument("--generation", choices=("sampled", "guided", "stratified", "spread", "frontier"), default="sampled")
    parser.add_argument("--oracle-seed-offset", type=int, choices=range(len(SEEDS)), default=0)
    parser.add_argument("--include-mixed-policy", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.samples <= 512 or not 0 <= args.budget_ms <= 5000:
        parser.error("samples must be 1..512 and budget-ms must be 0..5000")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = run(args.samples, args.budget_ms, args.generation, args.oracle_seed_offset, args.include_mixed_policy)
    except Exception as error:
        args.output.write_text(json.dumps({"phase": "11B", "audit_failed": True,
            "error": str(error), "production_changed": False}, indent=2) + "\n", encoding="utf-8")
        raise
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"11B: {report['completed_reference_games']} complete reference games; "
          f"checkpoints {report['checkpoint_outcomes']}; terminal {report['terminal_outcomes']}")
    print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
