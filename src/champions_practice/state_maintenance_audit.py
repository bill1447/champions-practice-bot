"""Offline comparison of disposable worlds and bounded native history witnesses.

The shadow sees only sanitized checkpoints and the bot's committed action. It
never receives the opponent command, live state, live RNG, or an oracle particle.
It has no live admission authority and stops at its first unresolved transition;
retained older particles must never be counted as current search coverage.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path
from time import perf_counter

from champions_practice.belief_controller import BeliefDecisionEngine, SealedBattleFacade
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.demo_fixture import (
    DEMO_AI_PREVIEW_CHOICE,
    DEMO_AI_TEAM,
    demo_public_priors,
)
from champions_practice.diversity_league import ROSTERS, catalog, policy_selector, team_text
from champions_practice.observation_beliefs import (
    public_observation_signature,
    public_opponent_actions_fully_observed,
    resample_particles_by_world,
)
from champions_practice.persistent_admission_smoke import fixture
from champions_practice.search_worker import HypotheticalSearchWorker
from champions_practice.strength_league import (
    _atomic_write_json,
    _git_commit,
    _particle_seed,
    _showdown_revision,
    _sodium_seed,
    _source_identity,
)


def transition_failure(update, timed_out: bool) -> str | None:
    """Distinguish lack of witnesses from proven impossibility."""
    if timed_out:
        return "conditioning-timeout"
    if update is None:
        return "conditioning-no-result"
    if update.particles:
        return None
    if update.unsupported_public_evidence:
        return "unsupported-public-evidence"
    if update.matched_world_ids:
        return "partial-world-witness"
    if update.exhaustively_excluded_world_ids and not update.sampled_unresolved_world_ids:
        return "all-catalog-worlds-disproved"
    return "no-complete-witness"


def queued_alternatives(particles):
    """Count discrete queued commands in hypotheses, never the live queue."""
    alternatives = {}
    for particle in particles:
        commands = [
            {key: action.get(key) for key in ("choice", "pokemon", "moveid", "targetLoc", "target")}
            for action in particle.state.get("queue", ())
            if action.get("choice") in {"move", "switch", "instaswitch"}
        ]
        key = json.dumps(commands, sort_keys=True)
        alternatives.setdefault(particle.world_id, {})[key] = commands
    return {world: list(commands.values()) for world, commands in alternatives.items()}


def fixtures():
    bounded_team, bounded_priors = fixture()
    # An undisclosed opponent item remains ambiguous at the opening. This is a
    # declared bounded catalog, not evidence that other sets are impossible.
    dragonite = bounded_priors["Dragonite"][0]
    bounded_priors["Dragonite"] += (replace(dragonite, item="Dragon Fang"),)
    return {
        "bounded": (bounded_team, bounded_priors, "team 1234"),
        "balance": (team_text(ROSTERS["balance"]), catalog(), "team 1234"),
        "mirror": (DEMO_AI_TEAM, demo_public_priors(), DEMO_AI_PREVIEW_CHOICE),
    }


def run_cell(*, name, policy, seed, max_decisions, budget):
    team, priors, preview = fixtures()[name]
    selector = policy_selector(policy, seed)
    shadow = BeliefDecisionEngine(
        ".",
        battle_format=CHAMPIONS_FORMAT,
        ai_team=team,
        opponent_priors=priors,
        world_limit=4,
        max_particles=4,
        conditioning_budget_seconds=budget,
        particle_seed=_particle_seed(seed, 1),
    )
    trace = []
    blocked = None
    unpruned_witnesses = ()
    with SealedBattleFacade(
        battle_format=CHAMPIONS_FORMAT,
        ai_team=team,
        ai_preview_choice=preview,
        opponent_priors=priors,
        world_limit=4,
        max_particles=4,
        candidate_limit=2,
        response_limit=2,
        strategic_plan_limit=1,
        strategic_candidate_limit=1,
        strategic_response_limit=1,
        decision_budget_seconds=budget,
        conditioning_budget_seconds=budget,
        worker_startup_timeout_seconds=60,
        particle_seed=_particle_seed(seed, 0),
    ) as battle:
        battle.start(
            opponent_team=team,
            p1_name="Audit opponent",
            p2_name="Audit bot",
            session_seed=_sodium_seed(seed, 0),
        )
        battle.commit_preview(human_choice=selector(tuple(battle.legal_human_choices())))
        before = battle.diagnostic_ai_public_checkpoint()
        shadow.initialize_preview(view=before, ai_choice=preview)
        opening_worlds = len({p.world_id for p in shadow.particles})
        unpruned_witnesses = shadow.particles
        if not shadow.particles:
            blocked = "opening-no-match"
        with HypotheticalSearchWorker(startup_deadline=perf_counter() + 60) as verifier:
            for index in range(max_decisions):
                choices = battle.legal_human_choices()
                if not choices:
                    break
                own_menu = battle.diagnostic_ai_public_choices()
                aligned = not blocked and bool(shadow.particles)
                if aligned:
                    for particle in shadow.particles:
                        projected = verifier.state_view(
                            state=particle.state,
                            side="p2",
                            previews=shadow.previews,
                        )
                        if public_observation_signature(projected) != public_observation_signature(
                            before
                        ):
                            blocked = "shadow-public-mismatch"
                        elif sorted(
                            verifier.legal_choices(state=particle.state, side="p2")
                        ) != sorted(own_menu):
                            blocked = "shadow-own-menu-mismatch"
                    aligned = blocked is None
                ready = battle.lock_ai_action()
                result = battle.commit_human_action(
                    token=ready.token,
                    human_choice=selector(tuple(choices)),
                )
                after = battle.diagnostic_ai_public_checkpoint()
                row = {
                    "decision_index": index,
                    "turn": before.get("turn"),
                    "phase": before.get("phase"),
                    "production_mode": result.decision.mode,
                    "production_fallback": result.decision.fallback_reason,
                    "production_native_admission": battle.diagnostic_ai_native_admission(),
                    "shadow_current_public_and_menu_match": aligned,
                    "shadow_worlds_before": len({p.world_id for p in shadow.particles}),
                    "shadow_failure": blocked,
                    "shadow_queued_alternatives": queued_alternatives(shadow.particles),
                }
                if not blocked:
                    start = perf_counter()
                    deadline = start + budget
                    try:
                        update, timeout = shadow._run_until_deadline(
                            lambda worker: shadow._condition_adaptive(
                                worker,
                                particles=shadow.particles,
                                ai_choice=result.decision.choice,
                                view=after,
                                previous_view=before,
                                batches=shadow.rng_sample_batches,
                                deadline=deadline,
                            ),
                            deadline=deadline,
                        )
                        blocked = transition_failure(update, timeout)
                    except (RuntimeError, ValueError, TimeoutError) as error:
                        update = None
                        blocked = "conditioning-error:" + type(error).__name__
                    row.update(
                        shadow_conditioning_seconds=perf_counter() - start,
                        shadow_transition_failure=blocked,
                    )
                    if update is not None:
                        row.update(
                            generated=update.generated,
                            matched=update.matched,
                            witnessed_worlds=list(update.matched_world_ids),
                            unresolved_worlds=list(update.sampled_unresolved_world_ids),
                            disproved_worlds=list(update.exhaustively_excluded_world_ids),
                            unsupported_evidence=list(update.unsupported_public_evidence),
                            mismatch_paths=list(update.structural_mismatch_paths),
                            finite_witnesses=update.finite_reachability_witnesses,
                            finite_unresolved=update.finite_reachability_unresolved,
                            finite_leaves=update.finite_reachability_leaves,
                        )
                        if blocked:
                            row["mismatch_examples"] = [
                                asdict(example) for example in update.structural_mismatch_examples
                            ]
                        if not blocked:
                            unpruned_witnesses = update.particles
                            shadow.particles = resample_particles_by_world(
                                update.particles,
                                limit=shadow.max_particles,
                                seed=index + 53,
                            )
                            row["queue_before_pruning"] = queued_alternatives(update.particles)
                            row["queue_after_pruning"] = queued_alternatives(shadow.particles)
                    # On unresolved, retain last-good particles but never use
                    # them again as a current checkpoint. No silent catch-up.
                    if blocked:
                        row.update(
                            first_failure_public_before=before,
                            first_failure_public_after=after,
                            committed_own_choice=result.decision.choice,
                            public_opponent_command_complete=public_opponent_actions_fully_observed(
                                after,
                                previous_public_view=before,
                            ),
                        )
                        # One offline probe of the previous positive batch.
                        # It receives no oracle seed or opponent command. It
                        # never advances the primary shadow or live controller.
                        if len(unpruned_witnesses) > len(shadow.particles):
                            probe_deadline = perf_counter() + budget
                            try:
                                probe, probe_timeout = shadow._run_until_deadline(
                                    lambda worker: shadow._condition_adaptive(
                                        worker,
                                        particles=unpruned_witnesses,
                                        ai_choice=result.decision.choice,
                                        view=after,
                                        previous_view=before,
                                        batches=shadow.rng_sample_batches,
                                        deadline=probe_deadline,
                                    ),
                                    deadline=probe_deadline,
                                )
                                row["unpruned_probe"] = {
                                    "particles": len(unpruned_witnesses),
                                    "failure": transition_failure(probe, probe_timeout),
                                    "matched_worlds": list(probe.matched_world_ids)
                                    if probe
                                    else [],
                                    "queued_alternatives": queued_alternatives(unpruned_witnesses),
                                }
                            except (RuntimeError, ValueError, TimeoutError) as error:
                                row["unpruned_probe"] = {"error": type(error).__name__}
                trace.append(row)
                print(
                    f"{name}/{policy} decision={index + 1} production={result.decision.mode} "
                    f"shadow_current={aligned} transition={blocked or 'witnessed'}",
                    flush=True,
                )
                before = after
                if result.terminal:
                    break
    actionable = [row for row in trace if row["production_mode"] != "forced-wait"]
    return {
        "fixture": name,
        "policy": policy,
        "seed": seed,
        "opening_shadow_worlds": opening_worlds,
        "decisions": len(trace),
        "actionable_decisions": len(actionable),
        "production_modes": dict(Counter(row["production_mode"] for row in trace)),
        "production_fallbacks": dict(
            Counter(row["production_fallback"] for row in trace if row["production_fallback"])
        ),
        "shadow_current_actionable_checkpoints": sum(
            row["shadow_current_public_and_menu_match"] for row in actionable
        ),
        "shadow_first_failure": blocked,
        "trace": trace,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-decisions", type=int, default=8)
    parser.add_argument("--budget", type=float, default=8)
    parser.add_argument(
        "--output", type=Path, default=Path("runs/state-maintenance-audit/report.json")
    )
    args = parser.parse_args()
    if args.max_decisions <= 0 or not 0 < args.budget <= 60:
        parser.error("positive decisions and a budget of at most 60 seconds required")
    root = Path.cwd()
    report = {
        "schema": "offline-state-maintenance-audit-v1",
        "parent_commit": _git_commit(root),
        "runtime_source": _source_identity(root),
        "showdown_revision": _showdown_revision(root),
        "budget_seconds": args.budget,
        "max_decisions": args.max_decisions,
        "scope": "passive public-only shadow, same production trajectory; no live authority or strength comparison",
        "cells": [],
    }
    for name, policy, seed in (
        ("bounded", "attack-first", 24101),
        ("bounded", "seeded-mixed", 24102),
        ("balance", "support-switch", 24103),
        ("mirror", "attack-first", 7),
    ):
        report["cells"].append(
            run_cell(
                name=name,
                policy=policy,
                seed=seed,
                max_decisions=args.max_decisions,
                budget=args.budget,
            )
        )
        _atomic_write_json(args.output, report)
    print(args.output, flush=True)


if __name__ == "__main__":
    main()
