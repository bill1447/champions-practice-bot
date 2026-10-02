from __future__ import annotations

import pytest

from champions_practice.reachability import (
    PublicReachabilityStep,
    ReachabilityCoverage,
    ReachabilityResult,
    ReachabilityStatus,
    witness_public_observation_sequence,
)


def _coverage(
    *,
    outcomes_examined: int = 4,
    randomness_exhaustive: bool = False,
    sequential_context_complete: bool = False,
) -> ReachabilityCoverage:
    return ReachabilityCoverage(
        sequential_context_fingerprint="sha256:ordered-transition-context",
        transitions_covered=2,
        outcomes_examined=outcomes_examined,
        randomness_domains=("damage-roll", "critical-hit"),
        randomness_exhaustive=randomness_exhaustive,
        sequential_context_complete=sequential_context_complete,
    )


def test_witness_is_positive_reachability_evidence_without_exclusion_authority():
    result = ReachabilityResult.witnessed(
        coverage=_coverage(outcomes_examined=1),
        witness_ids=("showdown-branch-17",),
    )

    assert result.status is ReachabilityStatus.WITNESSED
    assert result.establishes_reachability
    assert not result.establishes_impossibility
    assert result.conclusive


def test_bounded_sampling_miss_remains_unresolved():
    result = ReachabilityResult.unresolved(
        reason="bounded RNG search found no witness",
        coverage=_coverage(outcomes_examined=128),
    )

    assert result.status is ReachabilityStatus.UNRESOLVED
    assert not result.establishes_reachability
    assert not result.establishes_impossibility
    assert not result.conclusive


def test_exhaustive_disproof_requires_full_randomness_and_sequential_context():
    incomplete_randomness = _coverage(
        randomness_exhaustive=False,
        sequential_context_complete=True,
    )
    with pytest.raises(ValueError, match="exhaustive randomness"):
        ReachabilityResult.exhaustively_disproved(
            coverage=incomplete_randomness,
        )

    incomplete_history = _coverage(
        randomness_exhaustive=True,
        sequential_context_complete=False,
    )
    with pytest.raises(ValueError, match="full sequential transition context"):
        ReachabilityResult.exhaustively_disproved(
            coverage=incomplete_history,
        )


def test_exhaustive_disproof_is_the_only_negative_exclusion_evidence():
    result = ReachabilityResult.exhaustively_disproved(
        coverage=_coverage(
            outcomes_examined=256,
            randomness_exhaustive=True,
            sequential_context_complete=True,
        )
    )

    assert result.status is ReachabilityStatus.EXHAUSTIVELY_DISPROVED
    assert result.establishes_impossibility
    assert not result.establishes_reachability
    assert result.conclusive


def test_exhaustive_disproof_requires_at_least_one_examined_outcome():
    with pytest.raises(ValueError, match="at least one outcome"):
        ReachabilityResult.exhaustively_disproved(
            coverage=_coverage(
                outcomes_examined=0,
                randomness_exhaustive=True,
                sequential_context_complete=True,
            )
        )


def test_non_witness_result_cannot_carry_witness_ids():
    with pytest.raises(ValueError, match="cannot carry witnesses"):
        ReachabilityResult(
            status=ReachabilityStatus.UNRESOLVED,
            coverage=_coverage(),
            witness_ids=("forged-witness",),
            reason="sampling exhausted",
        )


@pytest.mark.parametrize(
    "status",
    (ReachabilityStatus.UNRESOLVED, ReachabilityStatus.UNSUPPORTED),
)
def test_inconclusive_statuses_require_an_explicit_reason(status: ReachabilityStatus):
    with pytest.raises(ValueError, match="require a reason"):
        ReachabilityResult(status=status, coverage=_coverage())


def test_unsupported_mechanics_are_not_negative_evidence():
    result = ReachabilityResult.unsupported(
        reason="mechanic has no authoritative enumerator",
        coverage=_coverage(outcomes_examined=3),
    )

    assert result.status is ReachabilityStatus.UNSUPPORTED
    assert not result.establishes_reachability
    assert not result.establishes_impossibility
    assert not result.conclusive


def test_inconclusive_result_cannot_claim_complete_exhaustive_coverage():
    with pytest.raises(ValueError, match="conclusive result"):
        ReachabilityResult.unresolved(
            reason="timeout after enumeration",
            coverage=_coverage(
                outcomes_examined=256,
                randomness_exhaustive=True,
                sequential_context_complete=True,
            ),
        )


def test_coverage_rejects_duplicate_randomness_domains():
    with pytest.raises(ValueError, match="must be unique"):
        ReachabilityCoverage(
            sequential_context_fingerprint="sha256:context",
            transitions_covered=1,
            outcomes_examined=1,
            randomness_domains=("damage-roll", "damage-roll"),
        )


class _FakeReachabilityWorker:
    def __init__(self, outcomes=None, *, timeout=False):
        self.outcomes = outcomes or {}
        self.timeout = timeout
        self.calls = 0

    def branch_many(self, *, state, branches):
        self.calls += 1
        if self.timeout:
            raise TimeoutError("synthetic worker timeout")
        resolved = []
        for index, branch in enumerate(branches):
            key = (state["node"], branch.get("rng_seed"))
            next_node, view = self.outcomes[key]
            resolved.append(
                {
                    "index": index,
                    "state": {"node": next_node},
                    "view": view,
                }
            )
        return resolved


def _public_step(view, *, seeds=("seed-a",), p1_choice="move a", p2_choice="move b"):
    return PublicReachabilityStep(
        p1_choice=p1_choice,
        p2_choice=p2_choice,
        expected_public_view=view,
        rng_seeds=seeds,
    )


def test_showdown_witness_probe_preserves_sequential_parentage():
    first = {"turn": 2, "marker": "first"}
    second = {"turn": 3, "marker": "second"}
    worker = _FakeReachabilityWorker(
        {
            ("root", "seed-a"): ("dead", {"turn": 2, "marker": "wrong"}),
            ("root", "seed-b"): ("path", first),
            ("path", "seed-c"): ("done", second),
        }
    )

    result = witness_public_observation_sequence(
        worker,
        state={"node": "root"},
        side="p2",
        steps=(
            _public_step(first, seeds=("seed-a", "seed-b")),
            _public_step(second, seeds=("seed-c",)),
        ),
    )

    assert result.status is ReachabilityStatus.WITNESSED
    assert result.establishes_reachability
    assert not result.establishes_impossibility
    assert result.coverage is not None
    assert result.coverage.transitions_covered == 2
    assert result.coverage.outcomes_examined == 3
    assert result.coverage.sequential_context_complete
    assert not result.coverage.randomness_exhaustive
    assert worker.calls == 2


def test_showdown_witness_probe_never_cartesian_combines_incompatible_outcomes():
    first = {"turn": 2, "marker": "first"}
    combined = {
        "turn": 3,
        "opponent": {"active": [{"hp_percent": 50, "status": "par"}]},
    }
    worker = _FakeReachabilityWorker(
        {
            ("root", "seed-a"): ("path-a", first),
            ("root", "seed-b"): ("path-b", first),
            (
                "path-a",
                "seed-c",
            ): (
                "done-a",
                {
                    "turn": 3,
                    "opponent": {
                        "active": [{"hp_percent": 50, "status": None}]
                    },
                },
            ),
            (
                "path-b",
                "seed-c",
            ): (
                "done-b",
                {
                    "turn": 3,
                    "opponent": {
                        "active": [{"hp_percent": 80, "status": "par"}]
                    },
                },
            ),
        }
    )

    result = witness_public_observation_sequence(
        worker,
        state={"node": "root"},
        side="p2",
        steps=(
            _public_step(first, seeds=("seed-a", "seed-b")),
            _public_step(combined, seeds=("seed-c",)),
        ),
    )

    assert result.status is ReachabilityStatus.UNRESOLVED
    assert not result.establishes_reachability
    assert not result.establishes_impossibility
    assert result.coverage is not None
    assert result.coverage.outcomes_examined == 4


def test_bounded_showdown_miss_is_unresolved_not_impossible():
    target = {"turn": 2, "marker": "wanted"}
    worker = _FakeReachabilityWorker(
        {
            ("root", "seed-a"): ("done", {"turn": 2, "marker": "other"}),
        }
    )

    result = witness_public_observation_sequence(
        worker,
        state={"node": "root"},
        side="p1",
        steps=(_public_step(target),),
    )

    assert result.status is ReachabilityStatus.UNRESOLVED
    assert not result.conclusive
    assert not result.establishes_impossibility


def test_reachability_timeout_is_unresolved_not_negative_evidence():
    worker = _FakeReachabilityWorker(timeout=True)

    result = witness_public_observation_sequence(
        worker,
        state={"node": "root"},
        side="p1",
        steps=(_public_step({"turn": 2}),),
    )

    assert result.status is ReachabilityStatus.UNRESOLVED
    assert not result.establishes_impossibility
    assert worker.calls == 1


def test_unsupported_public_mechanics_fail_without_worker_authority():
    worker = _FakeReachabilityWorker()
    target = {
        "turn": 2,
        "public_event_delta": {"unsupported": ["future-mechanic"]},
    }

    result = witness_public_observation_sequence(
        worker,
        state={"node": "root"},
        side="p1",
        steps=(_public_step(target),),
    )

    assert result.status is ReachabilityStatus.UNSUPPORTED
    assert not result.establishes_impossibility
    assert worker.calls == 0


def test_branch_budget_exhaustion_cannot_become_exclusion_evidence():
    target = {"turn": 2, "marker": "wanted"}
    worker = _FakeReachabilityWorker(
        {
            ("root", "seed-a"): ("miss", {"turn": 2, "marker": "other"}),
            ("root", "seed-b"): ("hit", target),
        }
    )

    result = witness_public_observation_sequence(
        worker,
        state={"node": "root"},
        side="p1",
        steps=(_public_step(target, seeds=("seed-a", "seed-b")),),
        max_branches=1,
    )

    assert result.status is ReachabilityStatus.UNRESOLVED
    assert not result.establishes_impossibility
    assert worker.calls == 1


def test_reachability_step_rejects_raw_empty_commands():
    with pytest.raises(ValueError, match="non-empty exact command"):
        PublicReachabilityStep(
            p1_choice="",
            p2_choice="move b",
            expected_public_view={"turn": 2},
        )
