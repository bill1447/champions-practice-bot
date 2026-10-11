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
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import fmean, median
from time import sleep
from typing import Any, Callable

from champions_practice.belief_controller import (
    SealedBattleFacade,
)
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.demo_fixture import (
    DEMO_AI_PREVIEW_CHOICE,
    DEMO_AI_TEAM,
    DEMO_HUMAN_TEAM,
    demo_public_priors,
)
from champions_practice.uncertain_fixture import (
    FIXTURE_ID as UNCERTAIN_FIXTURE_ID,
    SOURCE_LABEL as UNCERTAIN_SOURCE_LABEL,
    opponent_selection as uncertain_opponent_selection,
    opponent_team as uncertain_opponent_team,
    public_priors as uncertain_public_priors,
)


RUN_SCHEMA = "offline-strength-league-v1"
FIXTURE_ID = "current-roster-mirror-v1"
BOT_ID = "belief-strategy-main-v1"
BASELINE_ID = "attacking-mega-legal-v1"
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
    fixture: str = FIXTURE_ID

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
        if self.fixture not in {FIXTURE_ID, UNCERTAIN_FIXTURE_ID}:
            raise ValueError(f"unsupported strength league fixture: {self.fixture}")


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
    finite_reachability_witnesses: int = 0
    finite_reachability_disproofs: int = 0
    finite_reachability_unresolved: int = 0
    finite_reachability_leaves: int = 0
    recovery_events: tuple[dict[str, Any], ...] = ()
    recovery_retry_events: tuple[dict[str, Any], ...] = ()
    own_speed_diagnostics: tuple[dict[str, Any], ...] = ()
    own_speed_transport_issues: tuple[dict[str, str], ...] = ()
    decision_trace: tuple[dict[str, Any], ...] = ()


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


def _source_identity(project_root: Path) -> dict[str, Any]:
    """Bind runtime sources, including unstaged and new modules, to a run.

    Generated reports and review documents are excluded so writing a report
    does not change its own identity. Git metadata alone cannot identify the
    implementation executed from an uncommitted working tree.
    """
    paths = ["src", "tools", "pyproject.toml", "showdown-version.txt"]
    try:
        inventory = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--",
             *paths],
            cwd=project_root, check=True, capture_output=True, timeout=5,
        ).stdout
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all", "-z", "--", *paths],
            cwd=project_root, check=True, capture_output=True, timeout=5,
        ).stdout
        digest = hashlib.sha256()
        names = sorted(set(name for name in inventory.split(b"\0") if name))
        if not names:
            raise StrengthLeagueError("runtime source inventory is empty")
        for name in names:
            file = (project_root / os.fsdecode(name)).resolve()
            if not file.is_relative_to(project_root.resolve()):
                raise StrengthLeagueError("runtime source escapes repository")
            payload = file.read_bytes() if file.is_file() else None
            digest.update(len(name).to_bytes(8, "big"))
            digest.update(name)
            digest.update(b"missing" if payload is None else b"file")
            if payload is not None:
                digest.update(len(payload).to_bytes(8, "big"))
                digest.update(payload)
    except (OSError, subprocess.SubprocessError) as error:
        raise StrengthLeagueError("could not fingerprint runtime sources") from error
    return {"schema": "runtime-source-sha256-v1", "sha256": digest.hexdigest(),
            "dirty": bool(status)}


def _run_identity_payload(
    config: LeagueConfig,
    *,
    git_commit: str,
    showdown_revision: str,
    source_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Preserve the original fixture's run identity and comparison history.
    config_data = asdict(config)
    if config.fixture == FIXTURE_ID:
        config_data.pop("fixture")
    if config.fixture == UNCERTAIN_FIXTURE_ID:
        pool = uncertain_public_priors()
        catalog = "\n".join(
            candidate.team_text
            for candidates in pool.values()
            for candidate in candidates
        )
        opponent_team_hash = _sha256_text(catalog)
    else:
        opponent_team_hash = _sha256_text(DEMO_HUMAN_TEAM)
    return {
        "schema": RUN_SCHEMA,
        "fixture_id": config.fixture,
        "bot_id": BOT_ID,
        "baseline_id": BASELINE_ID,
        "format_id": CHAMPIONS_FORMAT,
        "git_commit": git_commit,
        "showdown_revision": showdown_revision,
        "bot_team_sha256": _sha256_text(DEMO_AI_TEAM),
        "opponent_team_sha256": opponent_team_hash,
        "config": config_data,
        **({"source_identity": source_identity} if source_identity is not None else {}),
    }


def _run_id(
    config: LeagueConfig,
    *,
    git_commit: str,
    showdown_revision: str,
    source_identity: dict[str, Any] | None = None,
) -> str:
    payload = json.dumps(
        _run_identity_payload(
            config,
            git_commit=git_commit,
            showdown_revision=showdown_revision,
            source_identity=source_identity,
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
    recovery_retries = [
        retry
        for game in games
        for retry in game.recovery_retry_events
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
            # Own-side-only native speed evidence, bounded per game and league.
            "own_speed_diagnostics": [
                {"game_index": game.game_index, **detail}
                for game in games for detail in game.own_speed_diagnostics
            ][:32],
            "own_speed_transport_issues": [
                {"game_index": game.game_index, **detail}
                for game in games for detail in game.own_speed_transport_issues
            ][:32],
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
            "retry_events": len(recovery_retries),
            "retry_worker_attempts": sum(
                int(retry.get("worker_attempts", 0))
                for retry in recovery_retries
            ),
            "retry_returned_updates": sum(
                int(retry.get("returned_updates", 0))
                for retry in recovery_retries
            ),
            "retry_deadline_timeouts": sum(
                int(retry.get("deadline_timeouts", 0))
                for retry in recovery_retries
            ),
            "retry_finite_progress_callbacks": sum(
                int(retry.get("finite_progress_callbacks", 0))
                for retry in recovery_retries
            ),
            "retry_finite_progress_changes": sum(
                int(retry.get("finite_progress_changes", 0))
                for retry in recovery_retries
            ),
            "retry_seed_cursor_advanced": sum(
                bool(retry.get("seed_cursor_advanced"))
                for retry in recovery_retries
            ),
            "retry_continuation_changed": sum(
                bool(retry.get("continuation_changed"))
                for retry in recovery_retries
            ),
            "retry_continuation_persisted": sum(
                bool(retry.get("continuation_persisted"))
                for retry in recovery_retries
            ),
            "finite_reachability_witnesses": sum(
                game.finite_reachability_witnesses for game in games
            ),
            "finite_reachability_disproofs": sum(
                game.finite_reachability_disproofs for game in games
            ),
            "finite_reachability_unresolved": sum(
                game.finite_reachability_unresolved for game in games
            ),
            "finite_reachability_leaves": sum(
                game.finite_reachability_leaves for game in games
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
    """Attack-first legal-command baseline; independent of the bot fallback.

    This is not the poke-env HeuristicOpponent: it has only legal command
    strings, not the richer battle objects needed by that evaluator.
    Deterministic selection ensures reproducibility without Protect spam.
    """
    if not choices:
        raise StrengthLeagueError("baseline has no legal choices")
    if all(choice.startswith("team ") for choice in choices):
        return sorted(choices)[0]

    def score(choice: str) -> tuple[int, int, int, int, str]:
        parts = [part.strip().lower() for part in choice.split(",")]
        moves = [part for part in parts if part.startswith("move ")]
        defensive = ("protect", "detect", "imprison", "trickroom",
                     "followme", "wideguard", "quickguard", "endure")
        # In Showdown command targets, -1/-2 select our own side;
        # +1/+2 select the opposing side. Avoid selecting ally-targeted
        # attacks by lexicographic tie break before rewarding aggression.
        friendly_fire = sum(
            any(token.startswith("-") and token[1:].isdigit()
                for token in move.split()[2:])
            for move in moves
        )
        attacks = sum(not any(token in move for token in defensive)
                      for move in moves)
        avoids_stall = -sum(any(token in move for token in defensive)
                            for move in moves)
        mega = sum("mega" in move for move in moves)
        return -friendly_fire, attacks, mega, avoids_stall, choice

    return max(choices, key=score)


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
    trace_sink: Callable[[tuple[dict[str, Any], ...], str], None] | None = None,
) -> GameResult:
    session_seed = _sodium_seed(config.seed, game_index)
    particle_seed = _particle_seed(config.seed, game_index)
    p1_name = "League Baseline"
    p2_name = "League Bot"
    uncertain = config.fixture == UNCERTAIN_FIXTURE_ID
    opponent_team = (
        uncertain_opponent_team(config.seed, game_index)
        if uncertain else DEMO_HUMAN_TEAM
    )
    opponent_priors = (
        uncertain_public_priors() if uncertain else demo_public_priors()
    )

    decision_seconds: list[float] = []
    conditioning_seconds: list[float] = []
    recovery_events: list[dict[str, Any]] = []
    recovery_retry_events: list[dict[str, Any]] = []
    fallback_reasons: Counter[str] = Counter()
    decision_trace: list[dict[str, Any]] = []
    own_speed_diagnostics: list[dict[str, Any]] = []
    own_speed_transport_issues: list[dict[str, str]] = []
    search_decisions = 0
    forced_wait_decisions = 0
    fallback_decisions = 0
    degraded_turns = 0
    strategy_decisions = 0
    branch_count = 0
    finite_reachability_witnesses = 0
    finite_reachability_disproofs = 0
    finite_reachability_unresolved = 0
    finite_reachability_leaves = 0

    with SealedBattleFacade(
        project_root=project_root,
        battle_format=CHAMPIONS_FORMAT,
        ai_team=DEMO_AI_TEAM,
        ai_preview_choice=DEMO_AI_PREVIEW_CHOICE,
        opponent_priors=opponent_priors,
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
            opponent_team=opponent_team,
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
            # Capture the exact sanitized p2 checkpoint and request-derived
            # choices that tactical search is about to consume. These are
            # diagnostic copies only: no live native state, sealed opponent
            # truth, hypothetical worlds, or oracle legality is exposed.
            bot_public_before = battle.diagnostic_ai_public_checkpoint()
            ai_public_choices_before = battle.diagnostic_ai_public_choices()
            decision_trace.append({
                "decision_index": len(decision_trace),
                "observed_turn_before": bot_public_before.get("turn"),
                "observed_phase_before": bot_public_before.get("phase"),
                "bot_public_before": bot_public_before,
                "ai_public_choices_before": list(ai_public_choices_before),
                "baseline_action": human_choice,
                "baseline_legal_choice_count": len(choices),
                "stage": "locking-ai-action",
                "complete": False,
            })
            if trace_sink is not None:
                trace_sink(tuple(decision_trace), "locking-ai-action")
            ready = battle.lock_ai_action()
            decision_trace[-1]["stage"] = "committing-joint-action"
            if trace_sink is not None:
                trace_sink(tuple(decision_trace), "committing-joint-action")
            result = battle.commit_human_action(
                token=ready.token,
                human_choice=human_choice,
            )
            decision = result.decision
            # Preserve per-decision provenance rather than only aggregate
            # fallback counts. Never persist the sealed native battle state,
            # offline opponent truth sets, or internal hypothetical worlds.
            public_after = result.public_view
            bot_public_after = battle.diagnostic_ai_public_checkpoint()
            decision_trace[-1].update({
                "stage": "complete",
                "complete": True,
                "observed_turn_after": bot_public_after.get("turn"),
                "observed_phase_after": bot_public_after.get("phase"),
                "bot_public_after": bot_public_after,
                # Retain the human-facing post-resolution phase/turn from #231
                # for backward comparison, but do not confuse it with the
                # decision engine's p2 observation above.
                "human_observed_turn_after": public_after.get("turn"),
                "human_observed_phase_after": public_after.get("phase"),
                "mode": decision.mode,
                "fallback_reason": decision.fallback_reason,
                "chosen_action": decision.choice,
                "particle_count": decision.particle_count,
                "candidate_count": decision.candidate_count,
                "branch_count": decision.branch_count,
                "elapsed_seconds": decision.elapsed_seconds,
                "conditioning_seconds": result.conditioning_seconds,
                "post_decision_conditioning_seconds": result.conditioning_seconds,
                "degraded": bool(result.degraded),
                "terminal": bool(result.terminal),
            })
            if trace_sink is not None:
                trace_sink(tuple(decision_trace), "decision-complete")
            decision_seconds.append(float(decision.elapsed_seconds))
            conditioning_seconds.append(float(result.conditioning_seconds))
            finite_reachability_witnesses += int(
                result.finite_reachability_witnesses
            )
            finite_reachability_disproofs += int(
                result.finite_reachability_disproofs
            )
            finite_reachability_unresolved += int(
                result.finite_reachability_unresolved
            )
            finite_reachability_leaves += int(
                result.finite_reachability_leaves
            )
            if result.recovery_diagnostic is not None:
                recovery_events.append(asdict(result.recovery_diagnostic))
            if result.recovery_retry_diagnostic is not None:
                recovery_retry_events.append(
                    {
                        "decision_index": len(decision_seconds) - 1,
                        **asdict(result.recovery_retry_diagnostic),
                    }
                )
            branch_count += int(decision.branch_count)
            if decision.mode == "belief-search":
                search_decisions += 1
            elif decision.mode == "forced-wait":
                forced_wait_decisions += 1
            elif decision.mode == "fallback":
                fallback_decisions += 1
                fallback_reasons[decision.fallback_reason or "unspecified"] += 1
                for detail in decision.own_speed_diagnostics[:2]:
                    if len(own_speed_diagnostics) < 8:
                        own_speed_diagnostics.append({
                            "decision_index": len(decision_seconds) - 1,
                            "fallback_reason": decision.fallback_reason,
                            **detail,
                        })
                for detail in decision.own_speed_transport_issues[:2]:
                    if len(own_speed_transport_issues) < 8:
                        own_speed_transport_issues.append({
                            "decision_index": len(decision_seconds) - 1,
                            **detail,
                        })
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
            decision_trace=tuple(decision_trace),
            own_speed_diagnostics=tuple(own_speed_diagnostics),
            own_speed_transport_issues=tuple(own_speed_transport_issues),
            degraded_turns=degraded_turns,
            strategy_decisions=strategy_decisions,
            branch_count=branch_count,
            decision_seconds=tuple(decision_seconds),
            conditioning_seconds=tuple(conditioning_seconds),
            finite_reachability_witnesses=finite_reachability_witnesses,
            finite_reachability_disproofs=finite_reachability_disproofs,
            finite_reachability_unresolved=finite_reachability_unresolved,
            finite_reachability_leaves=finite_reachability_leaves,
            recovery_events=tuple(recovery_events),
            recovery_retry_events=tuple(recovery_retry_events),
        )


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".part", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        # Windows can briefly hold the destination during another writer's
        # rename or reader open. Keep each source private and retry only those
        # bounded sharing/access failures; never rewrite the destination in place.
        for attempt in range(8):
            try:
                os.replace(temporary, path)
                break
            except PermissionError as error:
                if os.name != "nt" or error.winerror not in {5, 32, 33} or attempt == 7:
                    raise
                sleep(0.01 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


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
    source_identity = _source_identity(root)
    run_id = _run_id(
        config,
        git_commit=git_commit,
        showdown_revision=showdown_revision,
        source_identity=source_identity,
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
    partial_path = run_dir / "partial-report.json"
    latest_partial_path = base / "latest-partial-report.json"
    active_trace: tuple[dict[str, Any], ...] = ()
    active_stage = "starting-game"

    def write_partial(*, failure: dict[str, Any] | None = None) -> None:
        payload = {
            **_run_identity_payload(
                config, git_commit=git_commit,
                showdown_revision=showdown_revision,
                source_identity=source_identity,
            ),
            "run_id": run_id,
            "complete": False,
            "completed_games": [asdict(game) for game in games],
            "active_game": {
                "game_index": len(games),
                "stage": active_stage,
                "decision_trace": active_trace,
            },
            "failure": failure,
        }
        _atomic_write_json(partial_path, payload)
        _atomic_write_json(latest_partial_path, payload)

    def retain_trace(trace: tuple[dict[str, Any], ...], stage: str) -> None:
        nonlocal active_trace, active_stage
        active_trace = trace
        active_stage = stage
        write_partial()

    for index in range(config.battles):
        active_trace = ()
        active_stage = "starting-game"
        write_partial()
        try:
            game = run_game(
                config, game_index=index, project_root=root,
                trace_sink=retain_trace,
            )
        except Exception as error:
            # Never serialize exception text: worker exceptions may contain
            # untrusted or private data. Type and stage are enough to locate
            # the last durable public checkpoint for investigation.
            write_partial(failure={
                "game_index": index,
                "stage": active_stage,
                "error_type": type(error).__name__,
            })
            raise
        games.append(game)
        active_trace = ()
        active_stage = "game-complete"
        write_partial()
        print(
            f"Game {index + 1}/{config.battles}: {game.outcome} | "
            f"turns {game.turns} | decisions {game.decisions} | "
            f"fallbacks {game.fallback_decisions}"
        )

    if _source_identity(root) != source_identity or _git_commit(root) != git_commit:
        write_partial(failure={
            "game_index": config.battles - 1, "stage": "source-provenance",
            "error_type": "StrengthLeagueError",
        })
        raise StrengthLeagueError("runtime source changed during strength league")
    game_values = tuple(games)
    report = {
        **_run_identity_payload(
            config,
            git_commit=git_commit,
            showdown_revision=showdown_revision,
            source_identity=source_identity,
        ),
        "run_id": run_id,
        "summary": summarize_games(game_values),
        "games": [asdict(game) for game in game_values],
        "fixture_provenance": (
            {
                "source": UNCERTAIN_SOURCE_LABEL,
                "set_variants_per_species": {
                    species: len(candidates)
                    for species, candidates in uncertain_public_priors().items()
                },
                "truth_selection_offline_only": [
                    list(uncertain_opponent_selection(config.seed, index))
                    for index in range(config.battles)
                ],
                "notes": (
                    "Synthetic spread/nature uncertainty only; no VGCPastes provenance. "
                    "True selections must never enter bot priors or observations."
                ),
            }
            if config.fixture == UNCERTAIN_FIXTURE_ID else {
                "source": "frozen-current-roster-mirror",
                "notes": "One fixed opponent team; not an uncertainty benchmark.",
            }
        ),
        "limitations": [
            (
                "synthetic spread-only alternatives; not a calibrated external set corpus"
                if config.fixture == UNCERTAIN_FIXTURE_ID
                else "v1 uses only the current-roster mirror fixture"
            ),
            "the production belief bot is currently benchmarked only as p2",
            "the baseline is attacking-mega-legal-v1, not a calibrated ladder opponent",
            "this report measures gameplay on this fixture, not general ladder strength",
        ],
    }
    _atomic_write_json(report_path, report)
    _atomic_write_json(latest_path, report)
    # Leave the partial artifact for forensic continuity; complete results
    # are authoritative only when the full report exists.
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--battles", type=int, default=DEFAULT_BATTLES)
    parser.add_argument("--fixture", choices=(FIXTURE_ID, UNCERTAIN_FIXTURE_ID),
                        default=FIXTURE_ID)
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
                fixture=args.fixture,
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
