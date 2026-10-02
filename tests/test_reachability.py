from __future__ import annotations

import pytest

from champions_practice.reachability import (
    ReachabilityCoverage,
    ReachabilityResult,
    ReachabilityStatus,
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
