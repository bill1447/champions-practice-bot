"""Public effect timing evidence must not invent native duration authority."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from champions_practice.current_state_constraints import PublicEvidenceRecord
from champions_practice.public_effect_timing import public_pseudo_weather_timing


def _fixture():
    view = {"turn": 4, "field": {"pseudo_weather": ["trickroom"]}}
    ledger = SimpleNamespace(
        current_turn=4,
        matches_current_public_projection=lambda v: v is view,
        records=(
            PublicEvidenceRecord(
                "public_event_delta", 2,
                json.dumps({"events": [["-fieldstart", "move:trickroom"]],
                            "turn": 2, "unsupported": []}),
            ),
        ),
    )
    return ledger, view


def test_observed_start_records_age_but_never_proves_duration():
    ledger, view = _fixture()
    evidence = public_pseudo_weather_timing(ledger, view)
    assert len(evidence) == 1
    assert evidence[0].effect == "trickroom"
    assert evidence[0].active
    assert evidence[0].latest_observed_start_turn == 2
    assert evidence[0].activation_age_turns == 2
    assert not evidence[0].duration_proven


def test_missing_start_never_fabricates_age():
    ledger, view = _fixture()
    ledger.records = ()
    evidence = public_pseudo_weather_timing(ledger, view)
    assert evidence[0].activation_age_turns is None
    assert not evidence[0].duration_proven


def test_end_invalidates_older_start():
    ledger, view = _fixture()
    ledger.records += (
        PublicEvidenceRecord(
            "public_event_delta", 3,
            json.dumps({"events": [["-fieldend", "move:trickroom"]],
                        "turn": 3, "unsupported": []}),
        ),
    )
    evidence = public_pseudo_weather_timing(ledger, view)
    assert evidence[0].latest_observed_start_turn is None
    assert not evidence[0].duration_proven


def test_does_not_accept_unrelated_snapshot():
    ledger, view = _fixture()
    with pytest.raises(ValueError, match="matching public ledger"):
        public_pseudo_weather_timing(ledger, dict(view))
