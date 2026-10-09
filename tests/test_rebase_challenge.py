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


def test_truth_cannot_enter_public_reconstruction_signature():
    signature = inspect.signature(_public_only_step)
    assert "oracle_state" not in signature.parameters
    assert "human_choice" not in signature.parameters
    assert "session_id" not in signature.parameters
    assert "opponent_team" not in signature.parameters
    assert "particles" not in signature.parameters
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
