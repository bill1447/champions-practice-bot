from __future__ import annotations

import copy

import pytest

import champions_practice.recovery as recovery
from champions_practice.observation_beliefs import BeliefParticle
from champions_practice.recovery import (
    BoundedOpponentStatProposalGenerator,
    OpponentStatProposal,
    RecoveryCandidateStatus,
    RecoveryObservation,
    RecoveryRequest,
    validate_stat_recovery_proposals,
)


def _parent_state() -> dict:
    return {
        "test_step": 0,
        "turn": 1,
        "queue": [],
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
                        },
                        "baseStoredStats": {
                            "hp": 200,
                            "atk": 100,
                            "def": 100,
                            "spa": 132,
                            "spd": 100,
                            "spe": 132,
                        },
                        "storedStats": {
                            "atk": 100,
                            "def": 100,
                            "spa": 132,
                            "spd": 100,
                            "spe": 132,
                        },
                        "speed": 132,
                        "hp": 200,
                        "maxhp": 200,
                        "timesAttacked": 0,
                        "moveSlots": [{"id": "bodyslam", "pp": 24}],
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
            {
                "pokemon": [
                    {
                        "set": {"species": "Indeedee-F", "evs": {}},
                        "hp": 180,
                        "maxhp": 180,
                    }
                ]
            },
        ],
    }


def _checkpoint() -> dict:
    return {
        "turn": 1,
        "opponent": {
            "active": [{"species": "Snorlax", "hp_percent": 100}],
            "revealed": [
                {"species": "Snorlax", "seen": True},
                {"species": "Shuckle", "seen": False},
            ],
        },
    }


def _first_view() -> dict:
    return {
        "turn": 2,
        "opponent": {"active": [{"species": "Snorlax", "hp_percent": 80}]},
    }


def _second_view() -> dict:
    return {
        "turn": 3,
        "opponent": {"active": [{"species": "Snorlax", "hp_percent": 60}]},
    }


def _request() -> RecoveryRequest:
    checkpoint = _checkpoint()
    first = _first_view()
    return RecoveryRequest(
        checkpoint_particles=(
            BeliefParticle(
                _parent_state(),
                1.0,
                world_id="stat-parent",
                history_id="checkpoint",
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
                public_view=_second_view(),
            ),
        ),
        ai_side="p2",
        previews={"p1": ["Snorlax", "Shuckle"], "p2": ["Indeedee-F"]},
    )


def _proposal(
    proposal_id: str,
    *,
    atk: int,
    defense: int = 0,
    spa: int,
) -> OpponentStatProposal:
    changed = []
    if atk != 0:
        changed.append("atk")
    if defense != 0:
        changed.append("def")
    if spa != 32:
        changed.append("spa")
    return OpponentStatProposal(
        proposal_id=proposal_id,
        parent_particle_index=0,
        pokemon_index=0,
        species="Snorlax",
        stat_points=(
            ("hp", 2),
            ("atk", atk),
            ("def", defense),
            ("spa", spa),
            ("spd", 0),
            ("spe", 32),
        ),
        changed_hidden_dimensions=tuple(
            f"opponent.snorlax.stat_points.{stat}" for stat in changed
        ),
    )


class _TypedRecoveryWorker:
    def __init__(
        self,
        *,
        hostile_delta: str | None = None,
        reject_ids: set[str] | None = None,
    ) -> None:
        self.hostile_delta = hostile_delta
        self.reject_ids = reject_ids or set()
        self.branch_calls = 0

    def materialize_recovery_stat_proposals(self, *, state, side, proposals):
        assert side == "p1"
        resolved = []
        for proposal in proposals:
            proposal_id = proposal["proposal_id"]
            if proposal_id in self.reject_ids:
                resolved.append(
                    {"proposal_id": proposal_id, "rejected": "unsafe-fixture"}
                )
                continue

            candidate = copy.deepcopy(state)
            target = candidate["sides"][0]["pokemon"][proposal["pokemon_index"]]
            points = dict(proposal["stat_points"])
            target["set"]["evs"] = points
            target["baseStoredStats"] = {
                "hp": 200,
                "atk": 100 + points["atk"],
                "def": 100 + points["def"],
                "spa": 100 + points["spa"],
                "spd": 100 + points["spd"],
                "spe": 100 + points["spe"],
            }
            target["storedStats"] = {
                stat: target["baseStoredStats"][stat]
                for stat in ("atk", "def", "spa", "spd", "spe")
            }
            target["speed"] = target["storedStats"]["spe"]

            if self.hostile_delta == "timesAttacked":
                target["timesAttacked"] = 99
            elif self.hostile_delta == "queue":
                candidate["queue"] = [{"choice": "forged"}]
            elif self.hostile_delta == "pp":
                target["moveSlots"][0]["pp"] = 1

            resolved.append({"proposal_id": proposal_id, "state": candidate})
        return resolved

    def state_view(self, *, state, side, previews=None):
        assert side == "p2"
        points = state["sides"][0]["pokemon"][0]["set"]["evs"]
        if points["def"] == 32:
            return {
                "turn": 1,
                "opponent": {
                    "active": [{"species": "Snorlax", "hp_percent": 90}],
                    "revealed": [{"species": "Snorlax", "seen": True}],
                },
            }
        return _checkpoint()

    def validate_choices(self, *, state, side, candidates):
        assert side == "p1"
        return list(candidates)

    def legal_choices(self, *, state, side):
        return ["move human"]

    def branch_many(self, *, state, branches):
        self.branch_calls += 1
        points = state["sides"][0]["pokemon"][0]["set"]["evs"]
        step = int(state.get("test_step", 0)) + 1
        next_state = copy.deepcopy(state)
        next_state["test_step"] = step

        if points["atk"] == 32:
            view = _first_view() if step == 1 else _second_view()
        elif points["atk"] == 16:
            view = (
                _first_view()
                if step == 1
                else {
                    "turn": 3,
                    "opponent": {
                        "active": [{"species": "Snorlax", "hp_percent": 61}]
                    },
                }
            )
        else:
            view = {
                "turn": step + 1,
                "opponent": {
                    "active": [{"species": "Snorlax", "hp_percent": 95}]
                },
            }

        return [
            {"state": copy.deepcopy(next_state), "view": copy.deepcopy(view)}
            for _branch in branches
        ]


def test_bounded_stat_generator_only_broadens_seen_opponent_non_hp_points() -> None:
    request = _request()
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
    request = _request()
    generator = BoundedOpponentStatProposalGenerator(max_proposals=3)

    left = generator.generate(request)
    right = generator.generate(request)

    assert left == right
    assert len(left) == 3
    assert len({proposal.proposal_id for proposal in left}) == 3


def test_typed_stat_authority_requires_complete_suffix_replay() -> None:
    request = _request()
    worker = _TypedRecoveryWorker()
    proposals = (
        _proposal("good", atk=32, spa=0),
        _proposal("late-mismatch", atk=16, spa=16),
        _proposal("checkpoint-mismatch", atk=0, defense=32, spa=0),
    )

    report = validate_stat_recovery_proposals(
        worker,
        request=request,
        proposals=proposals,
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
    assert by_id["checkpoint-mismatch"].generated_branches == 0
    assert [result.candidate.candidate_id for result in report.validated_candidates] == [
        "good"
    ]


@pytest.mark.parametrize("hostile_delta", ["timesAttacked", "queue", "pp"])
def test_typed_stat_authority_rejects_non_stat_checkpoint_edits(
    hostile_delta: str,
) -> None:
    request = _request()
    worker = _TypedRecoveryWorker(hostile_delta=hostile_delta)

    report = validate_stat_recovery_proposals(
        worker,
        request=request,
        proposals=(_proposal("hostile", atk=32, spa=0),),
        rng_seeds_by_observation=(("seed-1",), ("seed-2",)),
    )

    result = report.candidate_results[0]
    assert result.status is RecoveryCandidateStatus.UNAUTHORIZED_STATE_DELTA
    assert result.generated_branches == 0
    assert result.final_particles == ()
    assert worker.branch_calls == 0


def test_typed_stat_authority_reports_materialization_rejections() -> None:
    request = _request()
    worker = _TypedRecoveryWorker(reject_ids={"reject"})

    report = validate_stat_recovery_proposals(
        worker,
        request=request,
        proposals=(_proposal("reject", atk=32, spa=0),),
        rng_seeds_by_observation=(("seed-1",), ("seed-2",)),
    )

    assert report.candidate_results == ()
    assert len(report.materialization_failures) == 1
    assert report.materialization_failures[0].proposal.proposal_id == "reject"
    assert report.materialization_failures[0].reason == "unsafe-fixture"


def test_typed_stat_authority_has_no_public_raw_candidate_input() -> None:
    assert not hasattr(recovery, "validate_recovery_candidates")
    assert not hasattr(recovery, "materialize_stat_proposals")
    assert not hasattr(recovery, "RecoveryCandidate")


def test_recovery_request_detects_parent_mutation_before_authority() -> None:
    request = _request()
    request.checkpoint_particles[0].state["sides"][0]["pokemon"][0][
        "timesAttacked"
    ] = 99

    with pytest.raises(ValueError, match="authority inputs were mutated"):
        validate_stat_recovery_proposals(
            _TypedRecoveryWorker(),
            request=request,
            proposals=(_proposal("mutated-parent", atk=32, spa=0),),
            rng_seeds_by_observation=(("seed-1",), ("seed-2",)),
        )


def test_typed_stat_proposal_must_match_seen_parent_species() -> None:
    request = _request()
    proposal = OpponentStatProposal(
        proposal_id="wrong-species",
        parent_particle_index=0,
        pokemon_index=0,
        species="Shuckle",
        stat_points=(
            ("hp", 2),
            ("atk", 32),
            ("def", 0),
            ("spa", 0),
            ("spd", 0),
            ("spe", 32),
        ),
        changed_hidden_dimensions=(
            "opponent.shuckle.stat_points.atk",
            "opponent.shuckle.stat_points.spa",
        ),
    )

    with pytest.raises(ValueError, match="species does not match parent"):
        validate_stat_recovery_proposals(
            _TypedRecoveryWorker(),
            request=request,
            proposals=(proposal,),
            rng_seeds_by_observation=(("seed-1",), ("seed-2",)),
        )


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

    with pytest.raises(ValueError, match="not contiguous"):
        validate_stat_recovery_proposals(
            _TypedRecoveryWorker(),
            request=broken,
            proposals=(),
            rng_seeds_by_observation=(("seed-1",), ("seed-2",)),
        )


def test_stat_proposal_ids_must_be_unique() -> None:
    request = _request()
    proposal = _proposal("duplicate", atk=32, spa=0)

    with pytest.raises(ValueError, match="proposal ids must be unique"):
        validate_stat_recovery_proposals(
            _TypedRecoveryWorker(),
            request=request,
            proposals=(proposal, proposal),
            rng_seeds_by_observation=(("seed-1",), ("seed-2",)),
        )


def test_recovery_requires_rng_coverage_for_every_observation() -> None:
    request = _request()

    with pytest.raises(ValueError, match="every recovery observation"):
        validate_stat_recovery_proposals(
            _TypedRecoveryWorker(),
            request=request,
            proposals=(),
            rng_seeds_by_observation=(("seed-1",),),
        )
