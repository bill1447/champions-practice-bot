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


def _positive_mechanics_match(
    state: dict[str, Any],
    projected: dict[str, Any],
    *,
    current_view: dict[str, Any],
    ledger: PublicConstraintLedger,
    legal_live: tuple[str, ...],
    hypothetical_legal: list[str],
) -> bool:
    """Require positive present-mechanics evidence, not fabricated history.

    The native projection's historical protocol fields necessarily differ
    from the actual game. They are not copied over or used as authority.
    Instead validate the entire own request/team, field, side conditions,
    and native opponent active HP/boost/status; positive static move coverage
    is separately checked against approved prior sets.
    """
    if (
        state.get("turn") != ledger.current_turn
        or projected.get("turn") != ledger.current_turn
        or projected.get("phase") != current_view.get("phase")
        or _canonical(projected.get("request")) != ledger.own_request
        or _canonical(projected.get("player")) != _canonical(current_view.get("player"))
        or _canonical(projected.get("field")) != _canonical(current_view.get("field"))
        or _canonical(projected.get("opponent", {}).get("side_conditions"))
        != _canonical(current_view.get("opponent", {}).get("side_conditions"))
        or (legal_live and set(hypothetical_legal) != set(legal_live))
    ):
        return False

    try:
        opponent = state["sides"][0]["pokemon"]
        active = current_view["opponent"]["active"]
        if len(active) != 2:
            return False
        for slot, observed in enumerate(active):
            native = opponent[slot]
            if not observed or not native or not native["isActive"]:
                return False
            if (
                _sid(native["set"]["species"]) != _sid(observed["base_species"])
                or bool(native["fainted"]) != bool(observed["fainted"])
                or (native["status"] or None) != observed["status"]
                or native["boosts"] != observed["boosts"]
            ):
                return False
            hp = native["hp"]
            maxhp = native["maxhp"]
            bucket = 0 if hp <= 0 else (100 * hp // maxhp or 1)
            if bucket != observed["hp_percent"]:
                return False

        for observed in current_view["opponent"]["revealed"]:
            if not observed["fainted"]:
                continue
            selected = [
                member for member in opponent
                if _sid(member["set"]["species"]) == _sid(observed["species"])
            ]
            if selected and any(not member["fainted"] for member in selected):
                return False
    except (KeyError, IndexError, TypeError, ZeroDivisionError):
        return False
    return True


@dataclass(frozen=True)
class PresentRebaseReport:
    particles: tuple[BeliefParticle, ...]
    roots_tried: int
    native_candidates: int
    positive_matches: int
    unresolved_reason: str | None
    historical_witnesses: int = 0
    exhaustively_excluded_worlds: int = 0


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
            unresolved = report.get("reason") or unresolved
            for hypothesis in report["outcomes"]:
                native += 1
                state = hypothesis["state"]
                if not _matches_approved_prior(state, proposal):
                    continue
                projected = worker.state_view(
                    state=state, side="p2", previews=previews,
                )
                commands = worker.legal_choices(state=state, side="p2")
                if not _positive_mechanics_match(
                    state, projected, current_view=current_view,
                    ledger=ledger, legal_live=legal_live,
                    hypothetical_legal=commands,
                ):
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
        except (RuntimeError, ValueError, KeyError):
            # A failed fresh proposal is unresolved, NOT negative world proof.
            unresolved = "native-proposal-unresolved"
            continue
    return PresentRebaseReport(
        particles=tuple(found),
        roots_tried=roots,
        native_candidates=native,
        positive_matches=len(found),
        unresolved_reason=None if found else unresolved or "bounded-public-constructor-unresolved",
    )
