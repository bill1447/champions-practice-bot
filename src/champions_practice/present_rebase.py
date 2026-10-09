"""Bounded native present-state hypotheses from public evidence (PR #196).

No hidden live session, old particle, opponent command, or oracle state enters
this operation. Static hypotheses come from approved public priors; pinned
Showdown constructs every current-turn state on a *fresh native Battle*.
A projection-compatible candidate is a possible present world, not proof of
any historical RNG sequence, and never excludes unrepresented worlds.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Protocol

from champions_practice.belief_worlds import PublicSetPriorCatalog, preview_choice_for_world
from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.current_state_proposals import (
    _require_current_public_input,
    build_current_state_set_proposals,
)
from champions_practice.current_state_reconstruction import _matches_approved_prior
from champions_practice.observation_beliefs import (
    BeliefParticle,
    identity_member_lineage,
)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sid(value: object) -> str:
    return "".join(c for c in str(value or "").lower() if c.isalnum())


def _first_public_difference(actual: Any, expected: Any, path: str) -> str | None:
    """First structural mismatch path only; never report private values.

    Both arguments are either native hypothetical data or the sanitized public
    observation. A mismatch does not prove the hypothesis mechanically impossible.
    """
    if isinstance(actual, dict) and isinstance(expected, dict):
        for key in sorted(actual.keys() | expected.keys()):
            child = f"{path}.{key}"
            if key not in actual or key not in expected:
                return child
            difference = _first_public_difference(actual[key], expected[key], child)
            if difference is not None:
                return difference
        return None
    if isinstance(actual, (list, tuple)) and isinstance(expected, (list, tuple)):
        for i, (left, right) in enumerate(zip(actual, expected)):
            difference = _first_public_difference(left, right, f"{path}[{i}]")
            if difference is not None:
                return difference
        if len(actual) != len(expected):
            return f"{path}.length"
        return None
    return None if actual == expected else path


def _positive_mechanics_rejection(
    state: dict[str, Any],
    projected: dict[str, Any],
    *,
    current_view: dict[str, Any],
    ledger: PublicConstraintLedger,
    legal_live: tuple[str, ...],
    hypothetical_legal: list[str],
) -> str | None:
    """Require positive current-state evidence with a precise rejection path.

    The pinned Showdown serializer keeps active Pokemon in the first roster
    slots, including after switches (sim/battle-actions.ts and sim/state.ts).
    Do NOT index the original team order or relax active-slot validation.
    """
    checks = (
        ("$.state.turn", state.get("turn"), ledger.current_turn),
        ("$.projection.turn", projected.get("turn"), ledger.current_turn),
        ("$.projection.phase", projected.get("phase"), current_view.get("phase")),
        ("$.request", projected.get("request"), current_view.get("request")),
        ("$.player", projected.get("player"), current_view.get("player")),
        ("$.field", projected.get("field"), current_view.get("field")),
        (
            "$.opponent.side_conditions",
            projected.get("opponent", {}).get("side_conditions"),
            current_view.get("opponent", {}).get("side_conditions"),
        ),
    )
    for path, actual, expected in checks:
        difference = _first_public_difference(actual, expected, path)
        if difference is not None:
            return difference
    if legal_live and set(hypothetical_legal) != set(legal_live):
        return "$.legal_choices"

    try:
        opponent = state["sides"][0]["pokemon"]
        active = current_view["opponent"]["active"]
        if len(active) != 2:
            return "$.opponent.active.length"
        for slot, observed in enumerate(active):
            prefix = f"$.opponent.active[{slot}]"
            native = opponent[slot]
            if not observed or not native or not native["isActive"]:
                return f"{prefix}.native_active"
            if _sid(native["set"]["species"]) != _sid(observed["base_species"]):
                return f"{prefix}.base_species"
            if bool(native["fainted"]) != bool(observed["fainted"]):
                return f"{prefix}.fainted"
            if (native["status"] or None) != observed["status"]:
                return f"{prefix}.status"
            difference = _first_public_difference(
                native["boosts"], observed["boosts"], f"{prefix}.boosts",
            )
            if difference is not None:
                return difference
            hp = native["hp"]
            maxhp = native["maxhp"]
            bucket = 0 if hp <= 0 else (100 * hp // maxhp or 1)
            if bucket != observed["hp_percent"]:
                return f"{prefix}.hp_percent"

        for observed in current_view["opponent"]["revealed"]:
            if not observed["fainted"]:
                continue
            selected = [
                member for member in opponent
                if _sid(member["set"]["species"]) == _sid(observed["species"])
            ]
            if selected and any(not member["fainted"] for member in selected):
                return "$.opponent.revealed.fainted"
    except (KeyError, IndexError, TypeError, ZeroDivisionError, AttributeError):
        return "$.state.invalid-native-structure"
    return None


def _positive_mechanics_match(
    state: dict[str, Any],
    projected: dict[str, Any],
    *,
    current_view: dict[str, Any],
    ledger: PublicConstraintLedger,
    legal_live: tuple[str, ...],
    hypothetical_legal: list[str],
) -> bool:
    """Compatibility predicate for native-state admission and existing tests."""
    return _positive_mechanics_rejection(
        state, projected, current_view=current_view, ledger=ledger,
        legal_live=legal_live, hypothetical_legal=hypothetical_legal,
    ) is None


@dataclass(frozen=True)
class PresentRebaseReport:
    particles: tuple[BeliefParticle, ...]
    roots_tried: int
    native_candidates: int
    positive_matches: int
    unresolved_reason: str | None
    historical_witnesses: int = 0
    exhaustively_excluded_worlds: int = 0
    # Bounded per-proposal rejection reasons; no hidden truth or private values.
    rejection_reasons: tuple[tuple[str, int], ...] = ()


class PresentHypothesisWorker(Protocol):
    def create_state(self, **kwargs: Any) -> dict[str, Any]: ...

    def materialize_present_hypotheses(
        self, *, state: dict[str, Any],
        current_view: dict[str, Any], limit: int,
    ) -> dict[str, Any]: ...

    def state_view(
        self, *, state: dict[str, Any], side: str,
        previews: dict[str, list[str]],
    ) -> dict[str, Any]: ...

    def legal_choices(
        self, *, state: dict[str, Any], side: str,
    ) -> list[str]: ...


def build_present_rebase(
    worker: PresentHypothesisWorker,
    *, ledger: PublicConstraintLedger,
    current_view: dict[str, Any],
    priors: PublicSetPriorCatalog,
    battle_format: str,
    ai_team: str,
    ai_preview_choice: str,
    legal_live: tuple[str, ...] = (),
    max_roots: int = 2,
    max_particles: int = 4,
) -> PresentRebaseReport:
    """Construct positive midgame world hypotheses without replaying history."""
    if (
        isinstance(max_roots, bool) or not 1 <= max_roots <= 4
        or isinstance(max_particles, bool) or not 1 <= max_particles <= 8
    ):
        raise ValueError("present rebase requires bounded roots and particles")
    _require_current_public_input(ledger, current_view)
    if (
        current_view["turn"] < 2
        or current_view["phase"] != "move"
        or not isinstance(ai_preview_choice, str)
        or not ai_preview_choice.startswith("team ")
    ):
        return PresentRebaseReport((), 0, 0, 0, "unsupported-public-phase")

    batch = build_current_state_set_proposals(
        ledger=ledger, current_view=current_view,
        priors=priors, limit=max_roots,
    )
    if not batch.proposals:
        return PresentRebaseReport(
            (), 0, 0, 0, batch.missing_prior or "no-public-set-proposal"
        )

    previews = {
        "p1": list(ledger.preview_species),
        "p2": [m["species"] for m in current_view["player"]["team"]],
    }
    belief = build_public_opponent_belief(current_view)
    found: list[BeliefParticle] = []
    roots = native = 0
    unresolved: str | None = None
    rejected: Counter[str] = Counter()
    for proposal in batch.proposals[:max_roots]:
        if len(found) >= max_particles:
            break
        # Deterministic hypothetical PRNG label, independent of hidden truth.
        digest = hashlib.sha256(
            (ledger.current_signature + proposal.proposal_id).encode()
        ).hexdigest()[:32]
        seed = "sodium," + digest
        try:
            p1_preview = preview_choice_for_world(belief, proposal.world)
            opening = worker.create_state(
                battle_format=battle_format,
                p1_team=proposal.team_text, p2_team=ai_team,
                p1_preview=p1_preview, p2_preview=ai_preview_choice,
                p1_name=current_view["opponent"]["name"],
                p2_name=current_view["player"]["name"],
                seed=seed,
            )
            roots += 1
            report = worker.materialize_present_hypotheses(
                state=opening, current_view=current_view,
                limit=min(4, max_particles - len(found)),
            )
            if not report["outcomes"]:
                reason = report.get("reason") or "native-produced-no-outcomes"
                path = report.get("mismatch_path")
                if isinstance(path, str) and path.startswith("$."):
                    reason += ":" + path[:120]
                rejected[reason] += 1
                unresolved = reason
            for hypothesis in report["outcomes"]:
                native += 1
                state = hypothesis["state"]
                if not _matches_approved_prior(state, proposal):
                    rejected["positive-prior-set-mismatch"] += 1
                    continue
                projected = worker.state_view(
                    state=state, side="p2", previews=previews,
                )
                commands = worker.legal_choices(state=state, side="p2")
                mismatch = _positive_mechanics_rejection(
                    state, projected, current_view=current_view,
                    ledger=ledger, legal_live=legal_live,
                    hypothetical_legal=commands,
                )
                if mismatch is not None:
                    rejected["positive-current-mismatch:" + mismatch] += 1
                    continue
                found.append(BeliefParticle(
                    state=state,
                    weight=proposal.weight,
                    world_id=proposal.proposal_id,
                    history_id="native-present-hypothesis",
                    p1_member_lineage=identity_member_lineage(state, "p1"),
                    p2_member_lineage=identity_member_lineage(state, "p2"),
                ))
                if len(found) >= max_particles:
                    break
        except (RuntimeError, ValueError, KeyError) as error:
            # A failed fresh proposal is unresolved, NOT negative world proof.
            unresolved = "native-proposal-error:" + type(error).__name__
            rejected[unresolved] += 1
            continue
    reasons = tuple(sorted(rejected.items(), key=lambda item: (-item[1], item[0])))
    # When all outcomes are rejected, report WHY rather than falsely claiming
    # that all public-current possibilities have been exhausted.
    if not found and reasons:
        unresolved = reasons[0][0]
    return PresentRebaseReport(
        particles=tuple(found),
        roots_tried=roots,
        native_candidates=native,
        positive_matches=len(found),
        unresolved_reason=None if found else unresolved or "bounded-public-constructor-unresolved",
        rejection_reasons=reasons,
    )
