"""Isolated, public-only seeds for current-state rebase (no live admission).

This is a deliberately narrow *proposal and projection* gate. Approved set
priors produce fresh Showdown opening hypotheses with no historical particle
ancestry. Such openings are not present-turn materializations after turn one.
A projection match is necessary, never sufficient, to grant live authority:
the generator cannot prove historical constraints, persistent timers, PP,
locks, move history, or turn-local stochastic reachability.

Only an independently validated future midgame constructor can turn these
static hypotheses into concrete *current-turn* state proposals. Never patch
serialized battle state to force a public view to match.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.belief_worlds import (
    MissingPublicSetPrior,
    PublicBeliefWorld,
    PublicSetCandidate,
    PublicSetPriorCatalog,
    materialize_public_belief_worlds,
    preview_choice_for_world,
)
from champions_practice.current_state_constraints import (
    PublicConstraintLedger,
)
from champions_practice.observation_beliefs import public_observation_signature


def _stable_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _species_id(value: str) -> str:
    return "".join(letter for letter in value.lower() if letter.isalnum())


class RebaseProposalStatus(str, Enum):
    PROJECTION_MATCH = "projection_match"
    OWN_REQUEST_MISMATCH = "own_request_mismatch"
    PUBLIC_PROJECTION_MISMATCH = "public_projection_mismatch"
    NOT_CURRENT_STATE = "not_current_state"


@dataclass(frozen=True)
class CurrentStateSetProposal:
    """Static prior hypothesis; NOT a reconstructed Showdown battle state."""

    proposal_id: str
    world: PublicBeliefWorld
    weight: float
    selected_species: tuple[str, ...]

    @property
    def team_text(self) -> str:
        return self.world.team_text


@dataclass(frozen=True)
class CurrentStateProposalBatch:
    """Finite public-prior proposals; not an exhaustive hypothesis space."""

    proposals: tuple[CurrentStateSetProposal, ...]
    source_turn: int
    candidates_considered: int
    rejected_missing_public_moves: int
    missing_prior: str | None = None
    live_admission_authorized: bool = False


@dataclass(frozen=True)
class CurrentStateProjectionProbe:
    """Producer projection evidence without negative or live-admission authority."""

    proposal_id: str
    status: RebaseProposalStatus
    public_projection_equal: bool
    own_request_equal: bool
    # The state is returned only on exact local projection agreement. No
    # caller may treat it as a validated historical/current-turn belief.
    matching_opening_state: dict[str, Any] | None = None
    live_admission_authorized: bool = False


class FreshPriorWorker(Protocol):
    def create_state(
        self, *, battle_format: str, p1_team: str, p2_team: str,
        p1_preview: str, p2_preview: str,
        p1_name: str, p2_name: str, seed: str,
    ) -> dict[str, Any]: ...

    def state_view(
        self, *, state: dict[str, Any], side: str,
        previews: dict[str, list[str]],
    ) -> dict[str, Any]: ...


def _require_current_public_input(
    ledger: PublicConstraintLedger, current_view: dict[str, Any]
) -> None:
    # Reuses the trusted #182 schema and own request gate. Never trust a caller's
    # claim that current_view was derived from this exact ledger checkpoint.
    if not ledger.matches_current_public_projection(current_view):
        raise ValueError("current public view disagrees with constraint ledger")
    if ledger.current_turn != current_view["turn"]:
        raise ValueError("constraint ledger turn disagrees with public view")


def build_current_state_set_proposals(
    *, ledger: PublicConstraintLedger,
    current_view: dict[str, Any],
    priors: PublicSetPriorCatalog,
    limit: int = 8,
) -> CurrentStateProposalBatch:
    """Build diversity-preserving static team proposals using only public evidence.

    Prior item and ability values are *not* filtered from observed public
    activations: Trick, ability changes and consumptions make those observations
    unsafe as proof of the initial set. Move coverage is a proposal criterion,
    NOT an exhaustive impossibility conclusion (moves can change in battle).
    Missing coverage is explicitly reported rather than excluding hidden truth.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("proposal limit must be a positive integer")
    _require_current_public_input(ledger, current_view)

    cleaned = copy.deepcopy(current_view)
    observed = cleaned["opponent"]["revealed"]
    # Only known moves are used for static prior eligibility; initial item
    # and ability must remain uncertain across ordinary exchange mechanics.
    known_by_species = {
        _species_id(entry.species): entry for entry in ledger.known_sets
    }
    for entry in observed:
        known = known_by_species.get(_species_id(entry["species"]))
        if known is None:
            raise ValueError("public species is not represented in ledger")
        entry["moves"] = list(known.moves)
        entry["items"] = []
        entry["abilities"] = []

    # Broadened evidence can leave all catalog priors without move coverage.
    # This means "unsupported prior", never "mechanically impossible".
    belief = build_public_opponent_belief(cleaned)
    try:
        worlds = materialize_public_belief_worlds(belief, priors, limit=limit)
    except MissingPublicSetPrior as error:
        return CurrentStateProposalBatch(
            proposals=(), source_turn=ledger.current_turn,
            candidates_considered=0, rejected_missing_public_moves=0,
            missing_prior=str(error),
        )

    proposals: list[CurrentStateSetProposal] = []
    for world in worlds:
        fingerprint = hashlib.sha256(_stable_json({
            "selected": world.selected_species,
            "team": world.team_text,
            "ledger": ledger.current_signature,
        }).encode()).hexdigest()[:24]
        proposals.append(CurrentStateSetProposal(
            proposal_id=f"public-prior:{fingerprint}",
            world=world,
            weight=world.weight,
            selected_species=world.selected_species,
        ))
    return CurrentStateProposalBatch(
        proposals=tuple(proposals), source_turn=ledger.current_turn,
        candidates_considered=len(worlds),
        rejected_missing_public_moves=0,
    )


def probe_fresh_prior_projections(
    worker: FreshPriorWorker,
    *,
    ledger: PublicConstraintLedger,
    current_view: dict[str, Any],
    proposals: CurrentStateProposalBatch,
    battle_format: str,
    ai_team: str,
    ai_preview_choice: str,
    seed: str,
    max_probes: int = 8,
) -> tuple[CurrentStateProjectionProbe, ...]:
    """Check both producer projections on fresh pinned-Showdown prior roots.

    This is NOT a midgame constructor. An opening root cannot be silently
    relabeled as a later-turn state, even when some public fields happen to
    look identical. A worker exception is propagated, not interpreted as an
    opponent world being impossible.
    """
    if isinstance(max_probes, bool) or not isinstance(max_probes, int) or max_probes < 1:
        raise ValueError("max_probes must be a positive integer")
    _require_current_public_input(ledger, current_view)
    if proposals.source_turn != ledger.current_turn:
        raise ValueError("proposal batch is stale for current turn")
    if not isinstance(seed, str) or not seed:
        raise ValueError("explicit hypothetical RNG seed is required")
    if not all(isinstance(item, str) and item for item in
               (battle_format, ai_team, ai_preview_choice)):
        raise ValueError("fresh prior opening requires format, team, and preview")

    public_belief = build_public_opponent_belief(current_view)
    previews = {
        "p1": list(ledger.preview_species),
        "p2": [item["species"] for item in current_view["player"]["team"]],
    }
    wanted = ledger.current_signature
    results: list[CurrentStateProjectionProbe] = []
    for proposal in proposals.proposals[:max_probes]:
        opponent_preview = preview_choice_for_world(public_belief, proposal.world)
        state = worker.create_state(
            battle_format=battle_format,
            p1_team=proposal.team_text,
            p2_team=ai_team,
            p1_preview=opponent_preview,
            p2_preview=ai_preview_choice,
            p1_name=current_view["opponent"]["name"],
            p2_name=current_view["player"]["name"],
            seed=seed,
        )
        projection = worker.state_view(
            state=state, side="p2", previews=previews,
        )
        request_equal = _stable_json(projection["request"]) == ledger.own_request
        public_equal = public_observation_signature(projection) == wanted

        # Root instantiation cannot establish persistent state after turn one.
        if current_view["turn"] != 1 or projection["turn"] != current_view["turn"]:
            status = RebaseProposalStatus.NOT_CURRENT_STATE
        elif not request_equal:
            status = RebaseProposalStatus.OWN_REQUEST_MISMATCH
        elif not public_equal:
            status = RebaseProposalStatus.PUBLIC_PROJECTION_MISMATCH
        else:
            status = RebaseProposalStatus.PROJECTION_MATCH

        results.append(CurrentStateProjectionProbe(
            proposal_id=proposal.proposal_id,
            status=status,
            public_projection_equal=public_equal,
            own_request_equal=request_equal,
            matching_opening_state=(
                state if status is RebaseProposalStatus.PROJECTION_MATCH else None
            ),
        ))
    return tuple(results)
