"""Non-circular real-collapse challenge assertions.

These tests require that historical outcomes never be promoted to actual
reconstruction success and that oracle truth is not an input to the separate
public constructor.
"""

from __future__ import annotations

import inspect

import pytest

from champions_practice.rebase_challenge import (
    CHALLENGE_SCHEMA,
    _native_mechanics,
    _write_offline_oracle_trace,
    _verified_ai_public_projection,
    _public_only_step,
    evaluate_historical_report,
    load_targets,
    main,
)


def _stand_in_report(targets):
    # Deterministic historical report-shaped test, not fabricated test success.
    cases = targets["cases"]
    games = [
        {
            "game_index": n,
            "fallback_decisions": 0,
            "degraded_turns": 0,
            "recovery_events": [],
        }
        for n in range(8)
    ]
    for item in cases:
        recovery = []
        for offset, turn in enumerate(item["observation_turns"]):
            recovery.append({
                "observation_turn": turn,
                "reason": "zero-sampled-match" if offset == 0 else "pending-backlog",
                "observed_opponent_actions": [
                    '{"move":"' + move + '","slot":1}'
                    for move in item["initial_actions"]
                ] if offset == 0 else [],
            })
        games[item["game_index"]].update({
            "fallback_decisions": item["fallback_decisions"],
            "degraded_turns": item["degraded_turns"],
            "recovery_events": recovery,
        })
    return {
        "schema": "offline-strength-league-v1",
        "run_id": targets["source"]["run_id"],
        "git_commit": targets["source"]["git_commit"],
        "showdown_revision": targets["source"]["pinned_showdown_revision"],
        "fixture_id": targets["source"]["fixture_id"],
        "config": {"seed": targets["source"]["seed"]},
        "games": games,
        "summary": {
            "decisions": {
                "total": 85,
                "fallback": 15,
                "degraded_turns": 19,
            },
            "recovery": {"events": 19, "retry_deadline_timeouts": 1},
        },
    }


def test_historical_collapse_manifest_is_exact_and_not_claimed_recovered():
    targets = load_targets()
    result = evaluate_historical_report(_stand_in_report(targets), targets)
    assert result["schema"] == CHALLENGE_SCHEMA
    assert result["verdict"] == "NOT_TESTED_INSUFFICIENT_RUNTIME_EVIDENCE"
    assert result["evaluated_cases"] == 0
    assert result["successful_cases"] == 0
    assert len(result["cases"]) == 3
    assert {(c["game_number"], c["initial_collapse_turn"]) for c in result["cases"]} == {
        (1, 5), (2, 8), (8, 8),
    }
    assert all(not x["proof_of_success"] for x in result["cases"])
    assert all(x["true_world_survived"] is None for x in result["cases"])
    assert all(x["retained_information"] is None for x in result["cases"])


def test_manifest_rejects_regressed_collapse_history():
    targets = load_targets()
    report = _stand_in_report(targets)
    report["games"][1]["recovery_events"][0]["observed_opponent_actions"] = [
        '{"move":"fake","slot":1}',
    ]
    with pytest.raises(ValueError, match="action evidence"):
        evaluate_historical_report(report, targets)
    report = _stand_in_report(targets)
    report["summary"]["decisions"]["fallback"] = 0
    with pytest.raises(ValueError, match="measurements"):
        evaluate_historical_report(report, targets)



def test_oracle_evidence_requires_matching_human_views_before_ai_projection():
    # The playable facade exposes p1 after the turn; the current-state
    # constructor requires p2. They have different private sides and requests.
    league_human = {
        "turn": 8,
        "request": {"side": "p1", "choices": ["move protect"]},
        "player": {"name": "Human"},
        "opponent": {"name": "AI"},
    }
    independent_human = {
        **league_human,
        "request": dict(league_human["request"]),
    }
    independent_ai = {
        "turn": 8,
        "request": {"side": "p2", "choices": ["move expandingforce"]},
        "player": {"name": "AI"},
        "opponent": {"name": "Human"},
    }
    assert _verified_ai_public_projection(
        observed_human_view=league_human,
        independent_human_view=independent_human,
        independent_ai_view=independent_ai,
    ) is independent_ai
    # The original CI failure incorrectly compared a p2 view to a p1 view.
    assert _verified_ai_public_projection(
        observed_human_view=league_human,
        independent_human_view=independent_ai,
        independent_ai_view=independent_ai,
    ) is None
    conflicting_human = {
        **independent_human, "request": {"side": "p1", "choices": ["move struggle"]}
    }
    assert _verified_ai_public_projection(
        observed_human_view=league_human,
        independent_human_view=conflicting_human,
        independent_ai_view=independent_ai,
    ) is None

def test_truth_cannot_enter_public_reconstruction_signature():
    signature = inspect.signature(_public_only_step)
    for forbidden in (
        "oracle_state", "human_choice", "session_id", "seed",
        "opponent_team", "particles",
    ):
        assert forbidden not in signature.parameters
    for name in ("previous_view", "current_view", "own_choice", "checkpoints"):
        assert name in signature.parameters


def test_true_hidden_mechanics_comparison_excludes_rng_but_preserves_pp():
    base = {
        "turn": 8,
        "log": ["anything"],
        "prng": [1, 2, 3, 4],
        "sides": [
            {"pokemon": [{"hp": 30, "moveSlots": [{"id": "woodhammer", "pp": 4}]}]},
            {"pokemon": []},
        ],
    }
    altered = {**base, "log": ["different"], "prng": [4, 3, 2, 1]}
    assert _native_mechanics(base) == _native_mechanics(altered)
    altered = {
        **altered,
        "sides": [
            {"pokemon": [{"hp": 30, "moveSlots": [{"id": "woodhammer", "pp": 3}]}]},
            {"pokemon": []},
        ],
    }
    assert _native_mechanics(base) != _native_mechanics(altered)


def test_historical_only_command_reports_incomplete_evaluation(tmp_path):
    output = tmp_path / "challenge.json"
    assert main(["--output", str(output)]) == 0
    import json
    report = json.loads(output.read_text())
    assert report["verdict"] == "HISTORICAL_ONLY_NOT_A_REBASE_TRIAL"
    assert report["summary"]["complete_recovery_demonstrated"] is False
    assert report["summary"]["posterior_information_retention_measured"] is False
    assert main(["--output", str(output), "--require-recovery"]) == 2


def test_offline_oracle_trace_exports_actions_and_both_native_snapshots(tmp_path):
    import json
    path = tmp_path / "game-2-oracle-trace.json"
    turn = {
        "decision_index": 8,
        "p1_baseline_choice": "move protect",
        "p2_bot_choice": "move woodhammer",
        "legacy_recovery_reason": "zero-sampled-match",
        "before": {"native_state": {"turn": 8, "sides": []}},
        "after": {"native_state": {"turn": 9, "sides": []}},
    }
    _write_offline_oracle_trace(path, 2, [turn])
    exported = json.loads(path.read_text(encoding="utf-8"))
    assert exported["schema"] == "offline-collapse-oracle-trace-v1"
    assert exported["game_number"] == 2
    assert exported["authority"] == "offline-forensics-only-secret-state-not-for-bot"
    assert exported["turns"] == [turn]
    assert exported["turns"][0]["before"]["native_state"]["turn"] == 8
    assert exported["turns"][0]["after"]["native_state"]["turn"] == 9
