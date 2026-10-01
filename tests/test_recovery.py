from __future__ import annotations

import copy

import pytest

from champions_practice.observation_beliefs import BeliefParticle
from champions_practice.recovery import (
    BoundedOpponentStatProposalGenerator,
    OpponentStatProposal,
    RecoveryCandidate,
    RecoveryCandidateStatus,
    RecoveryObservation,
    RecoveryRequest,
    materialize_stat_proposals,
    validate_recovery_candidates,
)


class _RecoveryWorker:
    def __init__(self, *, checkpoints, transitions) -> None:
        self.checkpoints = checkpoints
        self.transitions = transitions
        self.branch_calls = 0

    def state_view(self, *, state, side, previews=None):
        assert side == "p2"
        return self.checkpoints[state["id"]]

    def validate_choices(self, *, state, side, candidates):
        assert side == "p1"
        return list(candidates)

    def legal_choices(self, *, state, side):
        return ["move human"]

    def branch_many(self, *, state, branches):
        self.branch_calls += 1
        step = int(state.get("step", 0)) + 1
        view = self.transitions[(state["id"], step)]
        return [
            {
                "state": {"id": state["id"], "step": step},
                "view": view,
            }
            for _branch in branches
        ]


def _request() -> RecoveryRequest:
    checkpoint = {
        "turn": 1,
        "opponent": {"active": [{"species": "Snorlax", "hp_percent": 100}]},
    }
    first = {
        "turn": 2,
        "opponent": {"active": [{"species": "Snorlax", "hp_percent": 80}]},
    }
    second = {
        "turn": 3,
        "opponent": {"active": [{"species": "Snorlax", "hp_percent": 60}]},
    }
    return RecoveryRequest(
        checkpoint_particles=(
            BeliefParticle(
                {"id": "original", "sides": [{"foe": "base"}, {"own": "fixed"}]},
                1.0,
                world_id="world-1",
            ),
        ),
        checkpoint_public_view=checkpoint,
        observations=(
            RecoveryObservation(
                ai_choice="move ai",
                resolved_opponent_choice="move human",
                previous_public_view=checkpoint,
                public_view=first,
            ),
            RecoveryObservation(
                ai_choice="move ai",
                resolved_opponent_choice="move human",
                previous_public_view=first,
                public_view=second,
            ),
        ),
        ai_side="p2",
        previews={"p1": ["Snorlax"], "p2": ["Indeedee-F"]},
    )


def _stat_request() -> RecoveryRequest:
    state = {
        "sides": [
            {
                "pokemon": [
                    {
                        "set": {
                            "species": "Snorlax",
                            "evs": {
                                "hp": 2,
                                "atk": 0,
                                "def": 0,
                                "spa": 32,
                                "spd": 0,
                                "spe": 32,
                            },
                        }
                    },
                    {
                        "set": {
                            "species": "Shuckle",
                            "evs": {
                                "hp": 32,
                                "atk": 0,
                                "def": 32,
                                "spa": 0,
                                "spd": 2,
                                "spe": 0,
                            },
                        }
                    },
                ]
            },
            {"pokemon": [{"set": {"species": "Indeedee-F", "evs": {}}}]},
        ]
    }
    checkpoint = {
        "turn": 1,
        "opponent": {
            "revealed": [
                {"species": "Snorlax", "seen": True},
                {"species": "Shuckle", "seen": False},
            ]
        },
    }
    return RecoveryRequest(
        checkpoint_particles=(
            BeliefParticle(state, 1.0, world_id="stat-parent"),
        ),
        checkpoint_public_view=checkpoint,
        observations=(
            RecoveryObservation(
                ai_choice="move ai",
                resolved_opponent_choice="move human",
                previous_public_view=checkpoint,
                public_view={"turn": 2},
            ),
        ),
        ai_side="p2",
        previews={"p1": ["Snorlax", "Shuckle"], "p2": ["Indeedee-F"]},
    )


def test_bounded_stat_generator_only_broadens_seen_opponent_non_hp_points() -> None:
    request = _stat_request()
    before = copy.deepcopy(request.checkpoint_particles[0].state)
    generator = BoundedOpponentStatProposalGenerator(max_proposals=64)

    proposals = generator.generate(request)

    assert proposals
    assert len(proposals) <= 64
    assert all(proposal.pokemon_index == 0 for proposal in proposals)
    assert all(proposal.species == "Snorlax" for proposal in proposals)
    assert all(proposal.stat_point_dict["hp"] == 2 for proposal in proposals)
    assert all(
        max(proposal.stat_point_dict.values()) <= 32
        and sum(proposal.stat_point_dict.values()) <= 66
        for proposal in proposals
    )
    assert any(
        proposal.stat_point_dict
        == {
            "hp": 2,
            "atk": 32,
            "def": 0,
            "spa": 0,
            "spd": 0,
            "spe": 32,
        }
        for proposal in proposals
    )
    assert request.checkpoint_particles[0].state == before


def test_bounded_stat_generator_is_deterministic_and_honors_limit() -> None:
    request = _stat_request()
    generator = BoundedOpponentStatProposalGenerator(max_proposals=3)

    left = generator.generate(request)
    right = generator.generate(request)

    assert left == right
    assert len(left) == 3
    assert len({proposal.proposal_id for proposal in left}) == 3


class _MaterializationWorker:
    def materialize_recovery_stat_proposals(self, *, state, side, proposals):
        assert side == "p1"
        resolved = []
        for proposal in proposals:
            if proposal["proposal_id"] == "reject":
                resolved.append(
                    {"proposal_id": proposal["proposal_id"], "rejected": "unsafe"}
                )
                continue
            candidate = copy.deepcopy(state)
            candidate["materialized"] = proposal["proposal_id"]
            resolved.append(
                {"proposal_id": proposal["proposal_id"], "state": candidate}
            )
        return resolved


def test_stat_materialization_preserves_parent_identity_and_reports_rejections() -> None:
    request = _stat_request()
    proposals = (
        OpponentStatProposal(
            proposal_id="keep",
            parent_particle_index=0,
            pokemon_index=0,
            species="Snorlax",
            stat_points=(
                ("hp", 2),
                ("atk", 32),
                ("def", 0),
                ("spa", 0),
                ("spd", 0),
                ("spe", 32),
            ),
            changed_hidden_dimensions=(
                "opponent.snorlax.stat_points.atk",
                "opponent.snorlax.stat_points.spa",
            ),
        ),
        OpponentStatProposal(
            proposal_id="reject",
            parent_particle_index=0,
            pokemon_index=0,
            species="Snorlax",
            stat_points=(
                ("hp", 2),
                ("atk", 16),
                ("def", 0),
                ("spa", 16),
                ("spd", 0),
                ("spe", 32),
            ),
            changed_hidden_dimensions=(
                "opponent.snorlax.stat_points.atk",
                "opponent.snorlax.stat_points.spa",
            ),
        ),
    )

    report = materialize_stat_proposals(
        _MaterializationWorker(),
        request=request,
        proposals=proposals,
    )

    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.candidate_id == "keep"
    assert candidate.parent_particle_index == 0
    assert candidate.particle.world_id == "stat-parent"
    assert candidate.particle.weight == 1.0
    assert candidate.particle.state["materialized"] == "keep"
    assert candidate.source == "bounded-opponent-stat-points"
    assert len(report.failures) == 1
    assert report.failures[0].proposal.proposal_id == "reject"
    assert report.failures[0].reason == "unsafe"


def test_recovery_requires_checkpoint_and_complete_history_replay() -> None:
    request = _request()
    checkpoint = request.checkpoint_public_view
    bad_checkpoint = {
        "turn": 1,
        "opponent": {"active": [{"species": "Snorlax", "hp_percent": 90}]},
    }
    first = request.observations[0].public_view
    second = request.observations[1].public_view
    wrong_second = {
        "turn": 3,
        "opponent": {"active": [{"species": "Snorlax", "hp_percent": 61}]},
    }
    worker = _RecoveryWorker(
        checkpoints={
            "good": checkpoint,
            "late-mismatch": checkpoint,
            "checkpoint-mismatch": bad_checkpoint,
        },
        transitions={
            ("good", 1): first,
            ("good", 2): second,
            ("late-mismatch", 1): first,
            ("late-mismatch", 2): wrong_second,
        },
    )
    candidates = (
        RecoveryCandidate(
            "good",
            0,
            BeliefParticle(
                {"id": "good", "sides": [{"foe": "variant"}, {"own": "fixed"}]},
                1.0,
                world_id="good",
            ),
            source="test-generator",
            changed_hidden_dimensions=("opponent.atk",),
        ),
        RecoveryCandidate(
            "late-mismatch",
            0,
            BeliefParticle(
                {
                    "id": "late-mismatch",
                    "sides": [{"foe": "variant"}, {"own": "fixed"}],
                },
                1.0,
                world_id="late-mismatch",
            ),
            source="test-generator",
            changed_hidden_dimensions=("opponent.atk",),
        ),
        RecoveryCandidate(
            "checkpoint-mismatch",
            0,
            BeliefParticle(
                {
                    "id": "checkpoint-mismatch",
                    "sides": [{"foe": "variant"}, {"own": "fixed"}],
                },
                1.0,
                world_id="checkpoint-mismatch",
            ),
            source="test-generator",
            changed_hidden_dimensions=("opponent.hp",),
        ),
    )

    report = validate_recovery_candidates(
        worker,
        request=request,
        candidates=candidates,
        rng_seeds_by_observation=(("seed-1",), ("seed-2",)),
    )

    by_id = {
        result.candidate.candidate_id: result
        for result in report.candidate_results
    }
    assert by_id["good"].status is RecoveryCandidateStatus.VALIDATED
    assert by_id["good"].observations_replayed == 2
    assert len(by_id["good"].final_particles) == 1

    assert (
        by_id["late-mismatch"].status
        is RecoveryCandidateStatus.REPLAY_MISMATCH
    )
    assert by_id["late-mismatch"].observations_replayed == 1
    assert by_id["late-mismatch"].final_particles == ()

    assert (
        by_id["checkpoint-mismatch"].status
        is RecoveryCandidateStatus.CHECKPOINT_MISMATCH
    )
    assert by_id["checkpoint-mismatch"].checkpoint_compatible is False
    assert by_id["checkpoint-mismatch"].generated_branches == 0

    assert [result.candidate.candidate_id for result in report.validated_candidates] == [
        "good"
    ]
    assert len(report.validated_particles) == 1


def test_recovery_rejects_changes_to_ai_known_exact_state() -> None:
    request = _request()
    worker = _RecoveryWorker(
        checkpoints={"own-mutated": request.checkpoint_public_view},
        transitions={},
    )
    candidate = RecoveryCandidate(
        "own-mutated",
        0,
        BeliefParticle(
            {
                "id": "own-mutated",
                "sides": [{"foe": "variant"}, {"own": "changed"}],
            },
            1.0,
            world_id="own-mutated",
        ),
        source="test-generator",
        changed_hidden_dimensions=("player.known-state",),
    )

    report = validate_recovery_candidates(
        worker,
        request=request,
        candidates=(candidate,),
        rng_seeds_by_observation=(("seed-1",), ("seed-2",)),
    )

    result = report.candidate_results[0]
    assert result.status is RecoveryCandidateStatus.KNOWN_STATE_MISMATCH
    assert result.generated_branches == 0
    assert worker.branch_calls == 0


def test_recovery_rejects_noncontiguous_public_history() -> None:
    request = _request()
    broken = RecoveryRequest(
        checkpoint_particles=request.checkpoint_particles,
        checkpoint_public_view=request.checkpoint_public_view,
        observations=(
            request.observations[0],
            RecoveryObservation(
                ai_choice="move ai",
                resolved_opponent_choice="move human",
                previous_public_view={"turn": 999},
                public_view=request.observations[1].public_view,
            ),
        ),
        ai_side="p2",
        previews=request.previews,
    )
    worker = _RecoveryWorker(checkpoints={}, transitions={})

    with pytest.raises(ValueError, match="not contiguous"):
        validate_recovery_candidates(
            worker,
            request=broken,
            candidates=(),
            rng_seeds_by_observation=(("seed-1",), ("seed-2",)),
        )


def test_recovery_candidate_ids_must_be_unique() -> None:
    request = _request()
    worker = _RecoveryWorker(
        checkpoints={"a": request.checkpoint_public_view},
        transitions={},
    )
    candidate = RecoveryCandidate(
        "duplicate",
        0,
        BeliefParticle(
            {"id": "a", "sides": [{"foe": "variant"}, {"own": "fixed"}]},
            1.0,
            world_id="a",
        ),
        source="test-generator",
    )

    with pytest.raises(ValueError, match="ids must be unique"):
        validate_recovery_candidates(
            worker,
            request=request,
            candidates=(candidate, candidate),
            rng_seeds_by_observation=(("seed-1",), ("seed-2",)),
        )


def test_recovery_requires_rng_coverage_for_every_observation() -> None:
    request = _request()
    worker = _RecoveryWorker(checkpoints={}, transitions={})

    with pytest.raises(ValueError, match="every recovery observation"):
        validate_recovery_candidates(
            worker,
            request=request,
            candidates=(),
            rng_seeds_by_observation=(("seed-1",),),
        )
