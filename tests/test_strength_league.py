from __future__ import annotations

import pytest

from champions_practice.strength_league import (
    BASELINE_ID,
    BOT_ID,
    FIXTURE_ID,
    RUN_SCHEMA,
    GameResult,
    LeagueConfig,
    StrengthLeagueError,
    _particle_seed,
    _resolve_preview_choice,
    _run_id,
    _sodium_seed,
    summarize_games,
)


def _game(
    index: int,
    *,
    outcome: str,
    fallback_decisions: int = 0,
    degraded_turns: int = 0,
    strategy_decisions: int = 0,
    recovery_events: tuple[dict, ...] = (),
) -> GameResult:
    winner = {
        "bot-win": "League Bot",
        "bot-loss": "League Baseline",
        "draw": None,
    }[outcome]
    return GameResult(
        game_index=index,
        session_seed=_sodium_seed(15601, index),
        particle_seed=_particle_seed(15601, index),
        winner=winner,
        outcome=outcome,
        turns=8 + index,
        decisions=4,
        search_decisions=4 - fallback_decisions,
        forced_wait_decisions=0,
        fallback_decisions=fallback_decisions,
        fallback_reasons=(
            (("belief-search-deadline", fallback_decisions),)
            if fallback_decisions
            else ()
        ),
        degraded_turns=degraded_turns,
        strategy_decisions=strategy_decisions,
        branch_count=100 + index,
        decision_seconds=(1.0, 2.0, 3.0, 4.0),
        conditioning_seconds=(0.1, 0.2, 0.3, 0.4),
        recovery_events=recovery_events,
    )


def test_league_identity_is_deterministic_and_binds_configuration():
    base = LeagueConfig(battles=4)

    first = _run_id(
        base,
        git_commit="a" * 40,
        showdown_revision="b" * 40,
    )
    second = _run_id(
        base,
        git_commit="a" * 40,
        showdown_revision="b" * 40,
    )
    changed = _run_id(
        LeagueConfig(battles=5),
        git_commit="a" * 40,
        showdown_revision="b" * 40,
    )

    assert first == second
    assert first != changed
    assert len(first) == 20


def test_league_identity_changes_with_code_or_showdown_revision():
    config = LeagueConfig(battles=1)

    baseline = _run_id(
        config,
        git_commit="a" * 40,
        showdown_revision="b" * 40,
    )

    assert baseline != _run_id(
        config,
        git_commit="c" * 40,
        showdown_revision="b" * 40,
    )
    assert baseline != _run_id(
        config,
        git_commit="a" * 40,
        showdown_revision="d" * 40,
    )


def test_seed_generation_is_deterministic_and_game_specific():
    assert _sodium_seed(15601, 0) == _sodium_seed(15601, 0)
    assert _sodium_seed(15601, 0) != _sodium_seed(15601, 1)
    assert _sodium_seed(15601, 0).startswith("sodium,")
    assert len(_sodium_seed(15601, 0).split(",", 1)[1]) == 64
    assert _particle_seed(15601, 0) != _particle_seed(15601, 1)


def test_summary_reports_gameplay_latency_and_failure_modes():
    games = (
        _game(
            0,
            outcome="bot-win",
            fallback_decisions=1,
            degraded_turns=1,
            strategy_decisions=2,
            recovery_events=(
                {
                    "reason": "partial-world-sampled-match",
                    "sampled_matches": 3,
                    "sampled_unresolved_worlds": 1,
                    "exhaustively_excluded_worlds": 0,
                    "unsupported_public_evidence": (),
                },
            ),
        ),
        _game(1, outcome="bot-loss", strategy_decisions=1),
        _game(2, outcome="draw"),
    )

    summary = summarize_games(games)

    assert summary["games"] == 3
    assert summary["wins"] == 1
    assert summary["losses"] == 1
    assert summary["draws"] == 1
    assert summary["score_rate"] == 0.5
    assert summary["decisive_win_rate"] == 0.5
    assert summary["decisive_win_rate_95ci"] is not None
    assert summary["decisions"]["total"] == 12
    assert summary["decisions"]["fallback"] == 1
    assert summary["decisions"]["fallback_reasons"] == {
        "belief-search-deadline": 1
    }
    assert summary["decisions"]["degraded_turns"] == 1
    assert summary["decisions"]["strategy_plan_attached"] == 3
    assert summary["decision_seconds"]["p50"] == 2.5
    assert summary["decision_seconds"]["p95"] == 4.0
    assert summary["conditioning_seconds"]["p95"] == 0.4
    assert summary["recovery"]["events"] == 1
    assert summary["recovery"]["reasons"] == {
        "partial-world-sampled-match": 1
    }
    assert summary["recovery"]["sampled_matches"] == 3
    assert summary["recovery"]["sampled_unresolved_worlds"] == 1
    assert summary["recovery"]["exhaustively_excluded_worlds"] == 0


def test_summary_handles_all_draws_without_fake_decisive_interval():
    summary = summarize_games(
        (
            _game(0, outcome="draw"),
            _game(1, outcome="draw"),
        )
    )

    assert summary["decisive_win_rate"] is None
    assert summary["decisive_win_rate_95ci"] is None


def test_config_rejects_invalid_benchmark_shapes():
    with pytest.raises(ValueError, match="battles"):
        LeagueConfig(battles=0)
    with pytest.raises(ValueError, match="max_particles"):
        LeagueConfig(world_limit=8, max_particles=7)
    with pytest.raises(ValueError, match="decision_budget_seconds"):
        LeagueConfig(decision_budget_seconds=0.0)
    with pytest.raises(ValueError, match="worker_startup_timeout_seconds"):
        LeagueConfig(worker_startup_timeout_seconds=0.0)





def test_preview_choice_resolves_showdown_canonical_spacing():
    legal = (
        "team 1, 2, 3, 4",
        "team 2, 1, 3, 5",
    )

    assert _resolve_preview_choice(legal, "team 2135") == "team 2, 1, 3, 5"


def test_preview_choice_rejects_different_bring_order():
    with pytest.raises(StrengthLeagueError, match="preview is not legal"):
        _resolve_preview_choice(
            ("team 2, 1, 4, 5",),
            "team 2135",
        )


def test_v1_identifiers_are_explicit():
    assert RUN_SCHEMA == "offline-strength-league-v1"
    assert FIXTURE_ID == "current-roster-mirror-v1"
    assert BOT_ID == "belief-strategy-main-v1"
    assert BASELINE_ID == "public-fallback-v1"
