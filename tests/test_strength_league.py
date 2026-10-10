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
    finite_reachability_witnesses: int = 0,
    finite_reachability_disproofs: int = 0,
    finite_reachability_unresolved: int = 0,
    finite_reachability_leaves: int = 0,
    recovery_events: tuple[dict, ...] = (),
    recovery_retry_events: tuple[dict, ...] = (),
    own_speed_diagnostics: tuple[dict, ...] = (),
    own_speed_transport_issues: tuple[dict, ...] = (),
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
        finite_reachability_witnesses=finite_reachability_witnesses,
        finite_reachability_disproofs=finite_reachability_disproofs,
        finite_reachability_unresolved=finite_reachability_unresolved,
        finite_reachability_leaves=finite_reachability_leaves,
        recovery_events=recovery_events,
        recovery_retry_events=recovery_retry_events,
        own_speed_diagnostics=own_speed_diagnostics,
        own_speed_transport_issues=own_speed_transport_issues,
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
            finite_reachability_witnesses=2,
            finite_reachability_disproofs=1,
            finite_reachability_unresolved=3,
            finite_reachability_leaves=384,
            recovery_events=(
                {
                    "reason": "partial-world-sampled-match",
                    "sampled_matches": 3,
                    "sampled_unresolved_worlds": 1,
                    "exhaustively_excluded_worlds": 0,
                    "unsupported_public_evidence": (),
                    "structural_mismatch_paths": (
                        ("$.request.active[0]", 7),
                        ("$.public_event_delta.turn", 2),
                    ),
                    "structural_mismatch_worlds": (
                        ("world-a", 5),
                        ("world-b", 4),
                    ),
                },
            ),
            recovery_retry_events=(
                {
                    "worker_attempts": 2,
                    "returned_updates": 1,
                    "deadline_timeouts": 1,
                    "finite_progress_callbacks": 3,
                    "finite_progress_changes": 2,
                    "seed_cursor_advanced": True,
                    "continuation_changed": True,
                    "continuation_persisted": True,
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
    assert summary["recovery"]["finite_reachability_witnesses"] == 2
    assert summary["recovery"]["finite_reachability_disproofs"] == 1
    assert summary["recovery"]["finite_reachability_unresolved"] == 3
    assert summary["recovery"]["finite_reachability_leaves"] == 384
    assert summary["recovery"]["retry_events"] == 1
    assert summary["recovery"]["retry_worker_attempts"] == 2
    assert summary["recovery"]["retry_returned_updates"] == 1
    assert summary["recovery"]["retry_deadline_timeouts"] == 1
    assert summary["recovery"]["retry_finite_progress_callbacks"] == 3
    assert summary["recovery"]["retry_finite_progress_changes"] == 2
    assert summary["recovery"]["retry_seed_cursor_advanced"] == 1
    assert summary["recovery"]["retry_continuation_changed"] == 1
    assert summary["recovery"]["retry_continuation_persisted"] == 1
    assert summary["recovery"]["top_structural_mismatch_paths"] == [
        ["$.request.active[0]", 7],
        ["$.public_event_delta.turn", 2],
    ]
    assert summary["recovery"]["top_structural_mismatch_worlds"] == [
        ["world-a", 5],
        ["world-b", 4],
    ]


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
    assert BASELINE_ID == "attacking-mega-legal-v1"


def test_league_summary_retains_bounded_own_only_speed_forensics():
    own = {
        "decision_index": 3,
        "fallback_reason": "fresh-public-world:own-unburden-speed-unresolved",
        "species": "Sneasler",
        "observed_speed": 121,
        "native_cached_speed": 242,
        "native_action_speed": 122,
        "unburden_volatile": False,
        "stage": "after-native-unburden-removal",
    }
    game = _game(
        3, outcome="bot-win", fallback_decisions=1,
        own_speed_diagnostics=(own,),
    )
    summary = summarize_games((game,))
    assert summary["decisions"]["fallback"] == 1
    assert summary["decisions"]["own_speed_diagnostics"] == [
        {"game_index": 3, **own},
    ]
    assert "opponent_set" not in summary["decisions"]["own_speed_diagnostics"][0]


def test_league_summary_separates_mechanics_and_telemetry_transport_issue():
    issue = {
        "decision_index": 7,
        "mechanics_reason": "own-unburden-speed-unresolved",
        "mismatch_path": "$.player.active_details[0].speed",
        "diagnostic_issue": "invalid:native_stored_speed",
    }
    game = _game(
        5, outcome="bot-win", fallback_decisions=1,
        own_speed_transport_issues=(issue,),
    )
    summary = summarize_games((game,))
    assert summary["decisions"]["fallback"] == 1
    assert summary["decisions"]["own_speed_transport_issues"] == [
        {"game_index": 5, **issue},
    ]
    assert summary["decisions"]["own_speed_diagnostics"] == []
    assert "native-proposal-error:RuntimeError" not in str(issue)


def test_game_result_decision_trace_is_serializable_and_backwards_compatible():
    from dataclasses import asdict
    import json

    game = _game(0, outcome="bot-win")
    assert asdict(game)["decision_trace"] == ()
    trace = {
        "decision_index": 0,
        "observed_turn_before": 4,
        "observed_phase_before": "move",
        "bot_public_before": {
            "turn": 4, "phase": "move",
            "player": {"team": [{"species": "Gardevoir", "status": None}]},
            "field": {"terrain": "psychicterrain"},
        },
        "ai_public_choices_before": ["move protect", "switch 3"],
        "observed_phase_after": "switch",
        "bot_public_after": {"turn": 4, "phase": "switch"},
        "mode": "fallback", "fallback_reason": "unsupported-own-form",
        "chosen_action": "switch 3", "baseline_legal_choice_count": 4,
    }
    enriched = GameResult(**{**asdict(game), "decision_trace": (trace,)})
    assert json.loads(json.dumps(asdict(enriched)))["decision_trace"][0] == trace
