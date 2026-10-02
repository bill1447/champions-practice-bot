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

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from champions_practice.observation_beliefs import public_observation_signature


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


class ReachabilityWorker(Protocol):
    """Restricted mechanics surface used by bounded reachability probes."""

    def branch_many(
        self,
        *,
        state: dict[str, Any],
        branches: list[dict[str, Any]],
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class PublicReachabilityStep:
    """One exact action pair and public outcome required by a witness path."""

    p1_choice: str
    p2_choice: str
    expected_public_view: dict[str, Any]
    rng_seeds: tuple[str | None, ...] = (None,)

    def __post_init__(self) -> None:
        for side, choice in (("p1", self.p1_choice), ("p2", self.p2_choice)):
            if not isinstance(choice, str) or not choice.strip():
                raise ValueError(
                    f"{side} reachability choice must be a non-empty exact command"
                )
        if not isinstance(self.expected_public_view, dict):
            raise ValueError("expected_public_view must be a dictionary")
        if not self.rng_seeds:
            raise ValueError("reachability step requires at least one RNG sample")
        if any(
            seed is not None
            and (not isinstance(seed, str) or not seed.strip())
            for seed in self.rng_seeds
        ):
            raise ValueError("RNG samples must be non-empty strings or None")


def _reachability_hash(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _public_target_unsupported(view: dict[str, Any]) -> tuple[str, ...]:
    delta = view.get("public_event_delta")
    if not isinstance(delta, dict):
        return ()
    unsupported = delta.get("unsupported")
    if not isinstance(unsupported, list):
        return ()
    return tuple(
        value
        for value in unsupported
        if isinstance(value, str) and value.strip()
    )


def _probe_context_fingerprint(
    *,
    state: dict[str, Any],
    side: str,
    steps: tuple[PublicReachabilityStep, ...],
    previews: dict[str, list[str]] | None,
    max_branches: int,
) -> str:
    return "sha256:" + _reachability_hash(
        {
            "state": state,
            "side": side,
            "previews": previews,
            "max_branches": max_branches,
            "steps": [
                {
                    "p1_choice": step.p1_choice,
                    "p2_choice": step.p2_choice,
                    "expected_public_signature": public_observation_signature(
                        step.expected_public_view
                    ),
                    "rng_seeds": step.rng_seeds,
                }
                for step in steps
            ],
        }
    )


def _sampled_coverage(
    *,
    fingerprint: str,
    transitions_covered: int,
    outcomes_examined: int,
    sequential_context_complete: bool,
) -> ReachabilityCoverage | None:
    if transitions_covered <= 0:
        return None
    return ReachabilityCoverage(
        sequential_context_fingerprint=fingerprint,
        transitions_covered=transitions_covered,
        outcomes_examined=outcomes_examined,
        randomness_domains=("showdown-prng-seed",),
        randomness_exhaustive=False,
        sequential_context_complete=sequential_context_complete,
    )


def witness_public_observation_sequence(
    worker: ReachabilityWorker,
    *,
    state: dict[str, Any],
    side: str,
    steps: tuple[PublicReachabilityStep, ...],
    previews: dict[str, list[str]] | None = None,
    max_branches: int = 4096,
) -> ReachabilityResult:
    """Search bounded Showdown branches for one exact sequential public witness.

    This is positive-evidence machinery only. Every child transition is resolved
    by Showdown from the exact parent state that produced it, so outcomes from
    incompatible paths are never combined. Failure to find a witness remains
    UNRESOLVED because the configured RNG seeds are bounded samples rather than
    exhaustive mechanics enumeration.
    """

    if side not in {"p1", "p2"}:
        raise ValueError("reachability side must be p1 or p2")
    if not isinstance(state, dict) or not state:
        raise ValueError("reachability requires a serialized Showdown state")
    if not steps:
        raise ValueError("reachability requires at least one sequential step")
    if max_branches <= 0:
        raise ValueError("max_branches must be positive")

    for index, step in enumerate(steps):
        unsupported = _public_target_unsupported(step.expected_public_view)
        if unsupported:
            return ReachabilityResult.unsupported(
                reason=(
                    f"transition {index + 1} contains unsupported public mechanics "
                    f"evidence: {', '.join(unsupported)}"
                )
            )

    fingerprint = _probe_context_fingerprint(
        state=state,
        side=side,
        steps=steps,
        previews=previews,
        max_branches=max_branches,
    )
    paths: list[tuple[dict[str, Any], tuple[str | None, ...]]] = [
        (state, ())
    ]
    outcomes_examined = 0
    transitions_covered = 0

    for step_index, step in enumerate(steps):
        wanted = public_observation_signature(step.expected_public_view)
        next_paths: list[
            tuple[dict[str, Any], tuple[str | None, ...]]
        ] = []
        final_step = step_index == len(steps) - 1

        for parent_state, seed_path in paths:
            remaining = max_branches - outcomes_examined
            if remaining <= 0:
                return ReachabilityResult.unresolved(
                    reason=(
                        "bounded reachability branch budget exhausted before "
                        "the sequential query completed"
                    ),
                    coverage=_sampled_coverage(
                        fingerprint=fingerprint,
                        transitions_covered=transitions_covered,
                        outcomes_examined=outcomes_examined,
                        sequential_context_complete=False,
                    ),
                )

            selected_seeds = step.rng_seeds[:remaining]
            truncated = len(selected_seeds) < len(step.rng_seeds)
            branches: list[dict[str, Any]] = []
            for seed in selected_seeds:
                branch: dict[str, Any] = {
                    "p1_choice": step.p1_choice,
                    "p2_choice": step.p2_choice,
                    "include_state": True,
                    "view_side": side,
                    "rng_seed": seed,
                }
                if previews is not None:
                    branch["previews"] = previews
                branches.append(branch)

            try:
                resolved = worker.branch_many(
                    state=parent_state,
                    branches=branches,
                )
            except TimeoutError:
                return ReachabilityResult.unresolved(
                    reason=(
                        f"Showdown reachability probe timed out at transition "
                        f"{step_index + 1}"
                    ),
                    coverage=_sampled_coverage(
                        fingerprint=fingerprint,
                        transitions_covered=transitions_covered,
                        outcomes_examined=outcomes_examined,
                        sequential_context_complete=False,
                    ),
                )

            if len(resolved) != len(branches):
                raise RuntimeError(
                    "reachability worker returned an incomplete branch batch"
                )

            outcomes_examined += len(resolved)
            transitions_covered = step_index + 1

            for index, (seed, branch_result) in enumerate(
                zip(selected_seeds, resolved, strict=True)
            ):
                if branch_result.get("index") != index:
                    raise RuntimeError(
                        "reachability worker returned branches out of contract order"
                    )
                child_state = branch_result.get("state")
                public_view = branch_result.get("view")
                if not isinstance(child_state, dict) or not isinstance(
                    public_view,
                    dict,
                ):
                    raise RuntimeError(
                        "reachability worker omitted exact state or public view"
                    )
                if public_observation_signature(public_view) != wanted:
                    continue

                child_seed_path = seed_path + (seed,)
                if final_step:
                    witness_id = "sha256:" + _reachability_hash(
                        {
                            "context": fingerprint,
                            "rng_path": child_seed_path,
                        }
                    )
                    return ReachabilityResult.witnessed(
                        coverage=ReachabilityCoverage(
                            sequential_context_fingerprint=fingerprint,
                            transitions_covered=len(steps),
                            outcomes_examined=outcomes_examined,
                            randomness_domains=("showdown-prng-seed",),
                            randomness_exhaustive=False,
                            sequential_context_complete=True,
                        ),
                        witness_ids=(witness_id,),
                    )
                next_paths.append((child_state, child_seed_path))

            if truncated:
                return ReachabilityResult.unresolved(
                    reason=(
                        "bounded reachability branch budget exhausted before "
                        "all configured RNG samples were evaluated"
                    ),
                    coverage=_sampled_coverage(
                        fingerprint=fingerprint,
                        transitions_covered=transitions_covered,
                        outcomes_examined=outcomes_examined,
                        sequential_context_complete=False,
                    ),
                )

        if not next_paths:
            return ReachabilityResult.unresolved(
                reason=(
                    f"configured bounded RNG samples produced no mechanics "
                    f"witness at transition {step_index + 1}"
                ),
                coverage=_sampled_coverage(
                    fingerprint=fingerprint,
                    transitions_covered=transitions_covered,
                    outcomes_examined=outcomes_examined,
                    sequential_context_complete=final_step,
                ),
            )
        paths = next_paths

    raise AssertionError("reachability sequence ended without a typed result")
