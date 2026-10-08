"""Rolling public checkpoint authority, bounded one-turn progress and fail-open tests."""

from __future__ import annotations

from copy import deepcopy

import pytest

from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.current_state_proposals import build_current_state_set_proposals
from champions_practice.current_state_reconstruction import _matches_approved_prior
from champions_practice.demo_fixture import demo_public_priors
from champions_practice.public_scaffold_bootstrap import PublicScaffoldWitness
from champions_practice.rolling_public_checkpoints import (
    PublicRebaseCheckpoint,
    advance_rolling_public_checkpoints,
    validate_public_bootstrap_checkpoint,
)

SPECIES = (
    "Indeedee-F", "Sneasler", "Gardevoir", "Armarouge", "Rillaboom", "Metagross",
)
SEED = "sodium,00000001000000020000000300000004"
OWN = "move protect, move psychic"


@pytest.fixture(autouse=True)
def reduced_public_schema(monkeypatch):
    # The pinned Showdown smoke covers the real full public schema.
    monkeypatch.setattr(
        "champions_practice.current_state_constraints."
        "public_reachability_observation_issue",
        lambda _view: None,
    )


def view(turn):
    result = {
        "turn": turn, "phase": "move", "ended": False, "winner": None,
        "request": {"choosing": "p2", "turn": turn},
        "field": {"weather": None, "terrain": None, "pseudo_weather": []},
        "player": {"name": "AI", "team": [{"species": s} for s in SPECIES]},
        "opponent": {
            "name": "Human", "preview_species": list(SPECIES),
            "active": [
                {
                    "species": s, "base_species": s, "hp_percent": 100,
                    "fainted": False, "status": None, "boosts": {},
                }
                for s in ("Sneasler", "Indeedee-F")
            ],
            "revealed": [
                {
                    "species": s, "moves": [], "items": [], "abilities": [],
                    "status": None, "seen": s in ("Sneasler", "Indeedee-F"),
                    "fainted": False, "hp_percent": 100,
                } for s in SPECIES
            ],
            "side_conditions": [],
        },
        "opponent_last_actions": [],
        "public_execution_delta": {"turn": None, "actions": []},
        "public_event_delta": {"turn": None, "events": [], "unsupported": []},
    }
    if turn >= 2:
        result["opponent_last_actions"] = [
            {"turn": turn - 1, "slot": 1, "move": "closecombat", "target": 1},
            {"turn": turn - 1, "slot": 2, "move": "psychic", "target": 2},
        ]
        result["public_execution_delta"]["turn"] = turn - 1
        result["public_event_delta"]["turn"] = turn - 1
    return result


def prior_state(proposal, turn):
    members = []
    for mon in proposal.world.sets:
        members.append({"set": {
            "species": mon.species,
            "item": mon.item or "",
            "ability": mon.ability,
            "nature": mon.nature,
            "moves": list(mon.moves),
            "evs": dict(mon.stat_points),
        }, "hp": 100, "maxhp": 170})
    return {"sides": [{"pokemon": members}, {"pokemon": []}], "turn": turn}


def fixture():
    opening, before, after = view(1), view(2), view(3)
    start = PublicConstraintLedger.from_public_view(opening)
    old = start.advance(before)
    new = old.advance(after)
    batch = build_current_state_set_proposals(
        ledger=new, current_view=after, priors=demo_public_priors(), limit=8,
    )
    assert batch.proposals
    old_batch = build_current_state_set_proposals(
        ledger=old, current_view=before, priors=demo_public_priors(), limit=8,
    )
    compatible_teams = {p.team_text for p in batch.proposals}
    p = next(p for p in old_batch.proposals if p.team_text in compatible_teams)
    witness = PublicScaffoldWitness(
        proposal_id=p.proposal_id,
        opponent_choice="move closecombat +1, move psychic +2",
        own_choice=OWN, rng_seed=SEED, state=prior_state(p, 2),
    )
    return before, after, old, new, batch, witness


class FakeWorker:
    def __init__(self, before, after, *, tamper_request=False,
                 tamper_projection=False, own_legal=True):
        self.before = before
        self.after = after
        self.tamper_request = tamper_request
        self.tamper_projection = tamper_projection
        self.own_legal = own_legal
        self.branches = 0

    def state_view(self, *, state, side, previews):
        assert side == "p2"
        result = deepcopy(self.before if state["turn"] == 2 else self.after)
        if self.tamper_request and state["turn"] == 3:
            result["request"]["choosing"] = "tampered"
        if self.tamper_projection and state["turn"] == 3:
            result["opponent"]["active"][0]["hp_percent"] = 70
        return result

    def legal_choices(self, *, state, side):
        if side == "p2":
            return [OWN] if self.own_legal else ["move somethingelse"]
        return ["move direclaw +1, move psychic +2",
                "move closecombat +1, move psychic +2"]

    def branch_many(self, *, state, branches):
        self.branches += len(branches)
        returned = []
        for branch in branches:
            child = deepcopy(state)
            child["turn"] = 3
            returned.append({
                "state": child,
                "view": self.state_view(
                    state=child, side="p2", previews=branch["previews"],
                ),
            })
        return returned


def launch(*, worker=None, tweak=None, **kwargs):
    before, after, old, new, batch, witness = fixture()
    if tweak:
        before, after, old, new, batch, witness = tweak(
            before, after, old, new, batch, witness
        )
    worker = worker or FakeWorker(before, after)
    checkpoint = validate_public_bootstrap_checkpoint(
        worker, witness=witness, ledger=old,
        current_view=before, prior_batch=batch_at(old, before),
    )
    assert checkpoint is not None
    report = advance_rolling_public_checkpoints(
        worker, previous_view=before, current_view=after,
        previous_ledger=old, current_ledger=new,
        previous_prior_batch=batch_at(old, before),
        prior_batch=batch, checkpoints=(checkpoint,),
        known_own_choice=OWN, rng_seeds=(SEED,), **kwargs,
    )
    return report, worker


def batch_at(ledger, public):
    return build_current_state_set_proposals(
        ledger=ledger, current_view=public,
        priors=demo_public_priors(), limit=8,
    )


def test_public_checkpoint_advances_from_turn_two_to_turn_three():
    report, worker = launch()
    assert report.input_checkpoints == 1
    assert report.validated_parents == 1
    assert report.checkpoints
    assert worker.branches == report.simulated_branches
    assert all(c.turn == 3 and c.depth == 2 for c in report.checkpoints)
    assert all(not c.live_admission_authorized for c in report.checkpoints)
    assert report.exhaustive_disproofs == 0
    assert report.live_admission_authorized is False


def test_wrong_prior_set_spoofing_is_not_a_valid_checkpoint():
    before, _, old, _, _, witness = fixture()
    worker = FakeWorker(before, view(3))
    forged = deepcopy(witness.state)
    forged["sides"][0]["pokemon"][0]["set"]["nature"] = "wrong"
    assert not _matches_approved_prior(forged, batch_at(old, before).proposals[0])
    wrong = PublicScaffoldWitness(
        witness.proposal_id, witness.opponent_choice,
        witness.own_choice, witness.rng_seed, forged,
    )
    assert validate_public_bootstrap_checkpoint(
        worker, witness=wrong, ledger=old,
        current_view=before, prior_batch=batch_at(old, before),
    ) is None


def test_tampered_checkpoint_signature_rejected_without_branching():
    before, after, old, new, batch, witness = fixture()
    worker = FakeWorker(before, after)
    checkpoint = validate_public_bootstrap_checkpoint(
        worker, witness=witness, ledger=old,
        current_view=before, prior_batch=batch_at(old, before),
    )
    assert checkpoint is not None
    wrong = PublicRebaseCheckpoint(
        checkpoint.proposal_id, checkpoint.turn,
        "not-validated", checkpoint.state,
    )
    result = advance_rolling_public_checkpoints(
        worker, previous_view=before, current_view=after,
        previous_ledger=old, current_ledger=new,
        previous_prior_batch=batch_at(old, before),
        prior_batch=batch, checkpoints=(wrong,),
        known_own_choice=OWN, rng_seeds=(SEED,),
    )
    assert not result.checkpoints
    assert result.rejected_parents == 1
    assert result.exhaustive_disproofs == 0
    assert worker.branches == 0


def test_no_matching_projection_retains_inconclusive_support():
    before, after, *_ = fixture()
    report, _ = launch(worker=FakeWorker(before, after, tamper_projection=True))
    assert report.checkpoints == ()
    assert report.projection_mismatches > 0
    assert report.unresolved_reason == "bounded-rolling-checkpoint-unresolved"
    assert report.exhaustive_disproofs == 0


def test_illegal_own_choice_yields_no_unjustified_world_exclusion():
    before, after, *_ = fixture()
    report, worker = launch(worker=FakeWorker(before, after, own_legal=False))
    assert not report.checkpoints
    assert worker.branches == 0
    assert report.exhaustive_disproofs == 0


def test_lost_public_action_evidence_does_not_invent_opponent_command():
    before, after, old, _, _, witness = fixture()
    after["opponent_last_actions"] = after["opponent_last_actions"][:1]
    new = old.advance(after)
    batch = batch_at(new, after)
    worker = FakeWorker(before, after)
    checkpoint = validate_public_bootstrap_checkpoint(
        worker, witness=witness, ledger=old,
        current_view=before, prior_batch=batch_at(old, before),
    )
    assert checkpoint is not None
    report = advance_rolling_public_checkpoints(
        worker, previous_view=before, current_view=after,
        previous_ledger=old, current_ledger=new,
        previous_prior_batch=batch_at(old, before),
        prior_batch=batch, checkpoints=(checkpoint,),
        known_own_choice=OWN, rng_seeds=(SEED,),
    )
    assert report.unresolved_reason == "incomplete-public-opponent-actions"
    assert not report.checkpoints
    assert worker.branches == 0


def test_bounded_no_history_and_stale_current_snapshot_are_inconclusive():
    report, worker = launch(max_branches=1)
    assert report.simulated_branches == 1
    assert report.exhaustive_disproofs == 0
    before, after, old, new, batch, witness = fixture()
    out_of_order = deepcopy(after)
    out_of_order["turn"] = 4
    later_ledger = new.advance(out_of_order)
    with pytest.raises(ValueError, match="disagrees"):
        advance_rolling_public_checkpoints(
            worker, previous_view=before, current_view=out_of_order,
            previous_ledger=old, current_ledger=new,
            previous_prior_batch=batch_at(old, before),
            prior_batch=batch, checkpoints=(),
            known_own_choice=OWN, rng_seeds=(SEED,),
        )
    assert later_ledger.current_turn == 4


@pytest.mark.parametrize("parameter", [
    "max_checkpoints", "max_opponent_choices", "max_branches", "max_witnesses",
])
@pytest.mark.parametrize("invalid", [0, -1, True, 1.5])
def test_invalid_budgets_rejected(parameter, invalid):
    before, after, old, new, batch, witness = fixture()
    with pytest.raises(ValueError, match=parameter):
        advance_rolling_public_checkpoints(
            FakeWorker(before, after),
            previous_view=before, current_view=after,
            previous_ledger=old, current_ledger=new,
            previous_prior_batch=batch_at(old, before),
            prior_batch=batch, checkpoints=(),
            known_own_choice=OWN, rng_seeds=(SEED,),
            **{parameter: invalid},
        )
