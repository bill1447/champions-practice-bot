"""Mechanical equivalence and experiment input-boundary regressions."""

from copy import deepcopy

import pytest

from champions_practice.native_stochastic_tracker import NativeStochasticTracker
from champions_practice.native_stochastic_validator import (
    continuous_witness_lineages, first_difference, mechanical_fingerprint, mechanical_projection,
)


def test_different_rng_streams_can_represent_the_same_current_mechanics():
    left = {"prng": {"seed": [1, 2, 3, 4]}, "prngSeed": "hypothesis-a",
            "log": ["|t:|1"], "inputLog": ["seed a"],
            "sides": [{"pokemon": [{"statusState": {"time": 2}}]}], "queue": []}
    right = deepcopy(left)
    right.update(prng={"seed": [8, 7, 6, 5]}, prngSeed="hypothesis-b", log=["|t:|2"], inputLog=["seed b"])
    assert left != right
    assert mechanical_fingerprint(left) == mechanical_fingerprint(right)
    assert first_difference(mechanical_projection(left), mechanical_projection(right)) is None


@pytest.mark.parametrize("field,before,after", (
    ("queue", [{"moveid": "partingshot", "targetLoc": 1}], []),
    ("statusState", {"id": "slp", "time": 1}, {"id": "slp", "time": 2}),
    ("abilityState", {"id": "disguise", "busted": False}, {"id": "disguise", "busted": True}),
    ("volatiles", {"allyswitch": {"counter": 3}}, {"allyswitch": {"counter": 9}}),
    ("moveLastTurnResult", False, None),
    ("effectOrder", 4, 5),
    ("item", "sitrusberry", ""),
    ("activeTurns", 1, 0),
    ("speedOrder", [0, 1, 2, 3], [1, 0, 2, 3]),
))
def test_future_relevant_state_is_never_normalized_away(field, before, after):
    left, right = {field: before}, {field: after}
    assert first_difference(mechanical_projection(left), mechanical_projection(right))
    assert mechanical_fingerprint(left) != mechanical_fingerprint(right)


@pytest.mark.parametrize("method,kwargs", (
    ("initialize", {"seed": "oracle-canary"}),
    ("initialize", {"state": {"prng": "oracle-canary"}}),
    ("advance", {"prng": "oracle-canary"}),
    ("advance", {"serialized_state": "oracle-canary"}),
))
def test_python_tracker_api_has_no_privileged_input_parameter(method, kwargs):
    # No worker is started: rejection happens at the capability's call boundary.
    tracker = object.__new__(NativeStochasticTracker)
    with pytest.raises(TypeError):
        getattr(tracker, method)(**kwargs)


def test_mechanical_projection_keeps_missing_distinct_from_null_and_does_not_mutate():
    source = {"prng": "private", "sides": [{"status": "slp"}], "moveLastTurnResult": None}
    before = deepcopy(source)
    projected = mechanical_projection(source)
    projected["sides"][0]["status"] = ""
    assert source == before
    assert first_difference({"moveLastTurnResult": None}, {}) == "$:keys"


def test_a_terminal_match_cannot_restore_continuous_coverage_after_an_ancestry_loss():
    roots = continuous_witness_lineages(set(), [{"lineage": "root", "parent_lineage": None}], opening=True)
    next_turn = continuous_witness_lineages(roots, [{"lineage": "child", "parent_lineage": "root"}])
    assert next_turn == {"child"}
    lost = continuous_witness_lineages(next_turn, [])
    recovered = continuous_witness_lineages(lost, [{"lineage": "terminal", "parent_lineage": "child"}])
    assert recovered == set()


def test_a_matching_child_of_an_unmatched_parent_is_not_a_continuous_witness():
    matches = continuous_witness_lineages({"matching-parent"}, [
        {"lineage": "good", "parent_lineage": "matching-parent"},
        {"lineage": "recovered", "parent_lineage": "unmatched-parent"},
    ])
    assert matches == {"good"}
