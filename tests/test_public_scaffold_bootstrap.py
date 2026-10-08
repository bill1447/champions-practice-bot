"""First-scaffold public-witness bootstrap: isolated authority and limits."""

from __future__ import annotations

from copy import deepcopy

import pytest

from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.current_state_proposals import build_current_state_set_proposals
from champions_practice.demo_fixture import demo_public_priors
from champions_practice.public_scaffold_bootstrap import bootstrap_public_current_scaffolds


SPECIES = (
    "Indeedee-F", "Sneasler", "Gardevoir", "Armarouge", "Rillaboom", "Metagross",
)
SEED = "sodium,00000001000000020000000300000004"
OWN = "move protect, move psychic"


@pytest.fixture(autouse=True)
def fixture_validation(monkeypatch):
    # Full real v9 producer validation is exercised in the pinned CI smoke.
    monkeypatch.setattr(
        "champions_practice.current_state_constraints."
        "public_reachability_observation_issue", lambda _view: None,
    )


def public_view(turn=1):
    return {
        "turn": turn, "phase": "move", "ended": False, "winner": None,
        "request": {"phase": "move", "turn": turn},
        "field": {"weather": None, "terrain": None, "pseudo_weather": []},
        "player": {
            "name": "AI", "team": [{"species": x} for x in SPECIES],
        },
        "opponent": {
            "name": "Human", "preview_species": list(SPECIES),
            "active": [{
                "species": s, "base_species": s, "hp_percent": 100,
                "fainted": False, "status": None, "boosts": {},
            } for s in ("Sneasler", "Indeedee-F")],
            "revealed": [{
                "species": s, "moves": [], "items": [], "abilities": [],
                "hp_percent": 100, "status": None, "fainted": False,
                "seen": s in ("Sneasler", "Indeedee-F"),
            } for s in SPECIES],
            "side_conditions": [],
        },
        "opponent_last_actions": [],
        "public_event_delta": {"turn": None, "events": [], "unsupported": []},
        "public_execution_delta": {"turn": None, "actions": []},
    }


def fixture():
    opening = public_view()
    current = public_view(turn=2)
    current["opponent_last_actions"] = [
        {"turn": 1, "slot": 1, "move": "closecombat", "target": 1},
        {"turn": 1, "slot": 2, "move": "psychic", "target": 2},
    ]
    current["public_event_delta"]["turn"] = 1
    current["public_execution_delta"]["turn"] = 1
    ledger = PublicConstraintLedger.from_public_view(opening).advance(current)
    batch = build_current_state_set_proposals(
        ledger=ledger, current_view=current,
        priors=demo_public_priors(), limit=8,
    )
    return opening, current, ledger, batch


class FakeWorker:
    def __init__(self, opening, current, *, break_opening=False,
                 break_current=False, valid_own=True):
        self.opening = opening
        self.current = current
        self.break_opening = break_opening
        self.break_current = break_current
        self.valid_own = valid_own
        self.creates = 0
        self.branches = 0

    def create_state(self, **kwargs):
        assert "p1_team" in kwargs and "p2_team" in kwargs
        self.creates += 1
        return {"root": True}

    def state_view(self, *, state, side, previews):
        assert side == "p2"
        if state.get("root"):
            v = deepcopy(self.opening)
            if self.break_opening:
                v["request"]["phase"] = "wrong"
            return v
        v = deepcopy(self.current)
        if self.break_current:
            v["request"]["phase"] = "wrong"
        return v

    def legal_choices(self, *, state, side):
        if side == "p2":
            return [OWN] if self.valid_own else ["move other"]
        return [
            "move closecombat +1, move psychic +2",
            "move direclaw +1, move psychic +2",
            "move protect, move psychic +2",
        ]

    def branch_many(self, *, state, branches):
        self.branches += len(branches)
        return [
            {"index": i, "state": {"root": False}, "view": self.state_view(
                state={"root": False}, side="p2", previews=b["previews"],
            )}
            for i, b in enumerate(branches)
        ]


def run(worker, data, **extra):
    opening, current, ledger, batch = data
    return bootstrap_public_current_scaffolds(
        worker,
        opening_view=opening, current_view=current,
        ledger=ledger, prior_batch=batch,
        battle_format="format", ai_team="team",
        ai_preview_choice="team 1235",
        known_own_choice=OWN, rng_seeds=(SEED,), **extra,
    )


def test_one_public_turn_bootstraps_native_state_without_old_particles():
    data = fixture()
    worker = FakeWorker(data[0], data[1])
    report = run(worker, data, max_roots=2)
    assert report.witnesses
    assert report.fresh_roots <= 2
    assert report.simulated_branches > 0
    assert worker.branches == report.simulated_branches
    assert all(w.live_admission_authorized is False for w in report.witnesses)
    assert all(w.own_choice == OWN for w in report.witnesses)
    assert all(w.opponent_choice == "move closecombat +1, move psychic +2"
               for w in report.witnesses)
    assert not report.live_admission_authorized
    assert report.exhaustive_disproofs == 0


def test_unmatched_public_projection_is_never_exclusion_authority():
    data = fixture()
    worker = FakeWorker(data[0], data[1], break_current=True)
    report = run(worker, data, max_roots=1)
    assert not report.witnesses
    assert report.observation_mismatches > 0
    assert report.exhaustive_disproofs == 0
    assert report.unsupported_reason == "bounded-public-witness-search-unresolved"


def test_invalid_own_request_and_opening_projection_never_branch():
    data = fixture()
    for args in ({"valid_own": False}, {"break_opening": True}):
        worker = FakeWorker(data[0], data[1], **args)
        report = run(worker, data, max_roots=1)
        assert not report.witnesses
        assert worker.branches == 0
        assert report.exhaustive_disproofs == 0


def test_history_gap_and_tampered_same_turn_observation_fail_closed():
    opening, current, ledger, batch = fixture()
    worker = FakeWorker(opening, current)
    invalid = deepcopy(opening)
    invalid["turn"] = 0
    report = bootstrap_public_current_scaffolds(
        worker, opening_view=invalid, current_view=current,
        ledger=ledger, prior_batch=batch, battle_format="format",
        ai_team="team", ai_preview_choice="team 1235",
        known_own_choice=OWN, rng_seeds=(SEED,),
    )
    assert not report.witnesses and not report.exhaustive_disproofs
    assert report.unsupported_reason == "unsupported-or-incomplete-one-turn-public-history"
    modified = deepcopy(current)
    modified["request"]["turn"] = 88
    with pytest.raises(ValueError, match="disagrees"):
        bootstrap_public_current_scaffolds(
            worker, opening_view=opening, current_view=modified,
            ledger=ledger, prior_batch=batch, battle_format="format",
            ai_team="team", ai_preview_choice="team 1235",
            known_own_choice=OWN, rng_seeds=(SEED,),
        )


def test_incomplete_opponent_action_observation_does_not_guess_command():
    opening, current, _, _ = fixture()
    current["opponent_last_actions"] = current["opponent_last_actions"][:1]
    ledger = PublicConstraintLedger.from_public_view(opening).advance(current)
    batch = build_current_state_set_proposals(
        ledger=ledger, current_view=current,
        priors=demo_public_priors(), limit=4,
    )
    worker = FakeWorker(opening, current)
    report = run(worker, (opening, current, ledger, batch))
    assert report.unsupported_reason == "incomplete-public-opponent-actions"
    assert worker.creates == 0


def test_branch_budget_and_no_implicit_exhaustiveness():
    data = fixture()
    worker = FakeWorker(data[0], data[1])
    report = run(worker, data, max_roots=8, max_branches=1)
    assert report.simulated_branches == 1
    assert report.exhaustive_disproofs == 0


@pytest.mark.parametrize("parameter", ["max_roots", "max_branches", "max_witnesses",
                                        "max_opponent_choices"])
@pytest.mark.parametrize("invalid", [0, True, -1, 1.5])
def test_invalid_budgets_rejected(parameter, invalid):
    data = fixture()
    with pytest.raises(ValueError, match=parameter):
        run(FakeWorker(data[0], data[1]), data, **{parameter: invalid})
