"""The experiment must not claim improvement from mismatched or incomplete games."""

from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("native_frontier_compare",
    Path(__file__).resolve().parents[1] / "scripts/native_frontier_compare.py")
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


def report():
    rows = [{"terminal": False, "continuous_mechanical_witnesses": 1, "outcome": "witnessed",
             "validator": {"mechanical_witnesses": 1}},
            {"terminal": True, "continuous_mechanical_witnesses": 0, "outcome": "witnessed",
             "validator": {"mechanical_witnesses": 1}}]
    return {"generation": "guided", "source_identity": {"sha256": "same-runtime"},
            "showdown_revision": "pinned", "samples_per_checkpoint": 96, "checkpoint_budget_ms": 600,
            "oracle_seed_offset": 0, "include_mixed_policy": False,
            "checkpoint_outcomes": {"witnessed": 2}, "continuous_mechanical_games": 0,
            "games": [{"fixture": "fixture", "policy": "policy", "checkpoints": rows,
                       "completed_reference_game": True, "continuous_mechanical_lineage_to_terminal": False,
                       "terminal_outcome": "witnessed", "reference_trace_fingerprint": "same-game"}]}


def test_a_terminal_recovery_is_not_counted_as_continuous_maintenance():
    data = report()
    result = comparison.compare(data, deepcopy(data))
    assert result["candidate"]["terminal_witnesses"] == 1
    assert result["candidate"]["continuous_games"] == 0
    assert result["candidate"]["continuous_witnessed_checkpoints"] == 1


@pytest.mark.parametrize("key,value", (("oracle_seed_offset", 1), ("checkpoint_budget_ms", 500),
                                      ("samples_per_checkpoint", 128), ("showdown_revision", "different")))
def test_different_reference_or_resource_configurations_cannot_be_compared(key, value):
    original, changed = report(), report()
    changed[key] = value
    with pytest.raises(ValueError):
        comparison.compare(original, changed)


def test_different_runtime_sources_cannot_be_compared():
    original, changed = report(), report()
    changed["source_identity"]["sha256"] = "different"
    with pytest.raises(ValueError):
        comparison.compare(original, changed)


def test_different_public_command_traces_cannot_be_compared():
    original, changed = report(), report()
    changed["games"][0]["reference_trace_fingerprint"] = "different"
    with pytest.raises(ValueError):
        comparison.compare(original, changed)


def test_nonterminal_reference_game_cannot_be_presented_as_complete():
    changed = report()
    changed["games"][0]["checkpoints"][-1]["terminal"] = False
    with pytest.raises(ValueError):
        comparison.compare(report(), changed)


def test_a_false_continuous_lineage_claim_is_rejected():
    changed = report()
    changed["games"][0]["continuous_mechanical_lineage_to_terminal"] = True
    with pytest.raises(ValueError):
        comparison.compare(report(), changed)


def test_a_false_mechanical_witness_claim_is_rejected():
    changed = report()
    changed["games"][0]["checkpoints"][1]["validator"]["mechanical_witnesses"] = 0
    with pytest.raises(ValueError):
        comparison.compare(report(), changed)
