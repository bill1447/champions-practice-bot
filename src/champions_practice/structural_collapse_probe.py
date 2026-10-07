"""Reproduce the first structural belief-conditioning collapse deterministically."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from champions_practice.belief_controller import SealedBattleFacade
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.demo_fixture import (
    DEMO_AI_PREVIEW_CHOICE,
    DEMO_AI_TEAM,
    DEMO_HUMAN_TEAM,
    demo_public_priors,
)
from champions_practice.strength_league import (
    FIXTURE_ID,
    LeagueConfig,
    StrengthLeagueError,
    _atomic_write_json,
    _baseline_choice,
    _git_commit,
    _particle_seed,
    _resolve_preview_choice,
    _showdown_revision,
    _sodium_seed,
)


PROBE_SCHEMA = "structural-collapse-probe-v1"


def _probe_id(
    *,
    git_commit: str,
    showdown_revision: str,
    config: LeagueConfig,
    game_index: int,
) -> str:
    payload = json.dumps(
        {
            "schema": PROBE_SCHEMA,
            "fixture_id": FIXTURE_ID,
            "git_commit": git_commit,
            "showdown_revision": showdown_revision,
            "config": asdict(config),
            "game_index": game_index,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


def run_structural_collapse_probe(
    *,
    config: LeagueConfig | None = None,
    game_index: int = 0,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """Run the frozen league fixture until the first structural recovery event."""
    if game_index < 0:
        raise ValueError("game_index must be non-negative")
    config = config or LeagueConfig(battles=1, max_decisions=16)
    root = (
        Path(project_root).expanduser().resolve()
        if project_root is not None
        else Path(__file__).resolve().parents[2]
    )
    git_commit = _git_commit(root)
    showdown_revision = _showdown_revision(root)
    session_seed = _sodium_seed(config.seed, game_index)
    particle_seed = _particle_seed(config.seed, game_index)

    with SealedBattleFacade(
        project_root=root,
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
        particle_seed=particle_seed,
    ) as battle:
        battle.start(
            opponent_team=DEMO_HUMAN_TEAM,
            p1_name="Collapse Baseline",
            p2_name="Collapse Bot",
            session_seed=session_seed,
        )
        preview_choices = battle.legal_human_choices()
        baseline_preview = _resolve_preview_choice(
            preview_choices,
            DEMO_AI_PREVIEW_CHOICE,
        )
        battle.commit_preview(human_choice=baseline_preview)

        for decision_index in range(config.max_decisions):
            choices = battle.legal_human_choices()
            if not choices:
                raise StrengthLeagueError(
                    "structural-collapse probe exposed no legal baseline choices"
                )
            human_choice = _baseline_choice(choices)
            ready = battle.lock_ai_action()
            result = battle.commit_human_action(
                token=ready.token,
                human_choice=human_choice,
            )
            diagnostic = result.recovery_diagnostic
            if (
                diagnostic is not None
                and diagnostic.structural_mismatches > 0
            ):
                probe_id = _probe_id(
                    git_commit=git_commit,
                    showdown_revision=showdown_revision,
                    config=config,
                    game_index=game_index,
                )
                report = {
                    "schema": PROBE_SCHEMA,
                    "probe_id": probe_id,
                    "fixture_id": FIXTURE_ID,
                    "format_id": CHAMPIONS_FORMAT,
                    "git_commit": git_commit,
                    "showdown_revision": showdown_revision,
                    "game_index": game_index,
                    "decision_index": decision_index,
                    "session_seed": session_seed,
                    "particle_seed": particle_seed,
                    "human_choice": human_choice,
                    "ai_choice": result.decision.choice,
                    "decision_mode": result.decision.mode,
                    "public_view": result.public_view,
                    "recovery_diagnostic": asdict(diagnostic),
                    "config": asdict(config),
                }
                base = root / "runs" / "structural-collapse"
                _atomic_write_json(base / probe_id / "report.json", report)
                _atomic_write_json(base / "latest-report.json", report)
                return report
            if result.terminal:
                break

    raise StrengthLeagueError(
        "no structural belief-conditioning collapse was reproduced within "
        f"{config.max_decisions} decisions"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-index", type=int, default=0)
    parser.add_argument("--max-decisions", type=int, default=16)
    parser.add_argument("--decision-budget-seconds", type=float, default=8.0)
    parser.add_argument("--conditioning-budget-seconds", type=float, default=8.0)
    parser.add_argument("--worker-startup-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--seed", type=int, default=15601)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    config = LeagueConfig(
        battles=1,
        max_decisions=args.max_decisions,
        decision_budget_seconds=args.decision_budget_seconds,
        conditioning_budget_seconds=args.conditioning_budget_seconds,
        worker_startup_timeout_seconds=args.worker_startup_timeout_seconds,
        seed=args.seed,
    )
    try:
        report = run_structural_collapse_probe(
            config=config,
            game_index=args.game_index,
        )
    except (StrengthLeagueError, RuntimeError, ValueError, OSError) as error:
        raise SystemExit(f"ERROR: {error}") from error

    diagnostic = report["recovery_diagnostic"]
    print(f"Probe:      {report['probe_id']}")
    print(f"Game:       {report['game_index']}")
    print(f"Decision:   {report['decision_index']}")
    print(f"Reason:     {diagnostic['reason']}")
    print(
        "Structural: "
        f"{diagnostic['structural_mismatches']} / "
        f"{diagnostic['generated_branches']}"
    )
    print("Top mismatch paths:")
    for path, count in diagnostic["structural_mismatch_paths"][:10]:
        print(f"  {count:>6}  {path}")
    print("Examples:")
    for example in diagnostic["structural_mismatch_examples"][:5]:
        print(
            f"  {example['world_id']} {example['path']}: "
            f"actual={example['actual']!r} "
            f"simulated={example['simulated']!r}"
        )
    print(
        "Report:     "
        f"{Path(__file__).resolve().parents[2] / 'runs' / 'structural-collapse' / 'latest-report.json'}"
    )


if __name__ == "__main__":
    main()
