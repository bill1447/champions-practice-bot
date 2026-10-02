"""Typed mechanics-reachability evidence with no live-admission authority.

This module defines the result contract for future Showdown-backed stochastic
damage and categorical reachability. It is intentionally not integrated with
recovery admission or live belief decisions.

A witnessed outcome establishes mechanical reachability for the supplied
sequential context. An exhaustively-disproved outcome establishes mechanical
impossibility only when the result explicitly covers the full sequential
transition context and all relevant randomness. Bounded sampling misses,
timeouts, and unsupported mechanics remain unresolved or unsupported and may
not be promoted into exclusion evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ReachabilityStatus(str, Enum):
    """Authority level of one mechanics-reachability query."""

    WITNESSED = "witnessed"
    EXHAUSTIVELY_DISPROVED = "exhaustively-disproved"
    UNRESOLVED = "unresolved"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class ReachabilityCoverage:
    """Declared mechanics coverage for one sequential reachability query.

    The fingerprint binds evidence to the complete ordered transition context
    supplied by the eventual mechanics implementation. randomness_domains
    names the relevant random dimensions considered by that implementation;
    an empty tuple is valid for a deterministic transition.
    """

    sequential_context_fingerprint: str
    transitions_covered: int
    outcomes_examined: int
    randomness_domains: tuple[str, ...] = ()
    randomness_exhaustive: bool = False
    sequential_context_complete: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.sequential_context_fingerprint, str)
            or not self.sequential_context_fingerprint.strip()
        ):
            raise ValueError("reachability coverage requires a context fingerprint")
        if self.transitions_covered <= 0:
            raise ValueError("reachability coverage must include at least one transition")
        if self.outcomes_examined < 0:
            raise ValueError("outcomes_examined must not be negative")
        if any(
            not isinstance(domain, str) or not domain.strip()
            for domain in self.randomness_domains
        ):
            raise ValueError("randomness domains must be non-empty strings")
        if len(set(self.randomness_domains)) != len(self.randomness_domains):
            raise ValueError("randomness domains must be unique")


@dataclass(frozen=True)
class ReachabilityResult:
    """Mechanics evidence only; this object has no recovery-install operation."""

    status: ReachabilityStatus
    coverage: ReachabilityCoverage | None = None
    witness_ids: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if any(
            not isinstance(witness_id, str) or not witness_id.strip()
            for witness_id in self.witness_ids
        ):
            raise ValueError("witness ids must be non-empty strings")
        if len(set(self.witness_ids)) != len(self.witness_ids):
            raise ValueError("witness ids must be unique")

        if self.status is ReachabilityStatus.WITNESSED:
            if self.coverage is None:
                raise ValueError("witnessed reachability requires declared coverage")
            if not self.witness_ids:
                raise ValueError("witnessed reachability requires a mechanics witness")
            if self.coverage.outcomes_examined <= 0:
                raise ValueError("witnessed reachability must examine at least one outcome")
            return

        if self.witness_ids:
            raise ValueError("non-witness reachability results cannot carry witnesses")

        if self.status is ReachabilityStatus.EXHAUSTIVELY_DISPROVED:
            if self.coverage is None:
                raise ValueError("exhaustive disproof requires declared coverage")
            if not self.coverage.randomness_exhaustive:
                raise ValueError("exhaustive disproof requires exhaustive randomness coverage")
            if not self.coverage.sequential_context_complete:
                raise ValueError(
                    "exhaustive disproof requires the full sequential transition context"
                )
            if self.coverage.outcomes_examined <= 0:
                raise ValueError("exhaustive disproof must examine at least one outcome")
            return

        if self.coverage is not None and (
            self.coverage.randomness_exhaustive
            and self.coverage.sequential_context_complete
        ):
            raise ValueError(
                "fully exhaustive coverage must be represented as a conclusive result"
            )

        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError(
                "unresolved and unsupported reachability results require a reason"
            )

    @property
    def establishes_reachability(self) -> bool:
        """Whether this result contains a concrete mechanics witness."""

        return self.status is ReachabilityStatus.WITNESSED

    @property
    def establishes_impossibility(self) -> bool:
        """Whether this result is valid exclusion evidence for this exact context."""

        return self.status is ReachabilityStatus.EXHAUSTIVELY_DISPROVED

    @property
    def conclusive(self) -> bool:
        """Whether mechanics reachability is established in either direction."""

        return self.establishes_reachability or self.establishes_impossibility

    @classmethod
    def witnessed(
        cls,
        *,
        coverage: ReachabilityCoverage,
        witness_ids: tuple[str, ...],
    ) -> "ReachabilityResult":
        return cls(
            status=ReachabilityStatus.WITNESSED,
            coverage=coverage,
            witness_ids=witness_ids,
        )

    @classmethod
    def exhaustively_disproved(
        cls,
        *,
        coverage: ReachabilityCoverage,
    ) -> "ReachabilityResult":
        return cls(
            status=ReachabilityStatus.EXHAUSTIVELY_DISPROVED,
            coverage=coverage,
        )

    @classmethod
    def unresolved(
        cls,
        *,
        reason: str,
        coverage: ReachabilityCoverage | None = None,
    ) -> "ReachabilityResult":
        return cls(
            status=ReachabilityStatus.UNRESOLVED,
            coverage=coverage,
            reason=reason,
        )

    @classmethod
    def unsupported(
        cls,
        *,
        reason: str,
        coverage: ReachabilityCoverage | None = None,
    ) -> "ReachabilityResult":
        return cls(
            status=ReachabilityStatus.UNSUPPORTED,
            coverage=coverage,
            reason=reason,
        )
