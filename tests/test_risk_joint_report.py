import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location("risk_report", Path(__file__).parents[1]/"scripts/risk_joint_report.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def report():
    return {"source_identity": {}, "catalog_sha256": "catalog", "team_sha256": {}, "budget_seconds": 8,
            "scenario_weights_are_probabilities": False, "baseline_default_unchanged": True,
            "games": [{"id": agent, "agent": agent, "seed": "seed", "side": "p1", "opponent": "guard",
                       "p1_team": "a", "p2_team": "b", "status": "complete", "win": agent == "risk",
                       "rows": []} for agent in ("baseline", "risk")]}


def test_paired_summary():
    assert module.analyze([report()])["paired_outcomes"]["guard"] == {"risk_only_win": 1}


def test_missing_pair_rejected():
    data = report()
    data["games"].pop()
    with pytest.raises(ValueError, match="unpaired"):
        module.analyze([data])


def test_failed_game_not_scored_as_loss():
    data = report()
    data["games"][0]["status"] = "failed"
    with pytest.raises(ValueError, match="incomplete"):
        module.analyze([data])


def test_changed_source_rejected():
    first, second = report(), report()
    second["source_identity"] = {"changed": True}
    with pytest.raises(ValueError, match="source_identity"):
        module.analyze([first, second])
