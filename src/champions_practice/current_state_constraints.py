"""Particle-independent public evidence for future current-turn belief rebasing.

This ledger is *not* a hidden-world validator, a damage calculator, or a live
particle-admission surface. It records only the pinned, sanitized player view.
Observed action order is not by itself a Speed inequality; a sampled damage
result is not an Attack/Defense bound. Those deductions need separate pinned
mechanics proofs before any future rebase may use them as hard constraints.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.observation_beliefs import public_observation_signature
from champions_practice.reachability import public_reachability_observation_issue

PUBLIC_CONSTRAINT_LEDGER_SCHEMA = "public-current-constraint-ledger-v1"
MAX_PUBLIC_EVIDENCE_RECORDS = 512


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _species_id(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


@dataclass(frozen=True)
class KnownPublicSet:
    """Only positively revealed static facts; no negative move/item inference."""

    species: str
    moves: tuple[str, ...] = ()
    items: tuple[str, ...] = ()
    abilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class PublicEvidenceRecord:
    """One exact source-channel fact, with no inferred mechanics authority.

    The payload is canonical JSON of the exact producer field, not a
    hypothetical particle's projection. Repeated retained last-turn deltas
    are recorded once even when the next current view repeats them.
    """

    kind: str
    source_turn: int | None
    payload: str


@dataclass(frozen=True)
class PublicConstraintLedger:
    """Current authoritative snapshot plus immutable historical evidence.

    current_signature includes exact player request/HP, opponent public HP
    buckets, field, side conditions, active slots, fainting, boosts and forms.
    Known moves/items/abilities and turn records survive future snapshots.
    Duplicate preview species are deliberately *not* assigned a unique member
    identity from species alone: the record remains attached to that species
    without claiming which duplicate carries it.

    No hypothesis, opening particle, private side, RNG seed or old posterior
    weight is accepted as an input to this type.
    """

    preview_species: tuple[str, ...]
    current_turn: int
    current_signature: str
    own_request: str
    known_sets: tuple[KnownPublicSet, ...]
    records: tuple[PublicEvidenceRecord, ...] = ()
    schema: str = PUBLIC_CONSTRAINT_LEDGER_SCHEMA

    @classmethod
    def from_public_view(cls, view: dict[str, Any]) -> "PublicConstraintLedger":
        _validate_public_view(view)
        belief = build_public_opponent_belief(view)
        known = tuple(
            KnownPublicSet(
                species=mon.species,
                moves=tuple(sorted(set(mon.revealed_moves))),
                items=tuple(sorted(set(mon.revealed_items))),
                abilities=tuple(sorted(set(mon.revealed_abilities))),
            )
            for mon in belief.pokemon
        )
        return cls(
            preview_species=tuple(view["opponent"]["preview_species"]),
            current_turn=view["turn"],
            current_signature=public_observation_signature(view),
            own_request=_canonical(view["request"]),
            known_sets=known,
            records=_new_records(view, ()),
        )

    def advance(self, view: dict[str, Any]) -> "PublicConstraintLedger":
        _validate_public_view(view)
        if view["turn"] < self.current_turn:
            raise ValueError("public ledger cannot rewind to an earlier turn")
        if tuple(view["opponent"]["preview_species"]) != self.preview_species:
            raise ValueError("public ledger cannot silently change the preview roster")

        belief = build_public_opponent_belief(view)
        if len(belief.pokemon) != len(self.known_sets):
            raise ValueError("public ledger roster identity changed")
        known: list[KnownPublicSet] = []
        for previous, mon in zip(self.known_sets, belief.pokemon, strict=True):
            if _species_id(previous.species) != _species_id(mon.species):
                raise ValueError("public ledger roster identity changed")
            known.append(
                KnownPublicSet(
                    species=previous.species,
                    moves=tuple(sorted(set(previous.moves) | set(mon.revealed_moves))),
                    items=tuple(sorted(set(previous.items) | set(mon.revealed_items))),
                    abilities=tuple(
                        sorted(set(previous.abilities) | set(mon.revealed_abilities))
                    ),
                )
            )
        return PublicConstraintLedger(
            preview_species=self.preview_species,
            current_turn=view["turn"],
            current_signature=public_observation_signature(view),
            own_request=_canonical(view["request"]),
            known_sets=tuple(known),
            records=_new_records(view, self.records),
        )

    def matches_current_public_projection(self, view: dict[str, Any]) -> bool:
        """Necessary comparison, NOT authorization to synthesize/admit a state."""
        _validate_public_view(view)
        return (
            self.current_signature == public_observation_signature(view)
            and self.own_request == _canonical(view["request"])
        )


def _validate_public_view(view: dict[str, Any]) -> None:
    issue = public_reachability_observation_issue(view)
    if issue is not None:
        raise ValueError(f"public constraint ledger rejected non-public view: {issue}")


def _new_records(
    view: dict[str, Any],
    previous: tuple[PublicEvidenceRecord, ...],
) -> tuple[PublicEvidenceRecord, ...]:
    records = list(previous)
    seen = {(record.kind, record.source_turn, record.payload) for record in records}
    # The producer's latest event/execution turn can lag view.turn. A change
    # in current turn must not convert an unchanged historical delta into a
    # fabricated second observation.
    for kind in ("public_event_delta", "public_execution_delta"):
        value = view[kind]
        if kind == "public_event_delta":
            nonempty = bool(value["events"] or value["unsupported"])
        else:
            nonempty = bool(value["actions"])
        if not nonempty:
            continue
        record = PublicEvidenceRecord(kind, value["turn"], _canonical(value))
        key = (record.kind, record.source_turn, record.payload)
        if key not in seen:
            records.append(record)
            seen.add(key)

    actions = view["opponent_last_actions"]
    if actions:
        record = PublicEvidenceRecord(
            "opponent_last_actions", actions[0]["turn"], _canonical(actions)
        )
        key = (record.kind, record.source_turn, record.payload)
        if key not in seen:
            records.append(record)
            seen.add(key)

    if len(records) > MAX_PUBLIC_EVIDENCE_RECORDS:
        raise ValueError("public constraint ledger capacity exceeded; cannot drop history")
    return tuple(records)
