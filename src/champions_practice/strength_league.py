"""Deterministic offline strength league for the production belief bot.

The v1 league deliberately measures one narrow fixture: the current roster mirror
against the public-only fallback policy. It is a gameplay regression instrument,
not a claim of ladder strength. Reports bind code, Showdown, teams, budgets, and
seeds so later commits can be compared on the same fixture.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import fmean, median
from typing import Any, Callable

from champions_practice.belief_controller import (
    SealedBattleFacade,
    choose_public_fallback,
)
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.demo_fixture import (
    DEMO_AI_PREVIEW_CHOICE,
    DEMO_AI_TEAM,
    DEMO_HUMAN_TEAM,
    demo_public_priors,
)


RUN_SCHEMA = "offline-strength-league-v1"
FIXTURE_ID = "current-roster-mirror-v1"
BOT_ID = "belief-strategy-main-v1"
BASELINE_ID = "public-fallback-v1"
DEFAULT_BATTLES = 8
DEFAULT_MAX_DECISIONS = 64


class StrengthLeagueError(RuntimeError):
    """A benchmark run could not produce an interpretable result."""


@dataclass(frozen=True)
class LeagueConfig:
    battles: int = DEFAULT_BATTLES
    max_decisions: int = DEFAULT_MAX_DECISIONS
    world_limit: int = 8
    particles_per_world: int = 1
    max_particles: int = 8
    candidate_limit: int = 4
    response_limit: int = 4
    strategic_plan_limit: int = 2
    strategic_candidate_limit: int = 3
    strategic_response_limit: int = 2
    decision_budget_seconds: float = 8.0
    conditioning_budget_seconds: float = 8.0
    worker_startup_timeout_seconds: float = 30.0
    seed: int = 15601

    def __post_init__(self) -> None:
        positive_ints = {
            "battles": self.battles,
            "max_decisions": self.max_decisions,
            "world_limit": self.world_limit,
            "particles_per_world": self.particles_per_world,
            "max_particles": self.max_particles,
            "candidate_limit": self.candidate_limit,
            "response_limit": self.response_limit,
            "strategic_plan_limit": self.strategic_plan_limit,
            "strategic_candidate_limit": self.strategic_candidate_limit,
            "strategic_response_limit": self.strategic_response_limit,
        }
        for label, value in positive_ints.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{label} must be a positive integer")
        if self.max_particles < self.world_limit:
            raise ValueError("max_particles must be at least world_limit")
        for label, value in (
            ("decision_budget_seconds", self.decision_budget_seconds),
            ("conditioning_budget_seconds", self.conditioning_budget_seconds),
            (
                "worker_startup_timeout_seconds",
                self.worker_startup_timeout_seconds,
            ),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{label} must be positive and finite")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")


@dataclass(frozen=True)
class GameResult:
    game_index: int
    session_seed: str
    particle_seed: int
    winner: str | None
    outcome: str
    turns: int
    decisions: int
    search_decisions: int
    forced_wait_decisions: int
    fallback_decisions: int
    fallback_reasons: tuple[tuple[str, int], ...]
    degraded_turns: int
    strategy_decisions: int
    branch_count: int
    decision_seconds: tuple[float, ...]
    conditioning_seconds: tuple[float, ...]
    recovery_events: tuple[dict[str, Any], ...] = ()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_hex(*parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sodium_seed(seed: int, game_index: int) -> str:
    return "sodium," + _hash_hex("strength-league", seed, game_index)


def _particle_seed(seed: int, game_index: int) -> int:
    return int(_hash_hex("particle", seed, game_index)[:8], 16)


def _git_commit(project_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise StrengthLeagueError("could not resolve repository commit") from error
    value = result.stdout.strip()
    if len(value) != 40:
        raise StrengthLeagueError("repository commit is not a full SHA")
    return value


def _showdown_revision(project_root: Path) -> str:
    path = project_root / "showdown-version.txt"
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise StrengthLeagueError("could not read showdown-version.txt") from error
    if len(value) != 40:
        raise StrengthLeagueError("showdown-version.txt does not contain a full SHA")
    return value


def _run_identity_payload(
    config: LeagueConfig,
    *,
    git_commit: str,
    showdown_revision: str,
) -> dict[str, Any]:
    return {
        "schema": RUN_SCHEMA,
        "fixture_id": FIXTURE_ID,
        "bot_id": BOT_ID,
        "baseline_id": BASELINE_ID,
        "format_id": CHAMPIONS_FORMAT,
        "git_commit": git_commit,
        "showdown_revision": showdown_revision,
        "bot_team_sha256": _sha256_text(DEMO_AI_TEAM),
        "opponent_team_sha256": _sha256_text(DEMO_HUMAN_TEAM),
        "config": asdict(config),
    }


def _run_id(
    config: LeagueConfig,
    *,
    git_commit: str,
    showdown_revision: str,
) -> str:
    payload = json.dumps(
        _run_identity_payload(
            config,
            git_commit=git_commit,
            showdown_revision=showdown_revision,
        ),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def _wilson_interval(successes: int, total: int) -> tuple[float, float] | None:
    if total <= 0:
        return None
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / total
            + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def summarize_games(games: tuple[GameResult, ...]) -> dict[str, Any]:
    if not games:
        raise ValueError("at least one completed game is required")
    wins = sum(game.outcome == "bot-win" for game in games)
    losses = sum(game.outcome == "bot-loss" for game in games)
    draws = sum(game.outcome == "draw" for game in games)
    decisive = wins + losses
    interval = _wilson_interval(wins, decisive)

    decision_seconds = [
        value for game in games for value in game.decision_seconds
    ]
    conditioning_seconds = [
        value for game in games for value in game.conditioning_seconds
    ]
    fallback_reasons: Counter[str] = Counter()
    recovery_reasons: Counter[str] = Counter()
    structural_mismatch_paths: Counter[str] = Counter()
    structural_mismatch_worlds: Counter[str] = Counter()
    recovery_events = [
        event
        for game in games
        for event in game.recovery_events
    ]
    for game in games:
        fallback_reasons.update(dict(game.fallback_reasons))
    for event in recovery_events:
        reason = event.get("reason")
        if isinstance(reason, str):
            recovery_reasons[reason] += 1
        for path, count in event.get("structural_mismatch_paths", ()):
            structural_mismatch_paths[str(path)] += int(count)
        for world_id, count in event.get("structural_mismatch_worlds", ()):
            structural_mismatch_worlds[str(world_id)] += int(count)

    total_decisions = sum(game.decisions for game in games)
    search_decisions = sum(game.search_decisions for game in games)
    strategy_decisions = sum(game.strategy_decisions for game in games)
    fallback_decisions = sum(game.fallback_decisions for game in games)
    degraded_turns = sum(game.degraded_turns for game in games)

    return {
        "games": len(games),
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "score_rate": (wins + 0.5 * draws) / len(games),
        "decisive_win_rate": (wins / decisive) if decisive else None,
        "decisive_win_rate_95ci": list(interval) if interval is not None else None,
        "turns": {
            "mean": fmean(game.turns for game in games),
            "median": median(game.turns for game in games),
            "max": max(game.turns for game in games),
        },
        "decisions": {
            "total": total_decisions,
            "search": search_decisions,
            "forced_wait": sum(game.forced_wait_decisions for game in games),
            "strategy_plan_attached": strategy_decisions,
            "fallback": fallback_decisions,
            "fallback_rate": (
                fallback_decisions / total_decisions if total_decisions else 0.0
            ),
            "fallback_reasons": dict(sorted(fallback_reasons.items())),
            "degraded_turns": degraded_turns,
            "degraded_rate": (
                degraded_turns / total_decisions if total_decisions else 0.0
            ),
            "branches": sum(game.branch_count for game in games),
        },
        "recovery": {
            "events": len(recovery_events),
            "reasons": dict(sorted(recovery_reasons.items())),
            "sampled_matches": sum(
                int(event.get("sampled_matches", 0))
                for event in recovery_events
            ),
            "sampled_unresolved_worlds": sum(
                int(event.get("sampled_unresolved_worlds", 0))
                for event in recovery_events
            ),
            "exhaustively_excluded_worlds": sum(
                int(event.get("exhaustively_excluded_worlds", 0))
                for event in recovery_events
            ),
            "unsupported_events": sum(
                bool(event.get("unsupported_public_evidence"))
                for event in recovery_events
            ),
            "conditioning_errors": sum(
                event.get("reason") == "conditioning-error"
                for event in recovery_events
            ),
            "top_structural_mismatch_paths": [
                [path, count]
                for path, count in structural_mismatch_paths.most_common(16)
            ],
            "top_structural_mismatch_worlds": [
                [world_id, count]
                for world_id, count in structural_mismatch_worlds.most_common(16)
            ],
        },
        "decision_seconds": {
            "mean": fmean(decision_seconds) if decision_seconds else None,
            "p50": median(decision_seconds) if decision_seconds else None,
            "p95": _percentile(decision_seconds, 0.95),
            "max": max(decision_seconds) if decision_seconds else None,
        },
        "conditioning_seconds": {
            "mean": fmean(conditioning_seconds) if conditioning_seconds else None,
            "p50": median(conditioning_seconds) if conditioning_seconds else None,
            "p95": _percentile(conditioning_seconds, 0.95),
            "max": max(conditioning_seconds) if conditioning_seconds else None,
        },
    }


def _baseline_choice(choices: tuple[str, ...]) -> str:
    return choose_public_fallback(list(choices))


def _preview_signature(choice: str) -> str | None:
    stripped = choice.strip().lower()
    if not stripped.startswith("team"):
        return None
    digits = "".join(character for character in stripped[4:] if character.isdigit())
    return digits or None


def _resolve_preview_choice(
    choices: tuple[str, ...],
    desired: str,
) -> str:
    if desired in choices:
        return desired
    target = _preview_signature(desired)
    matches = [
        choice
        for choice in choices
        if _preview_signature(choice) == target
    ]
    if len(matches) == 1:
        return matches[0]
    raise StrengthLeagueError(
        "benchmark fixture preview is not legal for the baseline side; "
        f"wanted {desired!r}, legal choices include {choices[:8]!r}"
    )


def run_game(
    config: LeagueConfig,
    *,
    game_index: int,
    project_root: Path,
    baseline_selector: Callable[[tuple[str, ...]], str] = _baseline_choice,
) -> GameResult:
    session_seed = _sodium_seed(config.seed, game_index)
    particle_seed = _particle_seed(config.seed, game_index)
    p1_name = "League Baseline"
    p2_name = "League Bot"

    decision_seconds: list[float] = []
    conditioning_seconds: list[float] = []
    recovery_events: list[dict[str, Any]] = []
    fallback_reasons: Counter[str] = Counter()
    search_decisions = 0
    forced_wait_decisions = 0
    fallback_decisions = 0
    degraded_turns = 0
    strategy_decisions = 0
    branch_count = 0

    with SealedBattleFacade(
        project_root=project_root,
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
            p1_name=p1_name,
            p2_name=p2_name,
            session_seed=session_seed,
        )
        preview_choices = battle.legal_human_choices()
        baseline_preview = _resolve_preview_choice(
            preview_choices,
            DEMO_AI_PREVIEW_CHOICE,
        )
        battle.commit_preview(human_choice=baseline_preview)

        result = None
        for _ in range(config.max_decisions):
            choices = battle.legal_human_choices()
            if not choices:
                raise StrengthLeagueError(
                    f"game {game_index} exposed no legal baseline choices"
                )
            human_choice = baseline_selector(choices)
            if human_choice not in choices:
                raise StrengthLeagueError(
                    f"baseline selected illegal choice in game {game_index}: "
                    f"{human_choice!r}"
                )
            ready = battle.lock_ai_action()
            result = battle.commit_human_action(
                token=ready.token,
                human_choice=human_choice,
            )
            decision = result.decision
            decision_seconds.append(float(decision.elapsed_seconds))
            conditioning_seconds.append(float(result.conditioning_seconds))
            if result.recovery_diagnostic is not None:
                recovery_events.append(asdict(result.recovery_diagnostic))
            branch_count += int(decision.branch_count)
            if decision.mode == "belief-search":
                search_decisions += 1
            elif decision.mode == "forced-wait":
                forced_wait_decisions += 1
            elif decision.mode == "fallback":
                fallback_decisions += 1
                fallback_reasons[decision.fallback_reason or "unspecified"] += 1
            if decision.strategic_plan is not None:
                strategy_decisions += 1
            if result.degraded:
                degraded_turns += 1
            if result.terminal:
                break

        if result is None or not result.terminal:
            raise StrengthLeagueError(
                f"game {game_index} did not finish within "
                f"{config.max_decisions} decisions"
            )

        if result.winner == p2_name:
            outcome = "bot-win"
        elif result.winner == p1_name:
            outcome = "bot-loss"
        else:
            outcome = "draw"

        return GameResult(
            game_index=game_index,
            session_seed=session_seed,
            particle_seed=particle_seed,
            winner=result.winner,
            outcome=outcome,
            turns=int(result.public_view.get("turn", 0)),
            decisions=len(decision_seconds),
            search_decisions=search_decisions,
            forced_wait_decisions=forced_wait_decisions,
            fallback_decisions=fallback_decisions,
            fallback_reasons=tuple(sorted(fallback_reasons.items())),
            degraded_turns=degraded_turns,
            strategy_decisions=strategy_decisions,
            branch_count=branch_count,
            decision_seconds=tuple(decision_seconds),
            conditioning_seconds=tuple(conditioning_seconds),
            recovery_events=tuple(recovery_events),
        )


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def run_league(
    config: LeagueConfig,
    *,
    project_root: str | Path | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    root = (
        Path(project_root).expanduser().resolve()
        if project_root is not None
        else Path(__file__).resolve().parents[2]
    )
    git_commit = _git_commit(root)
    showdown_revision = _showdown_revision(root)
    run_id = _run_id(
        config,
        git_commit=git_commit,
        showdown_revision=showdown_revision,
    )
    base = root / "runs" / "strength-league"
    run_dir = base / run_id
    report_path = run_dir / "report.json"
    latest_path = base / "latest-report.json"

    if report_path.is_file() and not refresh:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        _atomic_write_json(latest_path, report)
        return report

    games: list[GameResult] = []
    for index in range(config.battles):
        game = run_game(config, game_index=index, project_root=root)
        games.append(game)
        print(
            f"Game {index + 1}/{config.battles}: {game.outcome} | "
            f"turns {game.turns} | decisions {game.decisions} | "
            f"fallbacks {game.fallback_decisions}"
        )

    game_values = tuple(games)
    report = {
        **_run_identity_payload(
            config,
            git_commit=git_commit,
            showdown_revision=showdown_revision,
        ),
        "run_id": run_id,
        "summary": summarize_games(game_values),
        "games": [asdict(game) for game in game_values],
        "limitations": [
            "v1 uses only the current-roster mirror fixture",
            "the production belief bot is currently benchmarked only as p2",
            "the baseline is public-fallback-v1, not a calibrated ladder opponent",
            "this report measures gameplay on this fixture, not general ladder strength",
        ],
    }
    _atomic_write_json(report_path, report)
    _atomic_write_json(latest_path, report)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--battles", type=int, default=DEFAULT_BATTLES)
    parser.add_argument("--max-decisions", type=int, default=DEFAULT_MAX_DECISIONS)
    parser.add_argument("--world-limit", type=int, default=8)
    parser.add_argument("--particles-per-world", type=int, default=1)
    parser.add_argument("--max-particles", type=int, default=8)
    parser.add_argument("--candidate-limit", type=int, default=4)
    parser.add_argument("--response-limit", type=int, default=4)
    parser.add_argument("--strategic-plan-limit", type=int, default=2)
    parser.add_argument("--strategic-candidate-limit", type=int, default=3)
    parser.add_argument("--strategic-response-limit", type=int, default=2)
    parser.add_argument("--decision-budget-seconds", type=float, default=8.0)
    parser.add_argument("--conditioning-budget-seconds", type=float, default=8.0)
    parser.add_argument("--worker-startup-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--seed", type=int, default=15601)
    parser.add_argument("--refresh", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        report = run_league(
            LeagueConfig(
                battles=args.battles,
                max_decisions=args.max_decisions,
                world_limit=args.world_limit,
                particles_per_world=args.particles_per_world,
                max_particles=args.max_particles,
                candidate_limit=args.candidate_limit,
                response_limit=args.response_limit,
                strategic_plan_limit=args.strategic_plan_limit,
                strategic_candidate_limit=args.strategic_candidate_limit,
                strategic_response_limit=args.strategic_response_limit,
                decision_budget_seconds=args.decision_budget_seconds,
                conditioning_budget_seconds=args.conditioning_budget_seconds,
                worker_startup_timeout_seconds=args.worker_startup_timeout_seconds,
                seed=args.seed,
            ),
            refresh=args.refresh,
        )
    except (StrengthLeagueError, RuntimeError, ValueError, OSError) as error:
        raise SystemExit(f"ERROR: {error}") from error

    summary = report["summary"]
    print()
    print(f"Run:       {report['run_id']}")
    print(f"Fixture:   {report['fixture_id']}")
    print(f"Record:    {summary['wins']}-{summary['losses']}-{summary['draws']}")
    print(f"Score:     {summary['score_rate']:.1%}")
    if summary["decisive_win_rate"] is not None:
        low, high = summary["decisive_win_rate_95ci"]
        print(
            "Decisive:  "
            f"{summary['decisive_win_rate']:.1%} "
            f"(95% Wilson {low:.1%}-{high:.1%})"
        )
    print(
        "Fallbacks: "
        f"{summary['decisions']['fallback']} / "
        f"{summary['decisions']['total']} "
        f"({summary['decisions']['fallback_rate']:.1%})"
    )
    print(
        "Decision:  "
        f"p50 {summary['decision_seconds']['p50']:.3f}s | "
        f"p95 {summary['decision_seconds']['p95']:.3f}s"
    )
    print(
        "Report:    "
        f"{Path(__file__).resolve().parents[2] / 'runs' / 'strength-league' / report['run_id'] / 'report.json'}"
    )


if __name__ == "__main__":
    main()
