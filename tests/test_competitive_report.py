import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("competitive_report", Path(__file__).resolve().parents[1] /
                                            "scripts/competitive_evaluation_report.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def report():
    case = {"id": "direct-0-0-p1", "agents": {"p1": "v2", "p2": "production"},
            "teams": {"p1": "a", "p2": "b"}, "battle_seed": "seed", "pair": "direct-0-0",
            "category": "heldout-direct"}
    reverse = {**case, "id": "direct-0-0-p2", "agents": {"p1": "production", "p2": "v2"}}
    return {"cases": [case, reverse], "games": [{**item, "status": "complete", "winner": winner,
             "budget_seconds": 8, "rows": []} for item, winner in ((case, "P1"), (reverse, "P2"))], "budget_seconds": 8, "source_identity": {},
            "policy_sha256": "frozen", "production_sha256": "frozen"}


def test_analysis_validates_pairing_and_computes_rates():
    result = MODULE.analyze(report())
    assert result["strata"]["heldout-direct"]["agents"]["v2"]["score_rate"] == 1
    assert result["strata"]["reference-direct"]["agents"]["v2"]["score_rate"] is None


@pytest.mark.parametrize("field,value", [("budget_seconds", 1), ("battle_seed", "changed"),
                                         ("teams", {"p1": "different"})])
def test_rejects_unfair_comparison(field, value):
    data = report()
    data["games"][0][field] = value
    with pytest.raises(ValueError):
        MODULE.analyze(data)


def test_rejects_missing_cases_and_illegal_actions():
    data = report()
    data["games"] = []
    with pytest.raises(ValueError):
        MODULE.analyze(data)
    data = report()
    data["games"][0]["rows"] = [{"sides": {"p1": {"agent": "v2", "action": "bad", "public_choices": ["good"]}}}]
    with pytest.raises(ValueError):
        MODULE.analyze(data)
