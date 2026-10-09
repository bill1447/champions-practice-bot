"""Independent, deliberately failure-visible real-collapse rebase challenge.

The frozen eight-game report is a **historical outcome reference**, NOT a
present-turn reconstruction fixture: it lacks sanitized full public snapshots,
exact owned commands per turn, and a native hidden-state oracle. A successful
rebase cannot be inferred from that report. Reproduce a game to collect the
missing evidence and run #185/#186's *isolated* current-state constructors in
parallel with the unchanged production league, never in its decision path.

The independent offline oracle uses the known benchmark teams/seed/actions.
Human commands and the oracle state are passed ONLY to the evaluator; the
reconstruction function accepts only public views, own commands, approved
public priors and its own previously verified public checkpoint. Any oracle
mismatch makes truth survival unmeasurable, never success.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from champions_practice.belief_controller import SealedBattleFacade
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.current_state_proposals import (
    CurrentStateProposalBatch,
    build_current_state_set_proposals,
)
from champions_practice.demo_fixture import (
    DEMO_AI_PREVIEW_CHOICE,
    DEMO_AI_TEAM,
    DEMO_HUMAN_TEAM,
    demo_public_priors,
)
from champions_practice.observation_beliefs import public_observation_signature
from champions_practice.public_scaffold_bootstrap import bootstrap_public_current_scaffolds
from champions_practice.rolling_public_checkpoints import (
    PublicRebaseCheckpoint,
    advance_rolling_public_checkpoints,
    validate_public_bootstrap_checkpoint,
)
from champions_practice.search_worker import (
    HypotheticalSearchWorker,
    ShowdownSearchWorker,
)
from champions_practice.strength_league import (
    LeagueConfig, _baseline_choice, _particle_seed,
    _resolve_preview_choice, _sodium_seed,
)


CHALLENGE_SCHEMA = "public-rebase-real-collapse-challenge-v1"
FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests" / "fixtures" / "frozen-rebase-collapse-v1.json"
)
# Bound every isolated probe. An 8s miss is recorded as a failure even when
# a later witness was found; worker startup and production AI time are separate.
BUDGET_SECONDS = 8.0


def load_targets() -> dict[str, Any]:
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    if data["schema"] != "frozen-collapse-targets-v1":
        raise ValueError("unrecognized frozen target manifest")
    if data["source"]["pinned_showdown_revision"] != (
        "a5df8274e85b0889bf2a9b3422a08b39732374fc"
    ):
        raise ValueError("frozen target pins a different simulator revision")
    return data


def evaluate_historical_report(report: dict, targets: dict) -> dict[str, Any]:
    """Pin the ACTUAL user report, never manufacture missing public/oracle data."""
    source = targets["source"]
    if (
        report.get("schema") != "offline-strength-league-v1"
        or report.get("run_id") != source["run_id"]
        or report.get("git_commit") != source["git_commit"]
        or report.get("showdown_revision") != source["pinned_showdown_revision"]
        or report.get("fixture_id") != source["fixture_id"]
        or report.get("config", {}).get("seed") != source["seed"]
    ):
        raise ValueError("historical report provenance does not match the frozen target")
    summary = report["summary"]
    expected = targets["baseline"]
    for observed, wanted in (
        (len(report["games"]), expected["games"]),
        (summary["decisions"]["total"], expected["decisions"]),
        (summary["decisions"]["fallback"], expected["fallback_decisions"]),
        (summary["decisions"]["degraded_turns"], expected["degraded_turns"]),
        (summary["recovery"]["events"], expected["recovery_events"]),
        (summary["recovery"]["retry_deadline_timeouts"], expected["deadline_timeouts"]),
    ):
        if observed != wanted:
            raise ValueError("frozen report measurements disagree with reference")

    output = []
    for case in targets["cases"]:
        game = report["games"][case["game_index"]]
        records = game["recovery_events"]
        if (
            game["game_index"] != case["game_index"]
            or game["fallback_decisions"] != case["fallback_decisions"]
            or game["degraded_turns"] != case["degraded_turns"]
            or len(records) != len(case["observation_turns"])
            or [r["observation_turn"] for r in records] != case["observation_turns"]
            or records[0]["reason"] != "zero-sampled-match"
            or any(r["reason"] != "pending-backlog" for r in records[1:])
        ):
            raise ValueError("frozen collapse case drifted from submitted report")
        observed = {
            json.loads(a)["move"]
            for a in records[0]["observed_opponent_actions"]
            if "move" in json.loads(a)
        }
        if not set(case["initial_actions"]).issubset(observed):
            raise ValueError("frozen initial collapse action evidence changed")
        output.append({
            "game_number": case["game_number"],
            "initial_collapse_turn": case["initial_collapse_turn"],
            "actual_degraded_turns": case["degraded_turns"],
            "actual_fallback_decisions": case["fallback_decisions"],
            "legacy_reasons": [x["reason"] for x in records],
            "reconstruction_status": "NOT_EVALUATED_NO_PUBLIC_CHECKPOINTS",
            "valid_current_turn_states": None,
            "true_world_survived": None,
            "retained_information": None,
            "reconstruction_seconds": None,
            "backlog_escaped": None,
            "proof_of_success": False,
        })
    return {
        "schema": CHALLENGE_SCHEMA,
        "mode": "historical-report-only",
        "reference_run_id": source["run_id"],
        "baseline": expected,
        "cases": output,
        "evaluated_cases": 0,
        "successful_cases": 0,
        "verdict": "NOT_TESTED_INSUFFICIENT_RUNTIME_EVIDENCE",
    }


def _native_mechanics(state: dict[str, Any]) -> str:
    """Oracle-only comparison: exclude log and PRNG position, not battle mechanics.

    A mismatch never authorizes exclusion from the live belief. RNG trajectory
    equality would be too strict for alternative current hidden-state worlds.
    """
    selected = {
        key: value for key, value in state.items()
        if key not in {"log", "prng"}
    }
    return json.dumps(selected, sort_keys=True, separators=(",", ":"))


def _public_signature_match(first: dict, second: dict) -> bool:
    return (
        public_observation_signature(first) == public_observation_signature(second)
        and json.dumps(first.get("request"), sort_keys=True) ==
        json.dumps(second.get("request"), sort_keys=True)
    )


@dataclass(frozen=True)
class PublicRebaseStep:
    checkpoints: tuple[PublicRebaseCheckpoint, ...]
    current_batch: CurrentStateProposalBatch | None
    ledger: PublicConstraintLedger | None
    elapsed_seconds: float
    reason: str
    native_branches: int


def _public_only_step(
    worker: HypotheticalSearchWorker,
    *,
    first_turn: bool,
    opening_view: dict,
    previous_view: dict,
    current_view: dict,
    previous_ledger: PublicConstraintLedger | None,
    previous_batch: CurrentStateProposalBatch | None,
    checkpoints: tuple[PublicRebaseCheckpoint, ...],
    own_choice: str,
    seed: str,
) -> PublicRebaseStep:
    """The ONLY path given to the reconstruction engine.

    Deliberately no oracle state, real opponent command, live-worker session,
    truth team, or legacy particle argument.
    """
    started = perf_counter()
    try:
        ledger = (
            previous_ledger.advance(current_view)
            if previous_ledger is not None
            else PublicConstraintLedger.from_public_view(current_view)
        )
        batch = build_current_state_set_proposals(
            ledger=ledger, current_view=current_view,
            priors=demo_public_priors(), limit=16,
        )
        if not batch.proposals:
            reason = "NO_APPROVED_PUBLIC_PRIOR"
            return PublicRebaseStep((), batch, ledger, perf_counter()-started, reason, 0)

        # Deterministic exploratory seeds, not the true hidden RNG state.
        seeds = tuple(
            "sodium," + hashlib.sha256(
                f"public-only:{seed}:{current_view['turn']}:{i}".encode()
            ).hexdigest()
            for i in range(4)
        )
        if first_turn:
            report = bootstrap_public_current_scaffolds(
                worker, opening_view=opening_view, current_view=current_view,
                ledger=ledger, prior_batch=batch,
                battle_format=CHAMPIONS_FORMAT, ai_team=DEMO_AI_TEAM,
                ai_preview_choice=DEMO_AI_PREVIEW_CHOICE,
                known_own_choice=own_choice, rng_seeds=seeds,
                max_roots=4, max_opponent_choices=8,
                max_branches=32, max_witnesses=4,
            )
            certified = tuple(
                value for witness in report.witnesses
                if (value := validate_public_bootstrap_checkpoint(
                    worker, witness=witness, ledger=ledger,
                    current_view=current_view, prior_batch=batch,
                )) is not None
            )
            reason = "POSITIVE_CHECKPOINT" if certified else (
                report.unsupported_reason or "NO_VERIFIED_FIRST_CHECKPOINT"
            )
            return PublicRebaseStep(
                certified, batch, ledger, perf_counter()-started,
                reason, report.simulated_branches,
            )
        if not checkpoints or previous_ledger is None or previous_batch is None:
            return PublicRebaseStep(
                (), batch, ledger, perf_counter()-started,
                "NO_INDEPENDENT_PREVIOUS_CHECKPOINT", 0,
            )
        report = advance_rolling_public_checkpoints(
            worker,
            previous_view=previous_view, current_view=current_view,
            previous_ledger=previous_ledger, current_ledger=ledger,
            previous_prior_batch=previous_batch, prior_batch=batch,
            checkpoints=checkpoints,
            known_own_choice=own_choice, rng_seeds=seeds,
            max_checkpoints=4, max_opponent_choices=8,
            max_branches=32, max_witnesses=4,
        )
        return PublicRebaseStep(
            report.checkpoints, batch, ledger, perf_counter()-started,
            "POSITIVE_CHECKPOINT" if report.checkpoints else (
                report.unresolved_reason or "NO_VERIFIED_ROLLING_CHECKPOINT"
            ), report.simulated_branches,
        )
    except (ValueError, KeyError, RuntimeError) as error:
        return PublicRebaseStep(
            (), None, None, perf_counter()-started,
            f"UNSUPPORTED_RECONSTRUCTION:{type(error).__name__}:{error}", 0,
        )


def run_case(game_index: int, *, max_decisions: int = 18) -> dict[str, Any]:
    """Fresh deterministic strength-league run, with separate oracle and rebase."""
    config = LeagueConfig(
        battles=1, max_decisions=max_decisions, seed=15601,
    )
    session_seed = _sodium_seed(config.seed, game_index)
    rows: list[dict[str, Any]] = []
    with (
        SealedBattleFacade(
            battle_format=CHAMPIONS_FORMAT,
            ai_team=DEMO_AI_TEAM,
            ai_preview_choice=DEMO_AI_PREVIEW_CHOICE,
            opponent_priors=demo_public_priors(),
            world_limit=config.world_limit,
            particles_per_world=config.particles_per_world,
            max_particles=config.max_particles,
            candidate_limit=config.candidate_limit,
            response_limit=config.response_limit,
            strategic_plan_limit=config.strategic_plan_limit,
            strategic_candidate_limit=config.strategic_candidate_limit,
            strategic_response_limit=config.strategic_response_limit,
            decision_budget_seconds=config.decision_budget_seconds,
            conditioning_budget_seconds=config.conditioning_budget_seconds,
            worker_startup_timeout_seconds=config.worker_startup_timeout_seconds,
            particle_seed=_particle_seed(config.seed, game_index),
        ) as battle,
        ShowdownSearchWorker(startup_timeout_seconds=30.0) as reference_worker,
        HypotheticalSearchWorker() as reconstruction_worker,
    ):
        battle.start(
            opponent_team=DEMO_HUMAN_TEAM,
            p1_name="League Baseline", p2_name="League Bot",
            session_seed=session_seed,
        )
        baseline_preview = _resolve_preview_choice(
            battle.legal_human_choices(), DEMO_AI_PREVIEW_CHOICE,
        )
        battle.commit_preview(human_choice=baseline_preview)
        # Separate offline oracle has its OWN pinned session, completely
        # independent of the sealed facade's session/worker. Native session
        # execution must match native live execution: branch_many uses a
        # hypothetical RNG path that is not the same as session_choose.
        # The oracle's private snapshot NEVER reaches _public_only_step.
        started_oracle = reference_worker.start_session(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=DEMO_HUMAN_TEAM, p2_team=DEMO_AI_TEAM,
            p1_name="League Baseline", p2_name="League Bot",
            seed=session_seed,
        )
        oracle_session_id = started_oracle["session_id"]
        reference_worker.choose_session(
            oracle_session_id,
            p1_choice=baseline_preview,
            p2_choice=DEMO_AI_PREVIEW_CHOICE,
        )
        opening_view = reference_worker.session_view(
            oracle_session_id, side="p2",
        )["view"]
        # The facade exposes the *human* p1 view here; the reconstruction
        # deliberately uses the choosing AI's p2 view above. Compare like
        # with like, never p1 with p2 (different requests and team secrets).
        oracle_human_opening = reference_worker.session_view(
            oracle_session_id, side="p1",
        )["view"]
        if not _public_signature_match(oracle_human_opening, battle.public_state()):
            raise RuntimeError(
                "independent oracle diverges from human-side opening public view"
            )
        prior_view = opening_view
        prior_ledger = PublicConstraintLedger.from_public_view(opening_view)
        prior_batch = build_current_state_set_proposals(
            ledger=prior_ledger, current_view=opening_view,
            priors=demo_public_priors(), limit=16,
        )
        checkpoints: tuple[PublicRebaseCheckpoint, ...] = ()
        for decision_index in range(max_decisions):
            choices = battle.legal_human_choices()
            if not choices:
                break
            human_choice = _baseline_choice(choices)
            ready = battle.lock_ai_action()
            result = battle.commit_human_action(
                token=ready.token, human_choice=human_choice,
            )
            reference_worker.choose_session(
                oracle_session_id,
                p1_choice=human_choice,
                p2_choice=result.decision.choice,
            )
            # The evaluator alone owns this second worker's oracle state.
            # No function reconstructing public-only scaffolds receives it.
            oracle_view = reference_worker.session_view(
                oracle_session_id, side="p2",
            )["view"]
            oracle_state = reference_worker.session_snapshot(
                oracle_session_id,
            )["state"]
            current_view = result.public_view
            oracle_valid = _public_signature_match(oracle_view, current_view)
            if not oracle_valid:
                # No truth inference from a non-identical replay.
                rows.append({
                    "decision_index": decision_index,
                    "observation_turn": current_view.get("turn"),
                    "oracle_valid": False,
                    "status": "UNSUPPORTED_ORACLE_PUBLIC_DIVERGENCE",
                    "verified_current_states": 0,
                    "true_world_survived": None,
                    "reconstruction_seconds": None,
                    "within_8_seconds": None,
                    "backlog_escaped": None,
                    "retained_information": None,
                    "legacy_degraded": result.degraded,
                    "legacy_recovery_reason": (
                        result.recovery_diagnostic.reason
                        if result.recovery_diagnostic else None
                    ),
                })
                break
            step = _public_only_step(
                reconstruction_worker,
                first_turn=decision_index == 0,
                opening_view=opening_view,
                previous_view=prior_view,
                current_view=current_view,
                previous_ledger=prior_ledger,
                previous_batch=prior_batch,
                checkpoints=checkpoints,
                own_choice=result.decision.choice,
                seed=session_seed,
            )
            checkpoints = step.checkpoints
            prior_view = current_view
            prior_ledger = step.ledger
            prior_batch = step.current_batch
            # Truth is inspected ONLY in this evaluator, after the constructor.
            survived = any(
                _native_mechanics(candidate.state) == _native_mechanics(oracle_state)
                for candidate in checkpoints
            ) if checkpoints else False
            actual_collapse = result.recovery_diagnostic is not None
            bounded = step.elapsed_seconds <= BUDGET_SECONDS
            ledger = step.ledger
            rows.append({
                "decision_index": decision_index,
                "observation_turn": current_view.get("turn"),
                "oracle_valid": True,
                "status": step.reason,
                "verified_current_states": len(checkpoints),
                "true_world_survived": survived,
                "reconstruction_seconds": round(step.elapsed_seconds, 6),
                "within_8_seconds": bounded,
                "backlog_escaped": bool(checkpoints and bounded)
                if actual_collapse else None,
                "retained_information": {
                    "cumulative_public_records": len(ledger.records) if ledger else None,
                    "confirmed_moves": (
                        sum(len(item.moves) for item in ledger.known_sets)
                        if ledger else None
                    ),
                    "posterior_entropy": None,
                    "true_world_posterior_weight": None,
                    "fully_measured": False,
                },
                "native_branches": step.native_branches,
                "legacy_degraded": result.degraded,
                "legacy_mode": result.decision.mode,
                "legacy_recovery_reason": (
                    result.recovery_diagnostic.reason
                    if result.recovery_diagnostic else None
                ),
                "live_admission_authorized": False,
            })
            if result.terminal:
                break
    collapses = [
        x for x in rows if x.get("legacy_recovery_reason") in
        ("zero-sampled-match", "pending-backlog")
    ]
    return {
        "game_number": game_index + 1,
        "session_seed_sha256": hashlib.sha256(session_seed.encode()).hexdigest(),
        "turns_attempted": len(rows),
        "actual_collapse_rows": len(collapses),
        "current_belief_success_rows": sum(
            x["verified_current_states"] > 0
            and x["within_8_seconds"] is True
            and x["true_world_survived"] is True
            for x in collapses
        ),
        "collapse_rows": collapses,
        "all_turns": rows,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--historical-report", type=Path)
    parser.add_argument("--run-games", default="")
    parser.add_argument("--max-decisions", type=int, default=18)
    parser.add_argument("--output", type=Path, default=Path("runs/rebase-challenge/latest.json"))
    parser.add_argument("--require-recovery", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    targets = load_targets()
    payload: dict[str, Any] = {
        "schema": CHALLENGE_SCHEMA,
        "reference": targets["source"],
        "baseline": targets["baseline"],
        "budget_seconds": BUDGET_SECONDS,
        "live_changes": False,
        "authority": "diagnostic-only-no-admission-or-exclusion",
    }
    if args.historical_report is not None:
        raw = args.historical_report.read_bytes()
        if hashlib.sha256(raw).hexdigest() != targets["source"]["report_sha256"]:
            raise ValueError("historical report differs from pinned uploaded evidence")
        payload["historical"] = evaluate_historical_report(
            json.loads(raw), targets,
        )
    else:
        payload["historical"] = {
            "verdict": "NOT_EVALUATED_REPORT_NOT_PROVIDED",
            "cases": [c["game_number"] for c in targets["cases"]],
        }
    numbers = [
        int(x.strip()) for x in args.run_games.split(",") if x.strip()
    ]
    if any(n < 1 or n > 8 for n in numbers) or len(set(numbers)) != len(numbers):
        raise ValueError("--run-games accepts distinct league game numbers 1 through 8")
    if not 1 <= args.max_decisions <= 64:
        raise ValueError("--max-decisions must be 1 through 64")
    payload["fresh_trials"] = [
        run_case(i - 1, max_decisions=args.max_decisions)
        for i in numbers
    ]
    challenged = [x for game in payload["fresh_trials"]
                  for x in game["collapse_rows"]]
    payload["summary"] = {
        "fresh_collapse_rows": len(challenged),
        "valid_current_state_rows": sum(x["verified_current_states"] > 0 for x in challenged),
        "true_world_survival_rows": sum(x["true_world_survived"] is True for x in challenged),
        "within_budget_true_world_rows": sum(
            x["true_world_survived"] is True
            and x["within_8_seconds"] is True
            for x in challenged
        ),
        "complete_recovery_demonstrated": bool(challenged) and all(
            x["verified_current_states"] > 0
            and x["true_world_survived"] is True
            and x["within_8_seconds"] is True
            for x in challenged
        ),
        "posterior_information_retention_measured": False,
    }
    if not numbers:
        payload["verdict"] = "HISTORICAL_ONLY_NOT_A_REBASE_TRIAL"
    elif not challenged:
        payload["verdict"] = "NO_COLLAPSE_REPRODUCED_CANNOT_CLAIM_RECOVERY"
    elif payload["summary"]["complete_recovery_demonstrated"]:
        payload["verdict"] = "COVERED_COLLAPSE_CHECKPOINTS_SURVIVED_WITHIN_BUDGET"
    else:
        payload["verdict"] = "COLLAPSE_RECOVERY_NOT_DEMONSTRATED"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(f"Report: {args.output}")
    print(f"Verdict: {payload['verdict']}")
    print("Legacy baseline: 15 fallback decisions; 19 degraded turns")
    print(f"Fresh collapse rows: {len(challenged)}")
    print("Covered, survived, within 8 seconds: "
          f"{payload['summary']['within_budget_true_world_rows']}")
    print("Posterior information retention: not yet measurable")
    if args.require_recovery and not payload["summary"]["complete_recovery_demonstrated"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
