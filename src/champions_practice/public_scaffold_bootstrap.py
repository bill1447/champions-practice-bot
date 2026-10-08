"""Public-only, bounded first-scaffold bootstrap without historical particles.

PR #185 establishes a *positive* current-turn witness for a narrow covered
domain: exactly one observed turn after a validated post-preview public view.
Every input is public except our own committed action (which is known to us).
Opponent commands are generated from a fresh approved prior's legal choices
and filtered only by the public producer's action evidence. Randomness is a
bounded witness search, never exhaustive disproof.

All states come directly from fresh pinned Showdown roots and native branch
transitions. Neither a live session snapshot nor an earlier particle state
is an input. The outputs are diagnostic candidates, never live admissions.
This does not yet solve deep midgame collapse, where retained public evidence
may not uniquely establish PP, timers, volatile histories, or other state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.belief_worlds import preview_choice_for_world
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.current_state_proposals import (
    CurrentStateProposalBatch,
    _require_current_public_input,
)
from champions_practice.observation_beliefs import (
    filter_choices_by_public_actions,
    public_observation_signature,
    public_opponent_actions_fully_observed,
)


def _exact_json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=True)


@dataclass(frozen=True)
class PublicScaffoldWitness:
    proposal_id: str
    opponent_choice: str
    own_choice: str
    rng_seed: str
    state: dict[str, Any]
    exact_request_equal: bool = True
    public_projection_equal: bool = True
    live_admission_authorized: bool = False


@dataclass(frozen=True)
class PublicScaffoldBootstrapReport:
    witnesses: tuple[PublicScaffoldWitness, ...]
    fresh_roots: int
    simulated_branches: int
    observation_mismatches: int
    unsupported_reason: str | None
    # Truncation/no witness MUST NEVER be consumed as world-exclusion evidence.
    exhaustive_disproofs: int = 0
    live_admission_authorized: bool = False


class PublicScaffoldWorker(Protocol):
    def create_state(
        self, *, battle_format: str, p1_team: str, p2_team: str,
        p1_preview: str, p2_preview: str, p1_name: str, p2_name: str,
        seed: str,
    ) -> dict[str, Any]: ...

    def state_view(
        self, *, state: dict[str, Any], side: str,
        previews: dict[str, list[str]],
    ) -> dict[str, Any]: ...

    def legal_choices(self, *, state: dict[str, Any], side: str) -> list[str]: ...

    def branch_many(
        self, *, state: dict[str, Any],
        branches: list[dict[str, Any]],
    ) -> list[dict[str, Any]]: ...


def bootstrap_public_current_scaffolds(
    worker: PublicScaffoldWorker,
    *,
    opening_view: dict[str, Any],
    current_view: dict[str, Any],
    ledger: PublicConstraintLedger,
    prior_batch: CurrentStateProposalBatch,
    battle_format: str,
    ai_team: str,
    ai_preview_choice: str,
    known_own_choice: str,
    rng_seeds: tuple[str, ...],
    max_roots: int = 4,
    max_opponent_choices: int = 12,
    max_branches: int = 96,
    max_witnesses: int = 4,
) -> PublicScaffoldBootstrapReport:
    """Produce *first* present-turn scaffolds using only independent public data.

    Requires all actions from the single intervening turn to have sufficient
    public coverage, plus our actual submitted choice. No exact opponent
    command, hidden item, prior particle state, or live transport is accepted.
    A fresh state passes only after both opening and current complete
    producer projections and exact own requests agree.

    No-match, incomplete history, truncated search, invalid set prior, and
    unsupported actions are UNRESOLVED, never exhaustive disproofs.
    """
    limits = {
        "max_roots": (max_roots, 16),
        "max_opponent_choices": (max_opponent_choices, 64),
        "max_branches": (max_branches, 512),
        "max_witnesses": (max_witnesses, 32),
    }
    for key, (value, maximum) in limits.items():
        if (
            isinstance(value, bool) or not isinstance(value, int)
            or not 1 <= value <= maximum
        ):
            raise ValueError(f"{key} must be an integer in 1..{maximum}")
    if (
        not isinstance(rng_seeds, tuple) or not 1 <= len(rng_seeds) <= 16
        or not all(isinstance(x, str) and x.startswith("sodium,") for x in rng_seeds)
    ):
        raise ValueError("rng_seeds must be one to sixteen explicit hypothetical seeds")
    if not all(isinstance(x, str) and x.strip() for x in
               (known_own_choice, battle_format, ai_team, ai_preview_choice)):
        raise ValueError("known own action, format, team and preview are required")

    _require_current_public_input(ledger, current_view)
    if (
        prior_batch.source_turn != ledger.current_turn
        or prior_batch.source_signature != ledger.current_signature
    ):
        raise ValueError("stale current-turn prior batch")

    opening = PublicConstraintLedger.from_public_view(opening_view)
    if (
        opening.current_turn != 1 or ledger.current_turn != opening.current_turn + 1
        or ledger != opening.advance(current_view)
    ):
        return PublicScaffoldBootstrapReport(
            (), 0, 0, 0, "unsupported-or-incomplete-one-turn-public-history"
        )
    if not public_opponent_actions_fully_observed(
        current_view, previous_public_view=opening_view
    ):
        return PublicScaffoldBootstrapReport(
            (), 0, 0, 0, "incomplete-public-opponent-actions"
        )

    previews = {
        "p1": list(ledger.preview_species),
        "p2": [mon["species"] for mon in current_view["player"]["team"]],
    }
    if previews["p2"] != [mon["species"] for mon in opening_view["player"]["team"]]:
        return PublicScaffoldBootstrapReport(
            (), 0, 0, 0, "own-preview-roster-mismatch"
        )

    wanted_opening = opening.current_signature
    wanted_current = ledger.current_signature
    preview_belief = build_public_opponent_belief(opening_view)
    roots = branches_tried = mismatches = 0
    witnesses: list[PublicScaffoldWitness] = []
    for proposal in prior_batch.proposals[:max_roots]:
        if branches_tried >= max_branches or len(witnesses) >= max_witnesses:
            break

        p1_preview = preview_choice_for_world(preview_belief, proposal.world)
        root = worker.create_state(
            battle_format=battle_format, p1_team=proposal.team_text,
            p2_team=ai_team, p1_preview=p1_preview,
            p2_preview=ai_preview_choice,
            p1_name=current_view["opponent"]["name"],
            p2_name=current_view["player"]["name"],
            seed=rng_seeds[0],
        )
        roots += 1
        projected_opening = worker.state_view(
            state=root, side="p2", previews=previews,
        )
        if (
            public_observation_signature(projected_opening) != wanted_opening
            or _exact_json(projected_opening.get("request")) != opening.own_request
        ):
            mismatches += 1
            continue

        if known_own_choice not in worker.legal_choices(state=root, side="p2"):
            # An impossible *own* command means this root is unsupported;
            # never count it as an exhaustive rejection of the prior world.
            mismatches += 1
            continue

        legal = tuple(worker.legal_choices(state=root, side="p1"))
        compatible = filter_choices_by_public_actions(
            legal,
            current_view,
            previous_public_view=opening_view,
            state=root,
            side="p1",
            fail_open=False,
        )
        for response in compatible[:max_opponent_choices]:
            if branches_tried >= max_branches or len(witnesses) >= max_witnesses:
                break
            seeds = rng_seeds[:min(len(rng_seeds), max_branches - branches_tried)]
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
            rows = worker.branch_many(state=root, branches=requests)
            if len(rows) != len(requests):
                raise RuntimeError("pinned worker did not return all requested branches")
            branches_tried += len(rows)
            for seed, row in zip(seeds, rows, strict=True):
                state = row.get("state")
                view = row.get("view")
                if not isinstance(state, dict) or not isinstance(view, dict):
                    raise RuntimeError("pinned worker omitted an exact branch state/view")
                request_equal = _exact_json(view.get("request")) == ledger.own_request
                projection_equal = (
                    view.get("turn") == ledger.current_turn
                    and public_observation_signature(view) == wanted_current
                )
                if not (request_equal and projection_equal):
                    mismatches += 1
                    continue
                # Independently round-trip the resulting current state through
                # the pinned worker's serializer before retaining any witness.
                confirmed = worker.state_view(
                    state=state, side="p2", previews=previews,
                )
                if (
                    _exact_json(confirmed.get("request")) != ledger.own_request
                    or public_observation_signature(confirmed) != wanted_current
                ):
                    raise RuntimeError("native state roundtrip changed public authority")
                witnesses.append(PublicScaffoldWitness(
                    proposal_id=proposal.proposal_id,
                    opponent_choice=response,
                    own_choice=known_own_choice,
                    rng_seed=seed,
                    state=state,
                ))
                if len(witnesses) >= max_witnesses:
                    break

    reason = None if witnesses else "bounded-public-witness-search-unresolved"
    return PublicScaffoldBootstrapReport(
        witnesses=tuple(witnesses), fresh_roots=roots,
        simulated_branches=branches_tried, observation_mismatches=mismatches,
        unsupported_reason=reason,
    )
