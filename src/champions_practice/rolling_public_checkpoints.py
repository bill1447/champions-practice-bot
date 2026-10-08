"""Isolated rolling current-turn public checkpoints, without replay backlog.

#186 advances *already independently public-validated* hypothetical Showdown
states one observed turn. It does not replay from preview for every new turn:
the previous turn's public checkpoint is the local frontier. A certificate
checks approved prior sets, complete previous public projection and exact
choosing request; each new child undergoes the same checks.

This is an isolated positive-witness facility, not permission to accept,
exclude or reweight live particles. If a public checkpoint was not retained
before a historical collapse, this API cannot conjure it from later public
evidence. Neither a hidden session nor old belief ancestry is an input.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.current_state_proposals import (
    CurrentStateProposalBatch,
    _require_current_public_input,
)
from champions_practice.current_state_reconstruction import _matches_approved_prior
from champions_practice.observation_beliefs import (
    filter_choices_by_public_actions,
    public_observation_signature,
    public_opponent_actions_fully_observed,
)
from champions_practice.public_scaffold_bootstrap import PublicScaffoldWitness


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True)
class PublicRebaseCheckpoint:
    """Native hypothetical state with bounded public evidence provenance.

    A certificate is a process-local diagnostic, not cryptographic proof and
    explicitly not a substitute for independent mechanics validation.
    """

    proposal_id: str
    turn: int
    signature: str
    state: dict[str, Any]
    depth: int = 1
    live_admission_authorized: bool = False


@dataclass(frozen=True)
class PublicCheckpointAdvanceReport:
    checkpoints: tuple[PublicRebaseCheckpoint, ...]
    input_checkpoints: int
    validated_parents: int
    rejected_parents: int
    simulated_branches: int
    projection_mismatches: int
    unresolved_reason: str | None
    exhaustive_disproofs: int = 0
    live_admission_authorized: bool = False


class RollingPublicWorker(Protocol):
    def state_view(
        self, *, state: dict[str, Any], side: str,
        previews: dict[str, list[str]],
    ) -> dict[str, Any]: ...

    def legal_choices(self, *, state: dict[str, Any], side: str) -> list[str]: ...

    def branch_many(
        self, *, state: dict[str, Any], branches: list[dict[str, Any]]
    ) -> list[dict[str, Any]]: ...


def _previews(ledger: PublicConstraintLedger, view: dict[str, Any]) -> dict:
    return {
        "p1": list(ledger.preview_species),
        "p2": [member["species"] for member in view["player"]["team"]],
    }


def _valid_checkpoint_state(
    worker: RollingPublicWorker,
    *,
    state: dict[str, Any],
    proposal: object,
    ledger: PublicConstraintLedger,
    view: dict[str, Any],
) -> bool:
    """Independently check static prior identity and native full projection."""
    if not isinstance(state, dict) or not _matches_approved_prior(state, proposal):
        return False
    observed = worker.state_view(state=state, side="p2", previews=_previews(ledger, view))
    return (
        observed.get("turn") == ledger.current_turn
        and _canonical(observed.get("request")) == ledger.own_request
        and public_observation_signature(observed) == ledger.current_signature
    )


def validate_public_bootstrap_checkpoint(
    worker: RollingPublicWorker,
    *,
    witness: PublicScaffoldWitness,
    ledger: PublicConstraintLedger,
    current_view: dict[str, Any],
    prior_batch: CurrentStateProposalBatch,
) -> PublicRebaseCheckpoint | None:
    """Verify one #185 first-scaffold witness before using it as a frontier.

    A caller cannot pass a matching request/public JSON while lying about the
    approved hidden starting team. Failure returns no checkpoint, never a
    disproof of the opponent world.
    """
    _require_current_public_input(ledger, current_view)
    if (
        prior_batch.source_turn != ledger.current_turn
        or prior_batch.source_signature != ledger.current_signature
    ):
        raise ValueError("stale public prior batch")
    if witness.live_admission_authorized:
        raise ValueError("unexpected live authority in isolated witness")
    proposal = next(
        (p for p in prior_batch.proposals if p.proposal_id == witness.proposal_id),
        None,
    )
    if proposal is None or not _valid_checkpoint_state(
        worker,
        state=witness.state,
        proposal=proposal,
        ledger=ledger,
        view=current_view,
    ):
        return None
    return PublicRebaseCheckpoint(
        proposal_id=witness.proposal_id,
        turn=ledger.current_turn,
        signature=ledger.current_signature,
        state=witness.state,
    )


def advance_rolling_public_checkpoints(
    worker: RollingPublicWorker,
    *,
    previous_view: dict[str, Any],
    current_view: dict[str, Any],
    previous_ledger: PublicConstraintLedger,
    current_ledger: PublicConstraintLedger,
    previous_prior_batch: CurrentStateProposalBatch,
    prior_batch: CurrentStateProposalBatch,
    checkpoints: tuple[PublicRebaseCheckpoint, ...],
    known_own_choice: str,
    rng_seeds: tuple[str, ...],
    max_checkpoints: int = 4,
    max_opponent_choices: int = 12,
    max_branches: int = 96,
    max_witnesses: int = 8,
) -> PublicCheckpointAdvanceReport:
    """Advance a certified frontier *one* public turn, no opening-history replay.

    Bounded finite RNG probes are positive-only. Incomplete opponent-action
    coverage or absent witnesses is UNRESOLVED, even when all configured probes
    were consumed. Do not pass old sampled belief particles as checkpoints.
    """
    for label, value, ceiling in (
        ("max_checkpoints", max_checkpoints, 16),
        ("max_opponent_choices", max_opponent_choices, 64),
        ("max_branches", max_branches, 512),
        ("max_witnesses", max_witnesses, 32),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= ceiling:
            raise ValueError(f"{label} must be an integer in 1..{ceiling}")
    if (
        not isinstance(rng_seeds, tuple) or not 1 <= len(rng_seeds) <= 16
        or not all(isinstance(seed, str) and seed.startswith("sodium,") for seed in rng_seeds)
    ):
        raise ValueError("rng_seeds must contain one to sixteen hypothetical seeds")
    if not isinstance(known_own_choice, str) or not known_own_choice.strip():
        raise ValueError("known own command must be nonempty")
    _require_current_public_input(previous_ledger, previous_view)
    _require_current_public_input(current_ledger, current_view)
    if (
        prior_batch.source_turn != current_ledger.current_turn
        or prior_batch.source_signature != current_ledger.current_signature
        or previous_prior_batch.source_turn != previous_ledger.current_turn
        or previous_prior_batch.source_signature != previous_ledger.current_signature
    ):
        raise ValueError("stale current or previous public prior batch")

    if (
        current_ledger.current_turn != previous_ledger.current_turn + 1
        or previous_ledger.advance(current_view) != current_ledger
    ):
        return PublicCheckpointAdvanceReport(
            (), len(checkpoints), 0, 0, 0, 0, "unsupported-or-incomplete-ledger-history",
        )

    if not public_opponent_actions_fully_observed(
        current_view, previous_public_view=previous_view,
    ):
        return PublicCheckpointAdvanceReport(
            (), len(checkpoints), 0, 0, 0, 0, "incomplete-public-opponent-actions",
        )

    known_previous = {p.proposal_id: p for p in previous_prior_batch.proposals}
    # #183 IDs are deliberately tied to the exact public snapshot, so map
    # yesterday's certified prior to today's identical team set by its
    # canonical team text. Never silently reuse a stale proposal ID.
    known_current_by_team = {p.team_text: p for p in prior_batch.proposals}
    parents = accepted = rejected = branches = mismatches = 0
    successors: list[PublicRebaseCheckpoint] = []
    previews = _previews(current_ledger, current_view)
    for checkpoint in checkpoints[:max_checkpoints]:
        if branches >= max_branches or len(successors) >= max_witnesses:
            break

        previous_proposal = known_previous.get(checkpoint.proposal_id)
        proposal = (
            known_current_by_team.get(previous_proposal.team_text)
            if previous_proposal is not None else None
        )
        if (
            checkpoint.live_admission_authorized
            or checkpoint.turn != previous_ledger.current_turn
            or checkpoint.signature != previous_ledger.current_signature
            or proposal is None
            or not _valid_checkpoint_state(
                worker, state=checkpoint.state, proposal=previous_proposal,
                ledger=previous_ledger, view=previous_view,
            )
        ):
            rejected += 1
            continue
        parents += 1
        if known_own_choice not in worker.legal_choices(state=checkpoint.state, side="p2"):
            rejected += 1
            continue

        opponent_legal = tuple(worker.legal_choices(state=checkpoint.state, side="p1"))
        compatible = filter_choices_by_public_actions(
            opponent_legal, current_view,
            previous_public_view=previous_view,
            state=checkpoint.state, side="p1", fail_open=False,
        )
        for response in compatible[:max_opponent_choices]:
            if branches >= max_branches or len(successors) >= max_witnesses:
                break
            seeds = rng_seeds[:min(len(rng_seeds), max_branches - branches)]
            requests = [
                {
                    "p1_choice": response,
                    "p2_choice": known_own_choice,
                    "rng_seed": seed,
                    "include_state": True,
                    "view_side": "p2",
                    "previews": previews,
                }
                for seed in seeds
            ]
            results = worker.branch_many(state=checkpoint.state, branches=requests)
            if len(results) != len(requests):
                raise RuntimeError("pinned worker omitted a native branch")
            branches += len(results)
            for row in results:
                state = row.get("state")
                view = row.get("view")
                if not isinstance(state, dict) or not isinstance(view, dict):
                    raise RuntimeError("pinned worker omitted a native state or view")
                if (
                    view.get("turn") != current_ledger.current_turn
                    or _canonical(view.get("request")) != current_ledger.own_request
                    or public_observation_signature(view) != current_ledger.current_signature
                ):
                    mismatches += 1
                    continue
                if not _valid_checkpoint_state(
                    worker, state=state, proposal=proposal,
                    ledger=current_ledger, view=current_view,
                ):
                    raise RuntimeError("pinned state roundtrip violated projection/prior")
                successors.append(PublicRebaseCheckpoint(
                    proposal_id=proposal.proposal_id,
                    turn=current_ledger.current_turn,
                    signature=current_ledger.current_signature,
                    state=state,
                    depth=checkpoint.depth + 1,
                ))
                if len(successors) >= max_witnesses:
                    break

    return PublicCheckpointAdvanceReport(
        checkpoints=tuple(successors),
        input_checkpoints=len(checkpoints),
        validated_parents=parents,
        rejected_parents=rejected,
        simulated_branches=branches,
        projection_mismatches=mismatches,
        unresolved_reason=None if successors else "bounded-rolling-checkpoint-unresolved",
    )
