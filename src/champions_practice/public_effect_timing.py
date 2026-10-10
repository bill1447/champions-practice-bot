"""Public-only timing evidence; never native effect-duration authority.

An observed activation identifies a latest known start turn, NOT a remaining
native counter. Unobserved prior turns, extensions and resets prevent claiming
a singleton timer. This module deliberately does not mutate search roots.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from champions_practice.current_state_constraints import PublicConstraintLedger


@dataclass(frozen=True)
class PublicEffectTimingEvidence:
    effect: str
    active: bool
    latest_observed_start_turn: int | None
    latest_observed_end_turn: int | None
    activation_age_turns: int | None
    duration_proven: bool = False


def public_pseudo_weather_timing(
    ledger: PublicConstraintLedger,
    current_view: dict,
) -> tuple[PublicEffectTimingEvidence, ...]:
    """Record only witnessed start/end turns of currently visible effects.

    This intentionally cannot authorize a duration for fresh Showdown roots.
    A ledger may omit turns, and item/ability extension need not be visible.
    """
    if ledger.current_turn != current_view["turn"] or not ledger.matches_current_public_projection(
        current_view
    ):
        raise ValueError("effect timing requires matching public ledger/current observation")
    effects = current_view["field"]["pseudo_weather"]
    start: dict[str, int] = {}
    end: dict[str, int] = {}
    for record in ledger.records:
        if record.kind != "public_event_delta" or record.source_turn is None:
            continue
        delta = json.loads(record.payload)
        for event in delta["events"]:
            if not isinstance(event, list) or len(event) < 2:
                continue
            token = event[1]
            if not isinstance(token, str) or not token.startswith("move:"):
                continue
            effect = token[5:]
            if event[0] == "-fieldstart":
                start[effect] = max(record.source_turn, start.get(effect, -1))
            elif event[0] == "-fieldend":
                end[effect] = max(record.source_turn, end.get(effect, -1))
    names = sorted(set(effects) | set(start) | set(end))
    result = []
    for name in names:
        active = name in effects
        began = start.get(name)
        ended = end.get(name)
        # A later observed end invalidates evidence of an earlier start.
        if began is not None and ended is not None and ended >= began:
            began = None
        result.append(PublicEffectTimingEvidence(
            effect=name,
            active=active,
            latest_observed_start_turn=began,
            latest_observed_end_turn=ended,
            activation_age_turns=(
                ledger.current_turn - began if active and began is not None else None
            ),
        ))
    return tuple(result)
