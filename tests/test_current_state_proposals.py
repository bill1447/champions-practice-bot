"""Isolated current-state proposal and dual-projection acceptance regressions."""

from __future__ import annotations

import copy

import pytest

from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.current_state_proposals import (
    RebaseProposalStatus,
    build_current_state_set_proposals,
    probe_fresh_prior_projections,
)
from champions_practice.demo_fixture import demo_public_priors


SPECIES = (
    "Indeedee-F", "Sneasler", "Gardevoir", "Armarouge", "Rillaboom", "Metagross"
)


@pytest.fixture(autouse=True)
def reduced_fixture_validation(monkeypatch):
    # Public schema validity is independently tested in the pinned-runtime
    # integration smoke; small unit fixtures here target proposal logic.
    monkeypatch.setattr(
        "champions_practice.current_state_constraints."
        "public_reachability_observation_issue",
        lambda _view: None,
    )


def public_view(*, turn=1):
    return {
        "turn": turn, "phase": "move", "ended": False, "winner": None,
        "field": {"weather": None, "terrain": None, "pseudo_weather": []},
        "request": {"request": "authoritative-own-menu", "turn": turn},
        "player": {
            "name": "AI", "team": [{"species": species} for species in SPECIES],
        },
        "opponent": {
            "name": "Human",
            "preview_species": list(SPECIES),
            "active": [
                {
                    "species": species, "base_species": species,
                    "hp_percent": 100, "fainted": False,
                    "status": None, "boosts": {},
                }
                for species in ("Sneasler", "Indeedee-F")
            ],
            "revealed": [
                {
                    "species": species, "moves": [], "items": [],
                    "abilities": [], "hp_percent": 100,
                    "fainted": False, "seen": species in {"Sneasler", "Indeedee-F"},
                    "status": None,
                }
                for species in SPECIES
            ],
            "side_conditions": [],
        },
        "opponent_last_actions": [],
        "public_execution_delta": {"turn": None, "actions": []},
        "public_event_delta": {"turn": None, "events": [], "unsupported": []},
    }


def prepare(*, turn=1, limit=12):
    view = public_view(turn=turn)
    ledger = PublicConstraintLedger.from_public_view(view)
    batch = build_current_state_set_proposals(
        ledger=ledger, current_view=view,
        priors=demo_public_priors(), limit=limit,
    )
    assert batch.proposals
    return view, ledger, batch


def test_worlds_have_public_prior_provenance_and_diverse_selection():
    _, _, batch = prepare()
    assert batch.source_turn == 1
    assert batch.live_admission_authorized is False
    assert len({p.proposal_id for p in batch.proposals}) == len(batch.proposals)
    assert all(p.proposal_id.startswith("public-prior:") for p in batch.proposals)
    assert all(p.weight > 0 for p in batch.proposals)
    assert len({p.selected_species for p in batch.proposals}) > 1
    assert all("Sneasler" in p.selected_species for p in batch.proposals)


def test_items_and_abilities_are_observations_not_immutable_starting_set_proofs():
    view = public_view()
    for entry in view["opponent"]["revealed"]:
        if entry["species"] == "Metagross":
            entry["seen"] = True
            entry["items"] = ["leftovers", "metagrossite"]
            entry["abilities"] = ["lightmetal", "clearbody"]
    ledger = PublicConstraintLedger.from_public_view(view)
    batch = build_current_state_set_proposals(
        ledger=ledger, current_view=view,
        priors=demo_public_priors(), limit=16,
    )
    metagross = [p for p in batch.proposals if "Metagross" in p.selected_species]
    labels = {p.world.set_for_species("Metagross").label for p in metagross}
    assert labels == {"mega", "bulky"}


def test_publicly_seen_move_is_preserved_across_later_snapshots():
    first = public_view()
    sneasler = next(x for x in first["opponent"]["revealed"]
                    if x["species"] == "Sneasler")
    sneasler["moves"] = ["closecombat"]
    ledger = PublicConstraintLedger.from_public_view(first)
    later = public_view(turn=2)
    ledger = ledger.advance(later)
    batch = build_current_state_set_proposals(
        ledger=ledger, current_view=later,
        priors=demo_public_priors(), limit=4,
    )
    assert batch.proposals
    assert all("Close Combat" in
               p.world.set_for_species("Sneasler").moves
               for p in batch.proposals)


def test_missing_static_prior_does_not_exclude_true_hidden_world():
    current = public_view()
    current["opponent"]["revealed"][1]["moves"] = ["unknownmove"]
    ledger = PublicConstraintLedger.from_public_view(current)
    batch = build_current_state_set_proposals(
        ledger=ledger, current_view=current, priors=demo_public_priors(),
    )
    assert batch.proposals == ()
    assert batch.missing_prior is not None
    assert batch.live_admission_authorized is False


def test_stale_or_tampered_view_rejected_before_worker():
    view, ledger, batch = prepare()
    forged = copy.deepcopy(view)
    forged["request"]["request"] = "some-other-own-menu"
    with pytest.raises(ValueError, match="disagrees"):
        build_current_state_set_proposals(
            ledger=ledger, current_view=forged, priors=demo_public_priors()
        )
    worker = FakeWorker(view)
    with pytest.raises(ValueError, match="disagrees"):
        probe_fresh_prior_projections(
            worker, ledger=ledger, current_view=forged, proposals=batch,
            battle_format="test", ai_team="team", ai_preview_choice="team 1234",
            seed="1,2,3,4",
        )
    assert worker.created == 0


class FakeWorker:
    def __init__(self, projected):
        self.projected = projected
        self.created = 0

    def create_state(self, **kwargs):
        self.created += 1
        return {"source": "fresh-showdown-opening", "seed": kwargs["seed"]}

    def state_view(self, **kwargs):
        return copy.deepcopy(self.projected)


def _probe(worker, view, ledger, batch):
    return probe_fresh_prior_projections(
        worker, ledger=ledger, current_view=view, proposals=batch,
        battle_format="test", ai_team="approved-p2",
        ai_preview_choice="team 1234", seed="1,2,3,4",
        max_probes=2,
    )


def test_complete_matching_opening_projection_is_not_live_authority():
    view, ledger, batch = prepare()
    worker = FakeWorker(view)
    results = _probe(worker, view, ledger, batch)
    assert len(results) == 2
    assert worker.created == 2
    assert all(p.status is RebaseProposalStatus.PROJECTION_MATCH for p in results)
    assert all(p.own_request_equal and p.public_projection_equal for p in results)
    assert all(p.matching_opening_state is not None for p in results)
    assert all(not p.live_admission_authorized for p in results)


def test_wrong_own_request_always_rejects_even_with_plausible_other_fields():
    view, ledger, batch = prepare()
    forged = copy.deepcopy(view)
    forged["request"]["turn"] = 8
    probes = _probe(FakeWorker(forged), view, ledger, batch)
    assert all(p.status is RebaseProposalStatus.OWN_REQUEST_MISMATCH for p in probes)
    assert all(p.matching_opening_state is None for p in probes)


def test_wrong_public_projection_rejects_even_when_request_matches():
    view, ledger, batch = prepare()
    forged = copy.deepcopy(view)
    forged["opponent"]["active"][0]["hp_percent"] = 53
    probes = _probe(FakeWorker(forged), view, ledger, batch)
    assert all(p.status is RebaseProposalStatus.PUBLIC_PROJECTION_MISMATCH
               for p in probes)
    assert all(p.matching_opening_state is None for p in probes)


def test_fresh_root_cannot_be_relabelled_a_midgame_state_even_if_view_forged():
    view, ledger, batch = prepare(turn=3)
    probes = _probe(FakeWorker(view), view, ledger, batch)
    assert all(p.status is RebaseProposalStatus.NOT_CURRENT_STATE for p in probes)
    assert all(p.matching_opening_state is None for p in probes)
    assert all(not p.live_admission_authorized for p in probes)


def test_stale_batch_rejected_and_probe_budget_bounded():
    view, ledger, batch = prepare()
    another = public_view(turn=2)
    newer = ledger.advance(another)
    with pytest.raises(ValueError, match="stale"):
        _probe(FakeWorker(another), another, newer, batch)
    worker = FakeWorker(view)
    results = _probe(worker, view, ledger, batch)
    assert len(results) == worker.created == 2


@pytest.mark.parametrize("limit", [0, True, -1, 3.2])
def test_invalid_generator_budget_rejected(limit):
    view = public_view()
    ledger = PublicConstraintLedger.from_public_view(view)
    with pytest.raises(ValueError, match="limit"):
        build_current_state_set_proposals(
            ledger=ledger, current_view=view,
            priors=demo_public_priors(), limit=limit,
        )



def test_same_turn_revised_public_snapshot_invalidates_old_proposals():
    view, ledger, batch = prepare()
    changed = copy.deepcopy(view)
    changed["request"]["request"] = "different-own-menu"
    revised = ledger.advance(changed)
    worker = FakeWorker(changed)
    with pytest.raises(ValueError, match="stale"):
        _probe(worker, changed, revised, batch)
    assert worker.created == 0



def test_forced_struggle_does_not_disqualify_public_set_priors():
    view = public_view(turn=3)
    indeedee = next(
        entry for entry in view["opponent"]["revealed"]
        if entry["species"] == "Indeedee-F"
    )
    indeedee["moves"] = ["psychic", "struggle"]
    ledger = PublicConstraintLedger.from_public_view(view)
    batch = build_current_state_set_proposals(
        ledger=ledger, current_view=view,
        priors=demo_public_priors(), limit=12,
    )
    assert batch.proposals
    assert "struggle" in ledger.known_sets[0].moves or any(
        "struggle" in known.moves for known in ledger.known_sets
    )
    assert all(
        "struggle" not in {
            move.lower() for move in proposal.world.set_for_species("Indeedee-F").moves
        }
        for proposal in batch.proposals
        if "Indeedee-F" in proposal.selected_species
    )


def test_actual_unknown_move_still_disqualifies_public_set_priors():
    view = public_view(turn=3)
    indeedee = next(
        entry for entry in view["opponent"]["revealed"]
        if entry["species"] == "Indeedee-F"
    )
    indeedee["moves"] = ["psychic", "thunderbolt"]
    ledger = PublicConstraintLedger.from_public_view(view)
    batch = build_current_state_set_proposals(
        ledger=ledger, current_view=view,
        priors=demo_public_priors(), limit=12,
    )
    assert not batch.proposals
    assert batch.missing_prior is not None
