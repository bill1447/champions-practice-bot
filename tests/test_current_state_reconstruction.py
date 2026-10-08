"""Positive-only current-turn native reconstruction authority tests."""

from __future__ import annotations

from copy import deepcopy

import pytest

from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.current_state_proposals import (
    build_current_state_set_proposals,
)
from champions_practice.current_state_reconstruction import (
    CurrentTurnScaffold,
    _matches_approved_prior,
    _native_hp_only_change,
    reconstruct_current_hp_hypotheses,
)
from champions_practice.demo_fixture import demo_public_priors


SPECIES = (
    "Indeedee-F", "Sneasler", "Gardevoir", "Armarouge", "Rillaboom", "Metagross",
)


@pytest.fixture(autouse=True)
def reduced_public_schema(monkeypatch):
    monkeypatch.setattr(
        "champions_practice.current_state_constraints."
        "public_reachability_observation_issue",
        lambda _view: None,
    )


def view(*, turn=3):
    return {
        "turn": turn,
        "phase": "move",
        "ended": False,
        "winner": None,
        "request": {"own_side": "known", "turn": turn},
        "field": {"weather": None, "terrain": None, "pseudo_weather": []},
        "player": {
            "name": "AI",
            "team": [{"species": s} for s in SPECIES],
        },
        "opponent": {
            "name": "Human",
            "preview_species": list(SPECIES),
            "side_conditions": [],
            "active": [
                {
                    "base_species": s,
                    "species": s,
                    "hp_percent": 60,
                    "status": None,
                    "fainted": False,
                    "boosts": {},
                }
                for s in ("Sneasler", "Indeedee-F")
            ],
            "revealed": [
                {
                    "species": s, "moves": [], "items": [], "abilities": [],
                    "status": None, "seen": s in ("Sneasler", "Indeedee-F"),
                    "fainted": False, "hp_percent": 60,
                }
                for s in SPECIES
            ],
        },
        "public_event_delta": {"turn": 2, "events": [], "unsupported": []},
        "public_execution_delta": {"turn": 2, "actions": []},
        "opponent_last_actions": [],
    }


def setup():
    public = view()
    ledger = PublicConstraintLedger.from_public_view(public)
    batch = build_current_state_set_proposals(
        ledger=ledger, current_view=public, priors=demo_public_priors(), limit=8,
    )
    assert batch.proposals
    proposal = batch.proposals[0]
    members = []
    for candidate in proposal.world.sets:
        members.append({
            "set": {
                "species": candidate.species,
                "item": candidate.item or "",
                "ability": candidate.ability,
                "nature": candidate.nature,
                "moves": list(candidate.moves),
                "evs": dict(candidate.stat_points),
            },
            "hp": 103,
            "maxhp": 170,
        })
    scaffold = CurrentTurnScaffold(
        proposal_id=proposal.proposal_id,
        state={"sides": [{"pokemon": members}, {"pokemon": []}],
               "turn": 3, "log": ["public-event"]},
    )
    return public, ledger, batch, scaffold


class StubWorker:
    def __init__(self, public, *, request_mutation=False, projection_mutation=False,
                 hidden_mutation=False):
        self.public = public
        self.request_mutation = request_mutation
        self.projection_mutation = projection_mutation
        self.hidden_mutation = hidden_mutation
        self.materializations = 0

    def state_view(self, *, state, side, previews):
        assert side == "p2"
        result = deepcopy(self.public)
        if self.request_mutation:
            result["request"]["own_side"] = "forged"
        if self.projection_mutation and state["sides"][0]["pokemon"][0]["hp"] == 104:
            result["opponent"]["active"][0]["hp_percent"] = 59
        return result

    def materialize_current_hp_hypotheses(self, *, state, public_hp_buckets, limit):
        self.materializations += 1
        assert limit <= 8 and public_hp_buckets == (60, 60)
        modified = deepcopy(state)
        modified["sides"][0]["pokemon"][0]["hp"] = 104
        if self.hidden_mutation:
            modified["sides"][0]["pokemon"][0]["set"]["ability"] = "cheat"
        return {
            "outcomes": [{"slot": 0, "hp": 104, "maxhp": 170, "state": modified}],
            "examined": 1, "reason": None,
        }


def run(worker, inputs):
    public, ledger, batch, scaffold = inputs
    return reconstruct_current_hp_hypotheses(
        worker, ledger=ledger, current_view=public, prior_batch=batch,
        scaffolds=(scaffold,),
    )


def test_native_hp_only_candidate_is_non_authoritative():
    inputs = setup()
    worker = StubWorker(inputs[0])
    report = run(worker, inputs)
    assert report.mechanics_scope == "native-exact-hp-only"
    assert report.native_hypotheses == 1
    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.hp == 104
    assert candidate.exact_request_equal
    assert candidate.public_projection_equal
    assert candidate.native_state_delta_hp_only
    assert candidate.live_admission_authorized is False
    assert report.live_admission_authorized is False
    assert worker.materializations == 1


def test_exact_own_request_mismatch_rejects_scaffold():
    inputs = setup()
    worker = StubWorker(inputs[0], request_mutation=True)
    report = run(worker, inputs)
    assert report.rejected_scaffolds == 1
    assert report.candidates == ()
    assert worker.materializations == 0


def test_hypothesis_public_projection_mismatch_rejected():
    inputs = setup()
    report = run(StubWorker(inputs[0], projection_mutation=True), inputs)
    assert report.projection_rejections == 1
    assert report.candidates == ()


def test_unrelated_hidden_mutation_cannot_pass_as_exact_hp_reconstruction():
    inputs = setup()
    report = run(StubWorker(inputs[0], hidden_mutation=True), inputs)
    assert report.projection_rejections == 1
    assert report.candidates == ()


def test_unapproved_or_mislabelled_scaffold_cannot_reach_worker():
    public, ledger, batch, scaffold = setup()
    forged = CurrentTurnScaffold("unapproved", scaffold.state)
    worker = StubWorker(public)
    report = reconstruct_current_hp_hypotheses(
        worker, ledger=ledger, current_view=public, prior_batch=batch,
        scaffolds=(forged,),
    )
    assert report.rejected_scaffolds == 1
    assert worker.materializations == 0
    forged_state = deepcopy(scaffold.state)
    forged_state["sides"][0]["pokemon"][0]["set"]["nature"] = "wrong"
    assert not _matches_approved_prior(
        forged_state, batch.proposals[0]
    )


def test_only_one_opponent_hp_value_may_change():
    _, _, _, scaffold = setup()
    candidate = deepcopy(scaffold.state)
    candidate["sides"][0]["pokemon"][0]["hp"] = 104
    assert _native_hp_only_change(scaffold.state, candidate)
    candidate["sides"][1]["pokemon"].append({"hp": 99})
    assert not _native_hp_only_change(scaffold.state, candidate)
    candidate = deepcopy(scaffold.state)
    candidate["sides"][0]["pokemon"][0]["hp"] = 104
    candidate["sides"][0]["pokemon"][1]["hp"] = 104
    assert not _native_hp_only_change(scaffold.state, candidate)


def test_stale_batch_and_revised_own_request_fail_before_worker():
    public, ledger, batch, scaffold = setup()
    edited = deepcopy(public)
    edited["request"]["own_side"] = "different"
    newer = ledger.advance(edited)
    worker = StubWorker(edited)
    with pytest.raises(ValueError, match="stale"):
        reconstruct_current_hp_hypotheses(
            worker, ledger=newer, current_view=edited,
            prior_batch=batch, scaffolds=(scaffold,),
        )
    assert worker.materializations == 0


def test_missing_proposals_never_proves_world_impossible():
    public, ledger, batch, _ = setup()
    report = reconstruct_current_hp_hypotheses(
        StubWorker(public), ledger=ledger, current_view=public,
        prior_batch=batch, scaffolds=(),
    )
    assert report.candidates == ()
    assert report.examined_scaffolds == 0
    assert report.live_admission_authorized is False


@pytest.mark.parametrize("budget", [0, -1, True, 9, 1.5])
def test_invalid_bound_rejected(budget):
    public, ledger, batch, scaffold = setup()
    with pytest.raises(ValueError, match="max_scaffolds"):
        reconstruct_current_hp_hypotheses(
            StubWorker(public), ledger=ledger, current_view=public,
            prior_batch=batch, scaffolds=(scaffold,),
            max_scaffolds=budget,
        )
