"""Isolated midgame HP reconstruction from pinned Showdown current-turn scaffolds.

PR #184 is a *positive-only reconstruction experiment*, not a general
current-state rebase. A scaffold must already be a Showdown-produced same-turn
world matching every authoritative public field and the exact choosing request.
It is NOT synthesized from scratch and MUST NOT come from a live hidden session.
The native constructor varies only opponent exact HP within the pinned shared
HP bucket while preserving the full mechanics state: PP, choice locks, active
turns, volatiles, effects, items, timers, party identity and protocol history.

An interval-compatible HP successor is a public-compatible hypothesis, NOT
proof of reachable historical damage. Thus results are irrevocably
non-admissible to live tactical search until later independent validation.
"""

from __future__ import annotations

import copy
import json
import math
from collections import Counter
from dataclasses import dataclass
from typing import Any, Protocol

from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.current_state_proposals import (
    CurrentStateProposalBatch,
    _require_current_public_input,
)
from champions_practice.observation_beliefs import public_observation_signature


def _stable_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class CurrentTurnScaffold:
    """Non-live Showdown-produced state tagged by an approved prior proposal."""

    proposal_id: str
    state: dict[str, Any]


@dataclass(frozen=True)
class CurrentHpReconstruction:
    """A native-pinned HP-only candidate, never a live belief particle."""

    proposal_id: str
    slot: int
    hp: int
    maxhp: int
    state: dict[str, Any]
    exact_request_equal: bool
    public_projection_equal: bool
    native_state_delta_hp_only: bool
    live_admission_authorized: bool = False


@dataclass(frozen=True)
class CurrentHpReconstructionReport:
    candidates: tuple[CurrentHpReconstruction, ...]
    examined_scaffolds: int
    rejected_scaffolds: int
    native_hypotheses: int
    projection_rejections: int
    mechanics_scope: str = "native-exact-hp-only"
    live_admission_authorized: bool = False


class CurrentHpWorker(Protocol):
    def state_view(
        self, *, state: dict[str, Any], side: str,
        previews: dict[str, list[str]],
    ) -> dict[str, Any]: ...

    def materialize_current_hp_hypotheses(
        self, *, state: dict[str, Any],
        public_hp_buckets: tuple[int | None, int | None], limit: int,
    ) -> dict[str, Any]: ...


def _buckets(view: dict[str, Any]) -> tuple[int | None, int | None]:
    result: list[int | None] = []
    for entry in view["opponent"]["active"]:
        if entry is None:
            result.append(None)
            continue
        hp = entry["hp_percent"]
        if (
            isinstance(hp, bool)
            or not isinstance(hp, (int, float))
            or not math.isfinite(hp)
            or hp < 0
            or hp > 100
        ):
            raise ValueError("noncanonical public opponent HP")
        result.append(0 if hp == 0 else max(1, math.floor(hp)))
    if len(result) != 2:
        raise ValueError("expected two public opponent active slots")
    return result[0], result[1]


def _id(value: object) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _set_signature(
    species: object, item: object, ability: object, nature: object,
    moves: object, evs: object,
) -> tuple | None:
    if not isinstance(moves, (list, tuple)) or not isinstance(evs, dict):
        return None
    if any(isinstance(value, bool) or not isinstance(value, int) for value in evs.values()):
        return None
    return (
        _id(species), _id(item), _id(ability), _id(nature),
        tuple(sorted(_id(move) for move in moves)),
        tuple(sorted((_id(stat), points) for stat, points in evs.items() if points)),
    )


def _matches_approved_prior(state: dict, proposal: object) -> bool:
    """Check native stored opening sets; no unlabelled scaffold impersonation."""
    try:
        members = state["sides"][0]["pokemon"]
        expected = proposal.world.sets
    except (KeyError, IndexError, TypeError, AttributeError):
        return False
    if not isinstance(members, list) or len(members) != len(expected):
        return False
    actual = Counter()
    for member in members:
        if not isinstance(member, dict):
            return False
        initial = member.get("set")
        if not isinstance(initial, dict):
            return False
        sig = _set_signature(
            initial.get("species"), initial.get("item"), initial.get("ability"),
            initial.get("nature"), initial.get("moves"), initial.get("evs"),
        )
        if sig is None:
            return False
        actual[sig] += 1
    desired = Counter()
    for candidate in expected:
        sig = _set_signature(
            candidate.species, candidate.item, candidate.ability,
            candidate.nature, candidate.moves, dict(candidate.stat_points),
        )
        if sig is None:
            return False
        desired[sig] += 1
    return actual == desired


def _native_hp_only_change(original: dict, candidate: dict) -> bool:
    """Fail closed on any hidden/internal mutation except one p1 HP integer.

    Full Showdown serialization may include many mechanics-relevant fields.
    A candidate cannot change any of those to make public projection fit.
    """
    left = copy.deepcopy(original)
    right = copy.deepcopy(candidate)
    try:
        before = left["sides"][0]["pokemon"]
        after = right["sides"][0]["pokemon"]
    except (KeyError, IndexError, TypeError):
        return False
    if len(before) != len(after):
        return False
    differences = 0
    for before_member, after_member in zip(before, after, strict=True):
        if not isinstance(before_member, dict) or not isinstance(after_member, dict):
            return False
        left_hp = before_member.get("hp")
        right_hp = after_member.get("hp")
        if left_hp != right_hp:
            differences += 1
            if (
                isinstance(left_hp, bool) or not isinstance(left_hp, int)
                or isinstance(right_hp, bool) or not isinstance(right_hp, int)
                or not 1 <= right_hp <= int(after_member.get("maxhp", 0))
            ):
                return False
            after_member["hp"] = left_hp
    return differences == 1 and _stable_json(left) == _stable_json(right)


def reconstruct_current_hp_hypotheses(
    worker: CurrentHpWorker,
    *,
    ledger: PublicConstraintLedger,
    current_view: dict[str, Any],
    prior_batch: CurrentStateProposalBatch,
    scaffolds: tuple[CurrentTurnScaffold, ...],
    max_scaffolds: int = 4,
    max_hypotheses_per_scaffold: int = 4,
) -> CurrentHpReconstructionReport:
    """Propose concrete same-turn native HP states from full public-matched scaffolds.

    This *does not create the first scaffold* and therefore cannot resolve the
    original missing-ancestry collapse on its own. Every candidate must:
    - come from an approved prior proposal and a Showdown-produced scaffold;
    - start and end with current-turn exact own request and full public view;
    - differ from its scaffold in exactly one native opponent Pokemon.hp;
    - round-trip through Showdown's own Battle serializer (worker-enforced).
    All failure/absence is unresolved, never exclusion evidence.
    """
    for label, value in (
        ("max_scaffolds", max_scaffolds),
        ("max_hypotheses_per_scaffold", max_hypotheses_per_scaffold),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 8:
            raise ValueError(f"{label} must be between 1 and 8")

    _require_current_public_input(ledger, current_view)
    if (
        prior_batch.source_turn != ledger.current_turn
        or prior_batch.source_signature != ledger.current_signature
    ):
        raise ValueError("current HP reconstruction received stale prior batch")
    approved_proposals = {
        candidate.proposal_id: candidate for candidate in prior_batch.proposals
    }
    previews = {
        "p1": list(ledger.preview_species),
        "p2": [member["species"] for member in current_view["player"]["team"]],
    }
    buckets = _buckets(current_view)
    examined = rejected = native_count = projection_rejected = 0
    accepted: list[CurrentHpReconstruction] = []

    for scaffold in scaffolds[:max_scaffolds]:
        examined += 1
        approved = approved_proposals.get(scaffold.proposal_id)
        if approved is None or not _matches_approved_prior(scaffold.state, approved):
            rejected += 1
            continue
        # Full Showdown-projection and exact request are *preconditions*.
        # Never graft a mismatched old state into a current matching world.
        parent_view = worker.state_view(
            state=scaffold.state, side="p2", previews=previews
        )
        if (
            parent_view.get("turn") != ledger.current_turn
            or _stable_json(parent_view.get("request")) != ledger.own_request
            or public_observation_signature(parent_view) != ledger.current_signature
        ):
            rejected += 1
            continue

        result = worker.materialize_current_hp_hypotheses(
            state=scaffold.state,
            public_hp_buckets=buckets,
            limit=max_hypotheses_per_scaffold,
        )
        native = result["outcomes"]
        native_count += len(native)
        for row in native:
            state = row["state"]
            hp_only = _native_hp_only_change(scaffold.state, state)
            if not hp_only:
                projection_rejected += 1
                continue
            view = worker.state_view(state=state, side="p2", previews=previews)
            own_equal = _stable_json(view.get("request")) == ledger.own_request
            public_equal = public_observation_signature(view) == ledger.current_signature
            if (
                view.get("turn") != ledger.current_turn
                or not own_equal
                or not public_equal
            ):
                projection_rejected += 1
                continue
            accepted.append(CurrentHpReconstruction(
                proposal_id=scaffold.proposal_id,
                slot=row["slot"],
                hp=row["hp"],
                maxhp=row["maxhp"],
                state=state,
                exact_request_equal=own_equal,
                public_projection_equal=public_equal,
                native_state_delta_hp_only=hp_only,
            ))
    return CurrentHpReconstructionReport(
        candidates=tuple(accepted),
        examined_scaffolds=examined,
        rejected_scaffolds=rejected,
        native_hypotheses=native_count,
        projection_rejections=projection_rejected,
    )
