from __future__ import annotations

import copy
import math

import pytest

from champions_practice.reachability import (
    FINITE_TRANSITION_RANDOMNESS_DOMAIN,
    PUBLIC_OBSERVATION_SCHEMA_VERSION,
    PublicReachabilityStep,
    ReachabilityCoverage,
    ReachabilityResult,
    ReachabilityStatus,
    evaluate_deterministic_public_transition,
    finite_public_transition_reachability,
    public_reachability_observation_issue,
    witness_public_observation_sequence,
)
from champions_practice.search_worker import ShowdownRequestError


def _coverage(
    *,
    outcomes_examined: int = 4,
    randomness_exhaustive: bool = False,
    sequential_context_complete: bool = False,
) -> ReachabilityCoverage:
    return ReachabilityCoverage(
        sequential_context_fingerprint="sha256:ordered-transition-context",
        transitions_covered=2,
        outcomes_examined=outcomes_examined,
        randomness_domains=("damage-roll", "critical-hit"),
        randomness_exhaustive=randomness_exhaustive,
        sequential_context_complete=sequential_context_complete,
    )


def test_witness_is_positive_reachability_evidence_without_exclusion_authority():
    result = ReachabilityResult.witnessed(
        coverage=_coverage(outcomes_examined=1),
        witness_ids=("showdown-branch-17",),
    )

    assert result.status is ReachabilityStatus.WITNESSED
    assert result.establishes_reachability
    assert not result.establishes_impossibility
    assert result.conclusive


def test_bounded_sampling_miss_remains_unresolved():
    result = ReachabilityResult.unresolved(
        reason="bounded RNG search found no witness",
        coverage=_coverage(outcomes_examined=128),
    )

    assert result.status is ReachabilityStatus.UNRESOLVED
    assert not result.establishes_reachability
    assert not result.establishes_impossibility
    assert not result.conclusive


def test_exhaustive_disproof_requires_full_randomness_and_sequential_context():
    incomplete_randomness = _coverage(
        randomness_exhaustive=False,
        sequential_context_complete=True,
    )
    with pytest.raises(ValueError, match="exhaustive randomness"):
        ReachabilityResult.exhaustively_disproved(
            coverage=incomplete_randomness,
        )

    incomplete_history = _coverage(
        randomness_exhaustive=True,
        sequential_context_complete=False,
    )
    with pytest.raises(ValueError, match="full sequential transition context"):
        ReachabilityResult.exhaustively_disproved(
            coverage=incomplete_history,
        )


def test_exhaustive_disproof_is_the_only_negative_exclusion_evidence():
    result = ReachabilityResult.exhaustively_disproved(
        coverage=_coverage(
            outcomes_examined=256,
            randomness_exhaustive=True,
            sequential_context_complete=True,
        )
    )

    assert result.status is ReachabilityStatus.EXHAUSTIVELY_DISPROVED
    assert result.establishes_impossibility
    assert not result.establishes_reachability
    assert result.conclusive


def test_exhaustive_disproof_requires_at_least_one_examined_outcome():
    with pytest.raises(ValueError, match="at least one outcome"):
        ReachabilityResult.exhaustively_disproved(
            coverage=_coverage(
                outcomes_examined=0,
                randomness_exhaustive=True,
                sequential_context_complete=True,
            )
        )


def test_non_witness_result_cannot_carry_witness_ids():
    with pytest.raises(ValueError, match="cannot carry witnesses"):
        ReachabilityResult(
            status=ReachabilityStatus.UNRESOLVED,
            coverage=_coverage(),
            witness_ids=("forged-witness",),
            reason="sampling exhausted",
        )


@pytest.mark.parametrize(
    "status",
    (ReachabilityStatus.UNRESOLVED, ReachabilityStatus.UNSUPPORTED),
)
def test_inconclusive_statuses_require_an_explicit_reason(status: ReachabilityStatus):
    with pytest.raises(ValueError, match="require a reason"):
        ReachabilityResult(status=status, coverage=_coverage())


def test_unsupported_mechanics_are_not_negative_evidence():
    result = ReachabilityResult.unsupported(
        reason="mechanic has no authoritative enumerator",
        coverage=_coverage(outcomes_examined=3),
    )

    assert result.status is ReachabilityStatus.UNSUPPORTED
    assert not result.establishes_reachability
    assert not result.establishes_impossibility
    assert not result.conclusive


def test_inconclusive_result_cannot_claim_complete_exhaustive_coverage():
    with pytest.raises(ValueError, match="conclusive result"):
        ReachabilityResult.unresolved(
            reason="timeout after enumeration",
            coverage=_coverage(
                outcomes_examined=256,
                randomness_exhaustive=True,
                sequential_context_complete=True,
            ),
        )


def test_coverage_rejects_wrong_observation_schema():
    with pytest.raises(ValueError, match="unsupported observation schema"):
        ReachabilityCoverage(
            sequential_context_fingerprint="sha256:context",
            transitions_covered=1,
            observation_schema="showdown-player-view-v0",
            outcomes_examined=1,
        )


def test_coverage_rejects_duplicate_randomness_domains():
    with pytest.raises(ValueError, match="must be unique"):
        ReachabilityCoverage(
            sequential_context_fingerprint="sha256:context",
            transitions_covered=1,
            outcomes_examined=1,
            randomness_domains=("damage-roll", "damage-roll"),
        )


def _valid_public_view(spec: dict | None = None) -> dict:
    spec = spec or {}
    turn = spec.get("turn", 2)
    marker = spec.get("marker")
    winner = spec.get("winner", marker)

    opponent_active = []
    opponent_preview = []
    opponent_revealed = []
    raw_opponent = spec.get("opponent")
    default_species = ("Pikachu", "Raichu")
    if isinstance(raw_opponent, dict) and isinstance(raw_opponent.get("active"), list):
        for index, pokemon in enumerate(raw_opponent["active"]):
            if pokemon is None:
                opponent_active.append(None)
                continue
            species = pokemon.get(
                "species",
                default_species[min(index, len(default_species) - 1)],
            )
            base_species = pokemon.get("base_species", species)
            hp_percent = pokemon.get("hp_percent", 100)
            fainted = pokemon.get("fainted", False)
            status = pokemon.get("status")
            opponent_active.append(
                {
                    "species": species,
                    "base_species": base_species,
                    "hp_percent": hp_percent,
                    "fainted": fainted,
                    "status": status,
                    "boosts": pokemon.get(
                        "boosts",
                        {
                            "atk": 0,
                            "def": 0,
                            "spa": 0,
                            "spd": 0,
                            "spe": 0,
                            "accuracy": 0,
                            "evasion": 0,
                        },
                    ),
                }
            )
            if base_species not in opponent_preview:
                opponent_preview.append(base_species)
                opponent_revealed.append(
                    {
                        "species": base_species,
                        "moves": [],
                        "items": [],
                        "abilities": [],
                        "hp_percent": hp_percent,
                        "status": status,
                        "fainted": fainted,
                        "seen": True,
                    }
                )

    while len(opponent_active) < 2:
        opponent_active.append(None)

    view = {
        "turn": turn,
        "phase": "move",
        "opponent_last_actions": [],
        "public_execution_delta": {"turn": None, "actions": []},
        "public_event_delta": {"turn": None, "events": [], "unsupported": []},
        "ended": False,
        "winner": winner,
        "field": {"weather": None, "terrain": None, "pseudo_weather": []},
        "request": {
            "wait": True,
            "side": {"name": "Player", "id": "p1", "pokemon": []},
        },
        "player": {
            "name": "Player",
            "active": [None, None],
            "active_details": [None, None],
            "side_conditions": [],
            "team": [],
        },
        "opponent": {
            "name": "Opponent",
            "preview_species": opponent_preview,
            "side_conditions": [],
            "active": opponent_active,
            "revealed": opponent_revealed,
        },
    }
    if "public_event_delta" in spec:
        view["public_event_delta"] = copy.deepcopy(spec["public_event_delta"])
    if "public_execution_delta" in spec:
        view["public_execution_delta"] = copy.deepcopy(
            spec["public_execution_delta"]
        )
    return view


class _FakeReachabilityWorker:
    def __init__(
        self,
        outcomes=None,
        *,
        timeout=False,
        rejected_nodes=(),
        rng_draw_counts=None,
        normalize_views=True,
    ):
        self.outcomes = outcomes or {}
        self.timeout = timeout
        self.rejected_nodes = set(rejected_nodes)
        self.rng_draw_counts = rng_draw_counts or {}
        self.normalize_views = normalize_views
        self.calls = 0

    def branch_many(self, *, state, branches):
        self.calls += 1
        if self.timeout:
            raise TimeoutError("synthetic worker timeout")
        if state["node"] in self.rejected_nodes:
            raise ShowdownRequestError(
                "branch_many",
                "[Invalid choice] synthetic rejected parent",
            )
        resolved = []
        for index, branch in enumerate(branches):
            key = (state["node"], branch.get("rng_seed"))
            next_node, view = self.outcomes[key]
            result = {
                "index": index,
                "state": {"node": next_node},
                "view": (
                    _valid_public_view(view)
                    if self.normalize_views
                    else copy.deepcopy(view)
                ),
            }
            if branch.get("include_rng_draw_count") is True:
                result["rng_draw_count"] = self.rng_draw_counts.get(key, 0)
            resolved.append(result)
        return resolved


def _public_step(view, *, seeds=("seed-a",), p1_choice="move a", p2_choice="move b"):
    return PublicReachabilityStep(
        p1_choice=p1_choice,
        p2_choice=p2_choice,
        expected_public_view=_valid_public_view(view),
        rng_seeds=seeds,
    )


class _FakeFiniteTransitionWorker:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def enumerate_finite_transition(self, **kwargs):
        self.calls.append(kwargs)
        return copy.deepcopy(self.response)


def _finite_response(
    *,
    witnessed: bool = False,
    exhaustive: bool = False,
    leaves: int = 4,
    reason: str | None = None,
):
    response = {
        "domain": FINITE_TRANSITION_RANDOMNESS_DOMAIN,
        "exhaustive": exhaustive,
        "witnessed": witnessed,
        "leaves_examined": leaves,
        "decision_nodes": 7,
        "max_depth": 3,
        "reason": reason,
    }
    if witnessed:
        response["witness"] = {
            "state": {"node": "child"},
            "view": _valid_public_view({"turn": 2, "marker": "target"}),
            "member_lineage": {"p1": [0, 1, 2, 3], "p2": [0, 1, 2, 3]},
            "rng_seed": "sodium,finite-test-witness",
            "random_path": [
                {
                    "kind": "chance",
                    "value": True,
                    "metadata": {"numerator": 1, "denominator": 2},
                }
            ],
        }
    return response


def test_finite_transition_witness_has_positive_authority_and_child_state():
    worker = _FakeFiniteTransitionWorker(
        _finite_response(witnessed=True, leaves=3)
    )
    expected = _valid_public_view({"turn": 2, "marker": "target"})

    probe = finite_public_transition_reachability(
        worker,
        state={"node": "root"},
        side="p2",
        p1_choice="move protect, move trickroom",
        p2_choice="move direclaw +1, move imprison",
        expected_public_view=expected,
        max_leaves=4096,
    )

    assert probe.evidence.status is ReachabilityStatus.WITNESSED
    assert probe.evidence.establishes_reachability
    assert not probe.evidence.establishes_impossibility
    assert probe.child_state == {"node": "child"}
    assert probe.member_lineage == {
        "p1": [0, 1, 2, 3],
        "p2": [0, 1, 2, 3],
    }
    assert probe.leaves_examined == 3
    assert probe.random_path
    assert worker.calls[0]["expected_public_view"] == expected


def test_finite_transition_exhaustive_miss_is_negative_authority():
    worker = _FakeFiniteTransitionWorker(
        _finite_response(exhaustive=True, leaves=96)
    )

    probe = finite_public_transition_reachability(
        worker,
        state={"node": "root"},
        side="p2",
        p1_choice="move protect, move trickroom",
        p2_choice="move direclaw +1, move imprison",
        expected_public_view=_valid_public_view({"turn": 2}),
    )

    assert probe.evidence.status is ReachabilityStatus.EXHAUSTIVELY_DISPROVED
    assert probe.evidence.establishes_impossibility
    assert probe.evidence.coverage is not None
    assert probe.evidence.coverage.randomness_exhaustive
    assert probe.evidence.coverage.sequential_context_complete
    assert probe.evidence.coverage.randomness_domains == (
        FINITE_TRANSITION_RANDOMNESS_DOMAIN,
    )
    assert probe.child_state is None


def test_finite_transition_budget_exhaustion_remains_unresolved():
    worker = _FakeFiniteTransitionWorker(
        _finite_response(
            exhaustive=False,
            leaves=128,
            reason="finite stochastic branch budget exhausted",
        )
    )

    probe = finite_public_transition_reachability(
        worker,
        state={"node": "root"},
        side="p2",
        p1_choice="move protect, move trickroom",
        p2_choice="move direclaw +1, move imprison",
        expected_public_view=_valid_public_view({"turn": 2}),
    )

    assert probe.evidence.status is ReachabilityStatus.UNRESOLVED
    assert not probe.evidence.establishes_impossibility
    assert not probe.evidence.establishes_reachability
    assert probe.evidence.coverage is not None
    assert not probe.evidence.coverage.randomness_exhaustive


def test_showdown_witness_probe_preserves_sequential_parentage():
    first = {"turn": 2, "marker": "first"}
    second = {"turn": 3, "marker": "second"}
    worker = _FakeReachabilityWorker(
        {
            ("root", "seed-a"): ("dead", {"turn": 2, "marker": "wrong"}),
            ("root", "seed-b"): ("path", first),
            ("path", "seed-c"): ("done", second),
        }
    )

    result = witness_public_observation_sequence(
        worker,
        state={"node": "root"},
        side="p2",
        steps=(
            _public_step(first, seeds=("seed-a", "seed-b")),
            _public_step(second, seeds=("seed-c",)),
        ),
    )

    assert result.status is ReachabilityStatus.WITNESSED
    assert result.establishes_reachability
    assert not result.establishes_impossibility
    assert result.coverage is not None
    assert result.coverage.transitions_covered == 2
    assert result.coverage.outcomes_examined == 3
    assert result.coverage.sequential_context_complete
    assert not result.coverage.randomness_exhaustive
    assert worker.calls == 2


def test_showdown_witness_probe_never_cartesian_combines_incompatible_outcomes():
    first = {"turn": 2, "marker": "first"}
    combined = {
        "turn": 3,
        "opponent": {"active": [{"hp_percent": 50, "status": "par"}]},
    }
    worker = _FakeReachabilityWorker(
        {
            ("root", "seed-a"): ("path-a", first),
            ("root", "seed-b"): ("path-b", first),
            (
                "path-a",
                "seed-c",
            ): (
                "done-a",
                {
                    "turn": 3,
                    "opponent": {
                        "active": [{"hp_percent": 50, "status": None}]
                    },
                },
            ),
            (
                "path-b",
                "seed-c",
            ): (
                "done-b",
                {
                    "turn": 3,
                    "opponent": {
                        "active": [{"hp_percent": 80, "status": "par"}]
                    },
                },
            ),
        }
    )

    result = witness_public_observation_sequence(
        worker,
        state={"node": "root"},
        side="p2",
        steps=(
            _public_step(first, seeds=("seed-a", "seed-b")),
            _public_step(combined, seeds=("seed-c",)),
        ),
    )

    assert result.status is ReachabilityStatus.UNRESOLVED
    assert not result.establishes_reachability
    assert not result.establishes_impossibility
    assert result.coverage is not None
    assert result.coverage.outcomes_examined == 4


def test_bounded_showdown_miss_is_unresolved_not_impossible():
    target = {"turn": 2, "marker": "wanted"}
    worker = _FakeReachabilityWorker(
        {
            ("root", "seed-a"): ("done", {"turn": 2, "marker": "other"}),
        }
    )

    result = witness_public_observation_sequence(
        worker,
        state={"node": "root"},
        side="p1",
        steps=(_public_step(target),),
    )

    assert result.status is ReachabilityStatus.UNRESOLVED
    assert not result.conclusive
    assert not result.establishes_impossibility


def test_reachability_timeout_is_unresolved_not_negative_evidence():
    worker = _FakeReachabilityWorker(timeout=True)

    result = witness_public_observation_sequence(
        worker,
        state={"node": "root"},
        side="p1",
        steps=(_public_step({"turn": 2}),),
    )

    assert result.status is ReachabilityStatus.UNRESOLVED
    assert not result.establishes_impossibility
    assert worker.calls == 1


def test_unsupported_public_mechanics_fail_without_worker_authority():
    worker = _FakeReachabilityWorker()
    target = {
        "turn": 2,
        "public_event_delta": {"unsupported": ["future-mechanic"]},
    }

    result = witness_public_observation_sequence(
        worker,
        state={"node": "root"},
        side="p1",
        steps=(_public_step(target),),
    )

    assert result.status is ReachabilityStatus.UNSUPPORTED
    assert not result.establishes_impossibility
    assert worker.calls == 0


def test_branch_budget_exhaustion_cannot_become_exclusion_evidence():
    target = {"turn": 2, "marker": "wanted"}
    worker = _FakeReachabilityWorker(
        {
            ("root", "seed-a"): ("miss", {"turn": 2, "marker": "other"}),
            ("root", "seed-b"): ("hit", target),
        }
    )

    result = witness_public_observation_sequence(
        worker,
        state={"node": "root"},
        side="p1",
        steps=(_public_step(target, seeds=("seed-a", "seed-b")),),
        max_branches=1,
    )

    assert result.status is ReachabilityStatus.UNRESOLVED
    assert not result.establishes_impossibility
    assert worker.calls == 1


def test_reachability_step_rejects_raw_empty_commands():
    with pytest.raises(ValueError, match="non-empty exact command"):
        PublicReachabilityStep(
            p1_choice="",
            p2_choice="move b",
            expected_public_view={"turn": 2},
        )


def test_rejected_parent_path_does_not_block_a_different_sequential_witness():
    first = {"turn": 2, "marker": "first"}
    second = {"turn": 3, "marker": "second"}
    worker = _FakeReachabilityWorker(
        {
            ("root", "seed-a"): ("bad-parent", first),
            ("root", "seed-b"): ("good-parent", first),
            ("good-parent", "seed-c"): ("done", second),
        },
        rejected_nodes=("bad-parent",),
    )

    result = witness_public_observation_sequence(
        worker,
        state={"node": "root"},
        side="p2",
        steps=(
            _public_step(first, seeds=("seed-a", "seed-b")),
            _public_step(second, seeds=("seed-c",)),
        ),
    )

    assert result.status is ReachabilityStatus.WITNESSED
    assert result.establishes_reachability
    assert not result.establishes_impossibility



def test_zero_draw_mismatch_is_exhaustively_disproved():
    target = {"turn": 2, "marker": "wanted"}
    worker = _FakeReachabilityWorker(
        {
            ("root", "seed-a"): ("done", {"turn": 2, "marker": "actual"}),
        },
        rng_draw_counts={("root", "seed-a"): 0},
    )

    result = evaluate_deterministic_public_transition(
        worker,
        state={"node": "root"},
        side="p1",
        step=_public_step(target),
    )

    assert result.status is ReachabilityStatus.EXHAUSTIVELY_DISPROVED
    assert result.establishes_impossibility
    assert result.coverage is not None
    assert result.coverage.randomness_domains == ()
    assert result.coverage.randomness_exhaustive
    assert result.coverage.sequential_context_complete


def test_zero_draw_match_is_still_a_positive_witness():
    target = {"turn": 2, "marker": "wanted"}
    worker = _FakeReachabilityWorker(
        {("root", "seed-a"): ("done", target)},
        rng_draw_counts={("root", "seed-a"): 0},
    )

    result = evaluate_deterministic_public_transition(
        worker,
        state={"node": "root"},
        side="p2",
        step=_public_step(target),
    )

    assert result.status is ReachabilityStatus.WITNESSED
    assert result.establishes_reachability
    assert not result.establishes_impossibility
    assert result.coverage is not None
    assert result.coverage.randomness_exhaustive


def test_randomized_mismatch_remains_unresolved():
    target = {"turn": 2, "marker": "wanted"}
    worker = _FakeReachabilityWorker(
        {
            ("root", "seed-a"): ("done", {"turn": 2, "marker": "actual"}),
        },
        rng_draw_counts={("root", "seed-a"): 3},
    )

    result = evaluate_deterministic_public_transition(
        worker,
        state={"node": "root"},
        side="p1",
        step=_public_step(target),
    )

    assert result.status is ReachabilityStatus.UNRESOLVED
    assert not result.establishes_impossibility
    assert result.coverage is not None
    assert result.coverage.randomness_domains == ("showdown-prng-draw",)
    assert not result.coverage.randomness_exhaustive


def test_randomized_match_remains_a_valid_positive_witness():
    target = {"turn": 2, "marker": "wanted"}
    worker = _FakeReachabilityWorker(
        {("root", "seed-a"): ("done", target)},
        rng_draw_counts={("root", "seed-a"): 2},
    )

    result = evaluate_deterministic_public_transition(
        worker,
        state={"node": "root"},
        side="p1",
        step=_public_step(target),
    )

    assert result.status is ReachabilityStatus.WITNESSED
    assert result.establishes_reachability
    assert not result.establishes_impossibility
    assert result.coverage is not None
    assert not result.coverage.randomness_exhaustive


def test_deterministic_disproof_requires_exactly_one_seed():
    with pytest.raises(ValueError, match="exactly one"):
        evaluate_deterministic_public_transition(
            _FakeReachabilityWorker(),
            state={"node": "root"},
            side="p1",
            step=_public_step(
                {"turn": 2},
                seeds=("seed-a", "seed-b"),
            ),
        )


def test_deterministic_probe_requires_rng_draw_metadata():
    target = {"turn": 2}
    worker = _FakeReachabilityWorker(
        {("root", "seed-a"): ("done", target)}
    )

    original_branch_many = worker.branch_many

    def without_metadata(*, state, branches):
        result = original_branch_many(state=state, branches=branches)
        for branch in result:
            branch.pop("rng_draw_count", None)
        return result

    worker.branch_many = without_metadata

    with pytest.raises(RuntimeError, match="PRNG draw count"):
        evaluate_deterministic_public_transition(
            worker,
            state={"node": "root"},
            side="p1",
            step=_public_step(target),
        )



def test_reachability_schema_version_is_explicit_and_stable():
    assert PUBLIC_OBSERVATION_SCHEMA_VERSION == "showdown-player-view-v9"
    assert public_reachability_observation_issue(_valid_public_view()) is None


@pytest.mark.parametrize(
    "mutator",
    (
        lambda view: view.clear(),
        lambda view: view.pop("public_event_delta"),
        lambda view: view.__setitem__("public_event_delta", []),
        lambda view: view["public_event_delta"].__setitem__(
            "unsupported",
            "future-mechanic",
        ),
        lambda view: view["public_event_delta"].__setitem__(
            "unsupported",
            [""],
        ),
        lambda view: view.pop("public_execution_delta"),
        lambda view: view.__setitem__("unexpected_authority_field", True),
    ),
)
def test_malformed_expected_observation_is_nonconclusive(mutator):
    expected = _valid_public_view({"marker": "wanted"})
    mutator(expected)
    worker = _FakeReachabilityWorker(
        {("root", "seed-a"): ("done", {"turn": 2, "marker": "actual"})},
        rng_draw_counts={("root", "seed-a"): 0},
    )

    result = evaluate_deterministic_public_transition(
        worker,
        state={"node": "root"},
        side="p1",
        step=PublicReachabilityStep(
            p1_choice="move a",
            p2_choice="move b",
            expected_public_view=expected,
            rng_seeds=("seed-a",),
        ),
    )

    assert result.status is ReachabilityStatus.UNSUPPORTED
    assert not result.conclusive
    assert not result.establishes_impossibility
    assert worker.calls == 0


def test_valid_unsupported_expected_mechanics_remain_unsupported():
    expected = _valid_public_view()
    expected["public_event_delta"]["unsupported"] = ["future-mechanic"]
    worker = _FakeReachabilityWorker()

    result = evaluate_deterministic_public_transition(
        worker,
        state={"node": "root"},
        side="p1",
        step=PublicReachabilityStep(
            p1_choice="move a",
            p2_choice="move b",
            expected_public_view=expected,
            rng_seeds=("seed-a",),
        ),
    )

    assert result.status is ReachabilityStatus.UNSUPPORTED
    assert not result.conclusive
    assert worker.calls == 0


def test_malformed_worker_observation_cannot_become_witness_or_disproof():
    expected = _valid_public_view({"marker": "wanted"})
    worker = _FakeReachabilityWorker(
        {("root", "seed-a"): ("done", {})},
        rng_draw_counts={("root", "seed-a"): 0},
        normalize_views=False,
    )

    result = evaluate_deterministic_public_transition(
        worker,
        state={"node": "root"},
        side="p1",
        step=PublicReachabilityStep(
            p1_choice="move a",
            p2_choice="move b",
            expected_public_view=expected,
            rng_seeds=("seed-a",),
        ),
    )

    assert result.status is ReachabilityStatus.UNSUPPORTED
    assert not result.conclusive
    assert not result.establishes_impossibility


def test_worker_unsupported_mechanics_cannot_become_witness_or_disproof():
    expected = _valid_public_view({"marker": "wanted"})
    returned = _valid_public_view({"marker": "actual"})
    returned["public_event_delta"]["unsupported"] = ["future-mechanic"]
    worker = _FakeReachabilityWorker(
        {("root", "seed-a"): ("done", returned)},
        rng_draw_counts={("root", "seed-a"): 0},
        normalize_views=False,
    )

    result = evaluate_deterministic_public_transition(
        worker,
        state={"node": "root"},
        side="p1",
        step=PublicReachabilityStep(
            p1_choice="move a",
            p2_choice="move b",
            expected_public_view=expected,
            rng_seeds=("seed-a",),
        ),
    )

    assert result.status is ReachabilityStatus.UNSUPPORTED
    assert not result.conclusive
    assert not result.establishes_impossibility


def test_witness_sequence_rejects_malformed_expected_before_worker_call():
    worker = _FakeReachabilityWorker()
    result = witness_public_observation_sequence(
        worker,
        state={"node": "root"},
        side="p1",
        steps=(
            PublicReachabilityStep(
                p1_choice="move a",
                p2_choice="move b",
                expected_public_view={},
                rng_seeds=("seed-a",),
            ),
        ),
    )

    assert result.status is ReachabilityStatus.UNSUPPORTED
    assert not result.conclusive
    assert worker.calls == 0


def test_schema_version_changes_authority_context_fingerprint():
    expected = _valid_public_view({"marker": "wanted"})
    worker = _FakeReachabilityWorker(
        {("root", "seed-a"): ("done", {"turn": 2, "marker": "wanted"})},
        rng_draw_counts={("root", "seed-a"): 0},
    )
    result = evaluate_deterministic_public_transition(
        worker,
        state={"node": "root"},
        side="p1",
        step=PublicReachabilityStep(
            p1_choice="move a",
            p2_choice="move b",
            expected_public_view=expected,
            rng_seeds=("seed-a",),
        ),
    )

    assert result.status is ReachabilityStatus.WITNESSED
    assert result.coverage is not None
    assert result.coverage.observation_schema == PUBLIC_OBSERVATION_SCHEMA_VERSION
    assert result.coverage.sequential_context_fingerprint.startswith("sha256:")


def _nested_invalid_mutators():
    def truncated_damage(view):
        view["public_event_delta"]["events"].append(["-damage"])

    def unknown_mechanics_event(view):
        view["public_event_delta"]["events"].append(["-future-event", "p1a"])

    def impossible_selected_action(view):
        view["opponent_last_actions"].append(
            {
                "turn": 2,
                "slot": 999,
                "move": "definitelynotamove",
                "target": 999,
            }
        )

    def partial_move_variant(view):
        view["request"] = {
            "active": [
                {
                    "moves": [
                        {
                            "move": "Tackle",
                            "id": "tackle",
                            "maxpp": 56,
                            "target": "normal",
                            "disabled": False,
                        }
                    ]
                }
            ],
            "side": {"name": "Player", "id": "p1", "pokemon": []},
        }

    def nonfinite_hp(view):
        view["player"]["team"] = [
            {
                "species": "Pikachu",
                "hp": 100,
                "maxhp": 100,
                "hp_percent": float("nan"),
                "fainted": False,
                "status": None,
                "boosts": {
                    "atk": 0,
                    "def": 0,
                    "spa": 0,
                    "spd": 0,
                    "spe": 0,
                    "accuracy": 0,
                    "evasion": 0,
                },
                "item": None,
                "ability": None,
                "moves": ["Thunderbolt"],
                "speed": 100,
                "damaging_move_count": 1,
                "active": False,
            }
        ]

    def unknown_boost_dimension(view):
        view["opponent"]["active"] = [
            {
                "species": "Pikachu",
                "base_species": "Pikachu",
                "hp_percent": 100,
                "fainted": False,
                "status": None,
                "boosts": {"future-stat": 900},
            }
        ]

    return (
        truncated_damage,
        unknown_mechanics_event,
        impossible_selected_action,
        partial_move_variant,
        nonfinite_hp,
        unknown_boost_dimension,
    )


@pytest.mark.parametrize("mutator", _nested_invalid_mutators())
@pytest.mark.parametrize("evaluator", ("deterministic", "sequential"))
def test_nested_invalid_expected_evidence_fails_before_worker(mutator, evaluator):
    expected = _valid_public_view({"marker": "wanted"})
    mutator(expected)
    worker = _FakeReachabilityWorker(
        {("root", "seed-a"): ("done", {"turn": 2, "marker": "wanted"})},
        rng_draw_counts={("root", "seed-a"): 0},
    )
    step = PublicReachabilityStep(
        p1_choice="move a",
        p2_choice="move b",
        expected_public_view=expected,
        rng_seeds=("seed-a",),
    )

    if evaluator == "deterministic":
        result = evaluate_deterministic_public_transition(
            worker,
            state={"node": "root"},
            side="p1",
            step=step,
        )
    else:
        result = witness_public_observation_sequence(
            worker,
            state={"node": "root"},
            side="p1",
            steps=(step,),
        )

    assert result.status is ReachabilityStatus.UNSUPPORTED
    assert not result.conclusive
    assert not result.establishes_impossibility
    assert worker.calls == 0


@pytest.mark.parametrize("mutator", _nested_invalid_mutators())
@pytest.mark.parametrize("evaluator", ("deterministic", "sequential"))
@pytest.mark.parametrize("signature_mode", ("matching", "mismatching"))
def test_nested_invalid_worker_evidence_never_becomes_conclusive(
    mutator,
    evaluator,
    signature_mode,
):
    expected = _valid_public_view({"marker": "wanted"})
    returned = copy.deepcopy(expected)
    if signature_mode == "mismatching":
        returned["winner"] = "different-winner"
    mutator(returned)
    worker = _FakeReachabilityWorker(
        {("root", "seed-a"): ("done", returned)},
        rng_draw_counts={("root", "seed-a"): 0},
        normalize_views=False,
    )
    step = PublicReachabilityStep(
        p1_choice="move a",
        p2_choice="move b",
        expected_public_view=expected,
        rng_seeds=("seed-a",),
    )

    if evaluator == "deterministic":
        result = evaluate_deterministic_public_transition(
            worker,
            state={"node": "root"},
            side="p1",
            step=step,
        )
    else:
        result = witness_public_observation_sequence(
            worker,
            state={"node": "root"},
            side="p1",
            steps=(step,),
        )

    assert result.status is ReachabilityStatus.UNSUPPORTED
    assert not result.conclusive
    assert not result.establishes_impossibility


@pytest.mark.parametrize(
    "move",
    (
        {"move": "Recharge", "id": "recharge"},
        {"move": "Outrage", "id": "outrage"},
        {
            "move": "Struggle",
            "id": "struggle",
            "target": "randomNormal",
            "disabled": False,
        },
        {
            "move": "Tackle",
            "id": "tackle",
            "pp": 35,
            "maxpp": 56,
            "target": "normal",
            "disabled": False,
        },
    ),
)
def test_pinned_move_request_variants_remain_supported(move):
    view = _valid_public_view()
    view["request"] = {
        "active": [{"moves": [move]}, None],
        "side": {"name": "Player", "id": "p1", "pokemon": []},
    }

    assert public_reachability_observation_issue(view) is None


@pytest.mark.parametrize(
    "event",
    (
        ["-damage", "p1a", "100/200"],
        ["-status", "p1a", "par"],
        ["-boost", "p1a", "atk", "1"],
        ["-boost", "p1a", "atk", "1", "[from]:ability:intimidate"],
        ["-hitcount", "p2a", "2"],
        [
            "-hitcount",
            "p2a",
            "2",
            "[action]",
            "opponent",
            "1",
            "doublekick",
            "selected",
        ],
        ["-crit", "p2a"],
        ["-resisted", "p2a", "1"],
        ["-supereffective", "p2a", "2"],
        ["-weather", "raindance"],
    ),
)
def test_supported_canonical_mechanics_event_shapes_remain_valid(event):
    view = _valid_public_view()
    view["public_event_delta"]["turn"] = 1
    view["public_event_delta"]["events"] = [event]

    assert public_reachability_observation_issue(view) is None


def _v5_prior_invalid_mutators():
    def selected_slot_true(view):
        view["opponent_last_actions"].append(
            {"turn": 2, "slot": True, "move": "tackle", "target": 1}
        )

    def selected_slot_float(view):
        view["opponent_last_actions"].append(
            {"turn": 2, "slot": 1.0, "move": "tackle", "target": 1}
        )

    def selected_target_true(view):
        view["opponent_last_actions"].append(
            {"turn": 2, "slot": 1, "move": "tackle", "target": True}
        )

    def selected_target_float(view):
        view["opponent_last_actions"].append(
            {"turn": 2, "slot": 1, "move": "tackle", "target": 2.0}
        )

    def executed_slot_true(view):
        view["public_execution_delta"] = {
            "turn": 2,
            "actions": [
                {
                    "side": "player",
                    "slot": True,
                    "outcome": "executed",
                    "move": "tackle",
                    "source": "selected",
                    "provenance": [],
                    "effects": [],
                }
            ],
        }

    def bad_damage_condition(view):
        view["public_event_delta"]["events"].append(
            ["-damage", "p1a", "garbage"]
        )

    def incomplete_mega(view):
        view["public_event_delta"]["events"].append(
            ["-mega", "p1a", "gardevoir"]
        )

    def bad_status_actor(view):
        view["public_event_delta"]["events"].append(
            ["-status", "banana", "brn"]
        )

    def bad_tag_payload(view):
        view["public_event_delta"]["events"].append(
            ["-damage", "p1a", "50/100", "[from]:!!!"]
        )

    def bad_forme_modifier(view):
        view["public_event_delta"]["events"].append(
            ["-formechange", "p1a", "eiscue", "not canonical !!!"]
        )

    def padded_hitcount(view):
        view["public_event_delta"]["events"].append(
            ["-hitcount", "p1a", "01"]
        )

    def bad_execution_provenance(view):
        view["public_execution_delta"] = {
            "turn": 2,
            "actions": [
                {
                    "side": "player",
                    "slot": 1,
                    "outcome": "executed",
                    "move": "tackle",
                    "source": "called",
                    "provenance": ["[from]:!!!"],
                    "effects": [],
                }
            ],
        }

    def unknown_request_target(view):
        view["request"] = {
            "active": [
                {
                    "moves": [
                        {
                            "move": "Tackle",
                            "id": "tackle",
                            "pp": 35,
                            "maxpp": 56,
                            "target": "futureTarget",
                            "disabled": False,
                        }
                    ]
                }
            ],
            "side": {"name": "Player", "id": "p1", "pokemon": []},
        }

    def incomplete_boost_table(view):
        boosts = {
            "atk": 0,
            "def": 0,
            "spa": 0,
            "spd": 0,
            "spe": 0,
            "accuracy": 0,
            "evasion": 0,
        }
        boosts.pop("atk")
        view["player"]["team"] = [
            {
                "species": "Pikachu",
                "hp": 100,
                "maxhp": 100,
                "hp_percent": 100,
                "fainted": False,
                "status": None,
                "boosts": boosts,
                "item": None,
                "ability": None,
                "moves": ["Thunderbolt"],
                "speed": 100,
                "damaging_move_count": 1,
                "active": False,
            }
        ]
        view["request"] = {
            "wait": True,
            "side": {
                "name": "Player",
                "id": "p1",
                "pokemon": [
                    {
                        "ident": "p1: Pikachu",
                        "details": "Pikachu, L50",
                        "condition": "100/100",
                        "active": False,
                        "stats": {
                            "atk": 1,
                            "def": 1,
                            "spa": 1,
                            "spd": 1,
                            "spe": 1,
                        },
                        "moves": ["thunderbolt"],
                        "baseAbility": "static",
                        "item": "",
                        "pokeball": "",
                    }
                ],
            },
        }

    def inconsistent_roster(view):
        view["request"] = {
            "wait": True,
            "side": {
                "name": "Player",
                "id": "p1",
                "pokemon": [
                    {
                        "ident": "p1: Pikachu",
                        "details": "Pikachu, L50",
                        "condition": "100/100",
                        "active": False,
                        "stats": {
                            "atk": 1,
                            "def": 1,
                            "spa": 1,
                            "spd": 1,
                            "spe": 1,
                        },
                        "moves": ["tackle"],
                        "baseAbility": "static",
                        "item": "",
                        "pokeball": "",
                    }
                ],
            },
        }
        view["player"]["team"] = []

    return (
        selected_slot_true,
        selected_slot_float,
        selected_target_true,
        selected_target_float,
        executed_slot_true,
        bad_damage_condition,
        incomplete_mega,
        bad_status_actor,
        bad_tag_payload,
        bad_forme_modifier,
        padded_hitcount,
        bad_execution_provenance,
        unknown_request_target,
        incomplete_boost_table,
        inconsistent_roster,
    )


@pytest.mark.parametrize("mutator", _v5_prior_invalid_mutators())
@pytest.mark.parametrize("evaluator", ("deterministic", "sequential"))
def test_v5_prior_invalid_expected_evidence_is_preflight_unsupported(mutator, evaluator):
    expected = _valid_public_view({"marker": "wanted"})
    mutator(expected)
    worker = _FakeReachabilityWorker(
        {("root", "seed-a"): ("done", _valid_public_view({"marker": "wanted"}))},
        rng_draw_counts={("root", "seed-a"): 0},
        normalize_views=False,
    )
    step = PublicReachabilityStep(
        p1_choice="move a",
        p2_choice="move b",
        expected_public_view=expected,
        rng_seeds=("seed-a",),
    )

    if evaluator == "deterministic":
        result = evaluate_deterministic_public_transition(
            worker,
            state={"node": "root"},
            side="p1",
            step=step,
        )
    else:
        result = witness_public_observation_sequence(
            worker,
            state={"node": "root"},
            side="p1",
            steps=(step,),
        )

    assert result.status is ReachabilityStatus.UNSUPPORTED
    assert not result.conclusive
    assert not result.establishes_impossibility
    assert worker.calls == 0


@pytest.mark.parametrize("mutator", _v5_prior_invalid_mutators())
@pytest.mark.parametrize("evaluator", ("deterministic", "sequential"))
@pytest.mark.parametrize("signature_mode", ("matching", "mismatching"))
def test_v5_prior_invalid_worker_evidence_never_becomes_conclusive(
    mutator,
    evaluator,
    signature_mode,
):
    expected = _valid_public_view({"marker": "wanted"})
    returned = copy.deepcopy(expected)
    if signature_mode == "mismatching":
        returned["winner"] = "different-winner"
    mutator(returned)
    worker = _FakeReachabilityWorker(
        {("root", "seed-a"): ("done", returned)},
        rng_draw_counts={("root", "seed-a"): 0},
        normalize_views=False,
    )
    step = PublicReachabilityStep(
        p1_choice="move a",
        p2_choice="move b",
        expected_public_view=expected,
        rng_seeds=("seed-a",),
    )

    if evaluator == "deterministic":
        result = evaluate_deterministic_public_transition(
            worker,
            state={"node": "root"},
            side="p1",
            step=step,
        )
    else:
        result = witness_public_observation_sequence(
            worker,
            state={"node": "root"},
            side="p1",
            steps=(step,),
        )

    assert result.status is ReachabilityStatus.UNSUPPORTED
    assert not result.conclusive
    assert not result.establishes_impossibility


@pytest.mark.parametrize(
    "event",
    (
        ["-heal", "p1", "49/100", "[from]:move:revivalblessing"],
        ["-heal", "p2", "117/235", "[from]:move:revivalblessing"],
        ["-swapsideconditions"],
        ["-ohko"],
        ["-mega", "p1a", "gardevoir", "gardevoirite"],
    ),
)
def test_v5_prior_genuine_producer_event_variants_are_supported(event):
    view = _valid_public_view()
    view["public_event_delta"]["turn"] = 1
    view["public_event_delta"]["events"] = [event]
    assert public_reachability_observation_issue(view) is None


def _v5_complete_boosts():
    return {
        "atk": 0,
        "def": 0,
        "spa": 0,
        "spd": 0,
        "spe": 0,
        "accuracy": 0,
        "evasion": 0,
    }


def _v5_valid_own_mon(*, species="Pikachu", hp=100, maxhp=100, active=False):
    return {
        "species": species,
        "hp": hp,
        "maxhp": maxhp,
        "hp_percent": math.floor(((hp / maxhp) * 1000) + 0.5) / 10,
        "fainted": hp == 0,
        "status": None,
        "boosts": _v5_complete_boosts(),
        "item": None,
        "ability": "static",
        "moves": ["Thunderbolt"],
        "speed": 100,
        "damaging_move_count": 1,
        "active": active,
    }


def _v5_valid_request_mon(*, species="Pikachu", active=False):
    return {
        "ident": f"p1: {species}",
        "details": f"{species}, L50",
        "condition": "100/100",
        "active": active,
        "stats": {"atk": 1, "def": 1, "spa": 1, "spd": 1, "spe": 1},
        "moves": ["thunderbolt"],
        "baseAbility": "static",
        "ability": "static",
        "item": "",
        "pokeball": "pokeball",
        "commanding": False,
        "reviving": False,
    }


def _v5_semantic_valid_view():
    view = _valid_public_view({"marker": "wanted"})
    mon = _v5_valid_own_mon(active=True)
    view["player"]["active"] = ["Pikachu", None]
    view["player"]["active_details"] = [copy.deepcopy(mon), None]
    view["player"]["team"] = [copy.deepcopy(mon)]
    view["request"] = {
        "wait": True,
        "side": {
            "name": "Player",
            "id": "p1",
            "pokemon": [_v5_valid_request_mon(active=True)],
        },
    }
    return view


def _v5_semantic_invalid_mutators():
    def impossible_hp_fraction(view):
        view["public_event_delta"]["events"].append(
            ["-damage", "p1a", "101/100"]
        )

    def padded_hp(view):
        view["public_event_delta"]["events"].append(
            ["-damage", "p1a", "050/100"]
        )

    def unknown_event_status(view):
        view["public_event_delta"]["events"].append(
            ["-damage", "p1a", "50/100 mystery"]
        )

    def overlong_crit(view):
        view["public_event_delta"]["events"].append(
            ["-crit", "p1a", "extra"]
        )

    def invalid_miss_target(view):
        view["public_event_delta"]["events"].append(
            ["-miss", "p1a", "banana"]
        )

    def invalid_request_condition(view):
        view["request"]["side"]["pokemon"][0]["condition"] = "garbage"

    def noncanonical_request_id(view):
        view["request"]["side"]["pokemon"][0]["baseAbility"] = "Static!"

    def hp_exceeds_max(view):
        mon = view["player"]["team"][0]
        mon["hp"] = 101
        view["player"]["active_details"][0] = copy.deepcopy(mon)

    def inconsistent_hp_percent(view):
        mon = view["player"]["team"][0]
        mon["hp_percent"] = 99
        view["player"]["active_details"][0] = copy.deepcopy(mon)

    def mismatched_active_projection(view):
        view["player"]["active_details"][0]["species"] = "Raichu"

    def called_without_provenance(view):
        view["public_execution_delta"] = {
            "turn": 2,
            "actions": [
                {
                    "side": "player",
                    "slot": 1,
                    "outcome": "executed",
                    "move": "tackle",
                    "source": "called",
                    "provenance": [],
                    "effects": [],
                }
            ],
        }

    def selected_with_provenance(view):
        view["public_execution_delta"] = {
            "turn": 2,
            "actions": [
                {
                    "side": "player",
                    "slot": 1,
                    "outcome": "executed",
                    "move": "tackle",
                    "source": "selected",
                    "provenance": ["[from]:move:sleeptalk"],
                    "effects": [],
                }
            ],
        }

    return (
        impossible_hp_fraction,
        padded_hp,
        unknown_event_status,
        overlong_crit,
        invalid_miss_target,
        invalid_request_condition,
        noncanonical_request_id,
        hp_exceeds_max,
        inconsistent_hp_percent,
        mismatched_active_projection,
        called_without_provenance,
        selected_with_provenance,
    )


@pytest.mark.parametrize("mutator", _v5_semantic_invalid_mutators())
@pytest.mark.parametrize("evaluator", ("deterministic", "sequential"))
def test_v5_semantic_invalid_expected_is_preflight_unsupported(mutator, evaluator):
    expected = _v5_semantic_valid_view()
    mutator(expected)
    worker = _FakeReachabilityWorker(
        {("root", "seed-a"): ("done", _v5_semantic_valid_view())},
        rng_draw_counts={("root", "seed-a"): 0},
        normalize_views=False,
    )
    step = PublicReachabilityStep(
        p1_choice="move a",
        p2_choice="move b",
        expected_public_view=expected,
        rng_seeds=("seed-a",),
    )
    if evaluator == "deterministic":
        result = evaluate_deterministic_public_transition(
            worker,
            state={"node": "root"},
            side="p1",
            step=step,
        )
    else:
        result = witness_public_observation_sequence(
            worker,
            state={"node": "root"},
            side="p1",
            steps=(step,),
        )
    assert result.status is ReachabilityStatus.UNSUPPORTED
    assert not result.conclusive
    assert not result.establishes_impossibility
    assert worker.calls == 0


@pytest.mark.parametrize("mutator", _v5_semantic_invalid_mutators())
@pytest.mark.parametrize("evaluator", ("deterministic", "sequential"))
@pytest.mark.parametrize("signature_mode", ("matching", "mismatching"))
def test_v5_semantic_invalid_worker_evidence_never_conclusive(
    mutator,
    evaluator,
    signature_mode,
):
    expected = _v5_semantic_valid_view()
    returned = copy.deepcopy(expected)
    if signature_mode == "mismatching":
        returned["winner"] = "different-winner"
    mutator(returned)
    worker = _FakeReachabilityWorker(
        {("root", "seed-a"): ("done", returned)},
        rng_draw_counts={("root", "seed-a"): 0},
        normalize_views=False,
    )
    step = PublicReachabilityStep(
        p1_choice="move a",
        p2_choice="move b",
        expected_public_view=expected,
        rng_seeds=("seed-a",),
    )
    if evaluator == "deterministic":
        result = evaluate_deterministic_public_transition(
            worker,
            state={"node": "root"},
            side="p1",
            step=step,
        )
    else:
        result = witness_public_observation_sequence(
            worker,
            state={"node": "root"},
            side="p1",
            steps=(step,),
        )
    assert result.status is ReachabilityStatus.UNSUPPORTED
    assert not result.conclusive
    assert not result.establishes_impossibility


@pytest.mark.parametrize(
    "event",
    (
        ["-immune", "p2a"],
        ["-immune", "p2a", "[from]:ability:levitate"],
        ["-swapboost", "p1a", "p2a", "atkspa", "[from]:move:powerswap"],
        ["-swapboost", "p1a", "p2a", "[from]:move:heartswap"],
        ["-copyboost", "p1a", "p2a", "[from]:move:psychup"],
        ["-damage", "p2a", "50/100y"],
        ["-damage", "p2a", "50/100g"],
        ["-damage", "p2a", "20/100r"],
        ["-damage", "p2a", "20/100y"],
        ["-miss", "p1a"],
        ["-miss", "p1a", "p2a"],
        ["-singleturn", "p1a", "move:followme"],
        ["-singleturn", "p1b", "move:instruct", "[of]:p1a"],
        ["-start", "p2a", "typechange", "water"],
        ["-prepare", "p1a", "chillyreception", "[premajor]"],
        ["-ability", "p1a", "speedboost", "boost"],
        [
            "-ability",
            "p1a",
            "unburden",
            "trace",
            "[from]:ability:trace",
            "[of]:p2b",
        ],
        ["-transform", "p1a", "p2b", "[from]:ability:imposter"],
        ["-activate", "p2a", "move:eeriespell", "sleeptalk", "3"],
        ["-start", "p1a", "stockpile1"],
        ["-start", "p1a", "stockpile3"],
        ["-start", "p1a", "perish3", "[silent]"],
        ["-start", "p1a", "perish0"],
        ["-activate", "p2a", "move:substitute", "[damage]"],
    ),
)
def test_v5_genuine_event_variants_are_supported(event):
    view = _valid_public_view()
    view["public_event_delta"]["turn"] = 1
    view["public_event_delta"]["events"] = [event]
    assert public_reachability_observation_issue(view) is None


@pytest.mark.parametrize(
    "event",
    (
        ["-damage", "p1a", "20/100g"],
        ["-damage", "p1a", "50/100r"],
        ["-damage", "p1a", "21/100y"],
        ["-damage", "p1a", "0/100"],
        ["-swapboost", "p1a", "p2a", "atkatk"],
        ["-copyboost", "p1a", "p2a", "atkspa"],
        ["-crit", "p1a", "[from]:move:tackle"],
        ["-resisted", "p1a"],
        ["-resisted", "p1a", "3"],
        ["-supereffective", "p1a", "0"],
        ["-supereffective", "p1a", "01"],
        ["-activate", "banana"],
        ["-activate", "p1a"],
        ["-damage", "p1a", "50/100", "[futuremechanic]:banana"],
        ["-damage", "p1a", "50/100", "[from]"],
        ["-damage", "p1a", "50/100", "[of]:banana"],
        ["-boost", "p1a", "atk", "-1"],
        ["-unboost", "p1a", "atk", "-1"],
        ["-swapboost", "p1a", "p2a", "atkdef"],
        ["-prepare", "p1a", "p2b"],
        ["-weather", "p1a"],
        ["-fieldstart", "p2b"],
        ["-sidestart", "p1", "p2a"],
        ["-primal", "p1a"],
        ["-weather", "move:protect"],
        ["-weather", "item:leftovers"],
        ["-fieldstart", "ability:intimidate"],
        ["-sidestart", "p1", "item:leftovers"],
        ["-start", "p1a", "typechange", "banana"],
        ["-start", "p1a", "confusion", "move:protect"],
        ["-formechange", "p1a", "banana", "garbage"],
        ["-mega", "p1a", "banana", "leftovers"],
        ["-primal", "p1a", "leftovers"],
        ["-activate", "p1a", "move:protect", "p2a", "p2b"],
        [
            "-activate",
            "p1a",
            "confusion",
            "[from]:move:protect",
            "[from]:move:soak",
        ],
        ["-activate", "p2a", "move:eeriespell", "sleeptalk", "4"],
        ["-start", "p1a", "stockpile4"],
        ["-start", "p1a", "perish4"],
        ["-activate", "p2a", "move:substitute", "[future]"],
    ),
)
def test_v5_impossible_event_variants_are_rejected(event):
    view = _valid_public_view()
    view["public_event_delta"]["turn"] = 1
    view["public_event_delta"]["events"] = [event]
    assert public_reachability_observation_issue(view) is not None



def _v5_two_active_view():
    view = _valid_public_view({"marker": "wanted"})
    first = _v5_valid_own_mon(active=True)
    second = _v5_valid_own_mon(active=True)
    second["moves"] = ["Protect"]
    second["damaging_move_count"] = 0
    second["item"] = "leftovers"
    second["speed"] = 101
    view["player"]["active"] = ["Pikachu", "Pikachu"]
    view["player"]["active_details"] = [
        copy.deepcopy(first),
        copy.deepcopy(second),
    ]
    view["player"]["team"] = [copy.deepcopy(first), copy.deepcopy(second)]
    view["request"] = {
        "wait": True,
        "side": {
            "name": "Player",
            "id": "p1",
            "pokemon": [
                _v5_valid_request_mon(active=True),
                _v5_valid_request_mon(active=True),
            ],
        },
    }
    return view


def test_v5_ordered_duplicate_species_projection_is_supported():
    view = _v5_two_active_view()
    assert public_reachability_observation_issue(view) is None


def test_v5_swapped_duplicate_species_details_are_rejected():
    view = _v5_two_active_view()
    view["player"]["active_details"].reverse()
    assert public_reachability_observation_issue(view) is not None


def test_v5_doubles_projection_rejects_third_active_slot():
    view = _v5_two_active_view()
    third = copy.deepcopy(view["player"]["team"][0])
    view["player"]["active"].append("Pikachu")
    view["player"]["active_details"].append(copy.deepcopy(third))
    view["player"]["team"].append(third)
    assert public_reachability_observation_issue(view) is not None


def test_v5_terminal_fainted_occupants_are_supported():
    view = _valid_public_view({"marker": "Player"})
    first = _v5_valid_own_mon(
        species="Gardevoir",
        hp=0,
        maxhp=100,
        active=False,
    )
    first["status"] = "fnt"
    first["ability"] = "trace"
    first["moves"] = ["Psychic"]
    second = _v5_valid_own_mon(
        species="Armarouge",
        hp=0,
        maxhp=100,
        active=False,
    )
    second["status"] = "fnt"
    second["ability"] = "flashfire"
    second["moves"] = ["Psychic"]
    view["phase"] = "ended"
    view["ended"] = True
    view["winner"] = "Player"
    view["request"] = None
    view["player"]["active"] = ["Gardevoir", "Armarouge"]
    view["player"]["active_details"] = [
        copy.deepcopy(first),
        copy.deepcopy(second),
    ]
    view["player"]["team"] = [copy.deepcopy(first), copy.deepcopy(second)]

    assert public_reachability_observation_issue(view) is None


def test_v5_living_fnt_status_is_rejected():
    view = _v5_semantic_valid_view()
    view["player"]["team"][0]["status"] = "fnt"
    view["player"]["active_details"][0]["status"] = "fnt"
    assert public_reachability_observation_issue(view) is not None


@pytest.mark.parametrize(
    "mutation",
    ("own-status-list", "request-side-list"),
)
def test_v5_nested_collection_types_return_schema_failure(mutation):
    view = _v5_semantic_valid_view()
    if mutation == "own-status-list":
        view["player"]["team"][0]["status"] = []
        view["player"]["active_details"][0]["status"] = []
    else:
        view["request"]["side"]["id"] = []
    issue = public_reachability_observation_issue(view)
    assert isinstance(issue, str)


def test_v5_damaging_move_count_uses_pinned_move_metadata():
    view = _v5_semantic_valid_view()
    view["player"]["team"][0]["moves"] = ["Protect"]
    view["player"]["team"][0]["damaging_move_count"] = 1
    view["player"]["active_details"][0] = copy.deepcopy(view["player"]["team"][0])
    assert public_reachability_observation_issue(view) is not None


def test_v5_arbitrary_public_move_display_name_is_rejected():
    view = _v5_semantic_valid_view()
    view["player"]["team"][0]["moves"] = ["!!!"]
    view["player"]["active_details"][0] = copy.deepcopy(view["player"]["team"][0])
    assert public_reachability_observation_issue(view) is not None


def test_v5_request_side_must_match_roster_idents():
    view = _v5_semantic_valid_view()
    view["request"]["side"]["id"] = "p2"
    assert public_reachability_observation_issue(view) is not None


def test_v5_request_pokemon_requires_gen9_fields():
    view = _v5_semantic_valid_view()
    view["request"]["side"]["pokemon"][0].pop("ability")
    assert public_reachability_observation_issue(view) is not None


def test_v5_active_request_rejects_empty_move_choices():
    view = _valid_public_view()
    view["request"] = {
        "active": [{"moves": []}, None],
        "side": {"name": "Player", "id": "p1", "pokemon": []},
    }
    assert public_reachability_observation_issue(view) is not None


def test_v5_execution_effects_must_be_sorted_like_producer():
    view = _valid_public_view()
    view["public_execution_delta"] = {
        "turn": 2,
        "actions": [
            {
                "side": "player",
                "slot": 1,
                "outcome": "executed",
                "move": "tackle",
                "source": "selected",
                "provenance": [],
                "effects": ["-miss", "-fail"],
            }
        ],
    }
    assert public_reachability_observation_issue(view) is not None


@pytest.mark.parametrize(
    "provenance",
    (
        ["[from]:p1a"],
        ["[from]:banana"],
        ["[from]:[of]:p2a"],
    ),
)
def test_v5_called_execution_rejects_untyped_provenance(provenance):
    view = _valid_public_view()
    view["public_execution_delta"] = {
        "turn": 2,
        "actions": [
            {
                "side": "player",
                "slot": 1,
                "outcome": "executed",
                "move": "tackle",
                "source": "called",
                "provenance": provenance,
                "effects": [],
            }
        ],
    }
    assert public_reachability_observation_issue(view) is not None


def _v5_review_invalid_mutators():
    def unknown_modifier(view):
        view["public_event_delta"]["events"].append(
            ["-damage", "p1a", "50/100", "[futuremechanic]:banana"]
        )

    def untyped_called_provenance(view):
        view["public_execution_delta"] = {
            "turn": 2,
            "actions": [
                {
                    "side": "player",
                    "slot": 1,
                    "outcome": "executed",
                    "move": "tackle",
                    "source": "called",
                    "provenance": ["[from]:banana"],
                    "effects": [],
                }
            ],
        }

    def negative_boost(view):
        view["public_event_delta"]["events"].append(
            ["-boost", "p1a", "atk", "-1"]
        )

    def impossible_transfer(view):
        view["public_event_delta"]["events"].append(
            ["-swapboost", "p1a", "p2a", "atkdef"]
        )

    def actor_as_weather(view):
        view["public_event_delta"]["events"].append(["-weather", "p1a"])

    def wrong_damaging_count(view):
        mon = view["player"]["team"][0]
        mon["moves"] = ["Protect"]
        mon["damaging_move_count"] = 1
        view["player"]["active_details"][0] = copy.deepcopy(mon)

    def opposite_request_ident(view):
        view["request"]["side"]["pokemon"][0]["ident"] = "p2: Opposite"

    def unsorted_effects(view):
        view["public_execution_delta"] = {
            "turn": 2,
            "actions": [
                {
                    "side": "player",
                    "slot": 1,
                    "outcome": "executed",
                    "move": "tackle",
                    "source": "selected",
                    "provenance": [],
                    "effects": ["-miss", "-fail"],
                }
            ],
        }

    return (
        unknown_modifier,
        untyped_called_provenance,
        negative_boost,
        impossible_transfer,
        actor_as_weather,
        wrong_damaging_count,
        opposite_request_ident,
        unsorted_effects,
    )


@pytest.mark.parametrize("mutator", _v5_review_invalid_mutators())
@pytest.mark.parametrize("evaluator", ("deterministic", "sequential"))
def test_v5_review_invalid_expected_is_preflight_unsupported(mutator, evaluator):
    expected = _v5_semantic_valid_view()
    mutator(expected)
    worker = _FakeReachabilityWorker(
        {("root", "seed-a"): ("done", _v5_semantic_valid_view())},
        rng_draw_counts={("root", "seed-a"): 0},
        normalize_views=False,
    )
    step = PublicReachabilityStep(
        p1_choice="move a",
        p2_choice="move b",
        expected_public_view=expected,
        rng_seeds=("seed-a",),
    )
    if evaluator == "deterministic":
        result = evaluate_deterministic_public_transition(
            worker,
            state={"node": "root"},
            side="p1",
            step=step,
        )
    else:
        result = witness_public_observation_sequence(
            worker,
            state={"node": "root"},
            side="p1",
            steps=(step,),
        )
    assert result.status is ReachabilityStatus.UNSUPPORTED
    assert not result.conclusive
    assert not result.establishes_impossibility
    assert worker.calls == 0


@pytest.mark.parametrize("mutator", _v5_review_invalid_mutators())
@pytest.mark.parametrize("evaluator", ("deterministic", "sequential"))
@pytest.mark.parametrize("signature_mode", ("matching", "mismatching"))
def test_v5_review_invalid_worker_evidence_never_conclusive(
    mutator,
    evaluator,
    signature_mode,
):
    expected = _v5_semantic_valid_view()
    returned = copy.deepcopy(expected)
    if signature_mode == "mismatching":
        returned["winner"] = "different-winner"
    mutator(returned)
    worker = _FakeReachabilityWorker(
        {("root", "seed-a"): ("done", returned)},
        rng_draw_counts={("root", "seed-a"): 0},
        normalize_views=False,
    )
    step = PublicReachabilityStep(
        p1_choice="move a",
        p2_choice="move b",
        expected_public_view=expected,
        rng_seeds=("seed-a",),
    )
    if evaluator == "deterministic":
        result = evaluate_deterministic_public_transition(
            worker,
            state={"node": "root"},
            side="p1",
            step=step,
        )
    else:
        result = witness_public_observation_sequence(
            worker,
            state={"node": "root"},
            side="p1",
            steps=(step,),
        )
    assert result.status is ReachabilityStatus.UNSUPPORTED
    assert not result.conclusive
    assert not result.establishes_impossibility



@pytest.mark.parametrize(
    ("move_name", "expected_damaging"),
    (
        ("Hidden Power Ice", 1),
        ("Return 102", 1),
        ("Frustration 1", 1),
    ),
)
def test_v6_exact_special_move_displays_are_supported(move_name, expected_damaging):
    view = _v5_semantic_valid_view()
    view["player"]["team"][0]["moves"] = [move_name]
    view["player"]["team"][0]["damaging_move_count"] = expected_damaging
    view["player"]["active_details"][0] = copy.deepcopy(view["player"]["team"][0])
    assert public_reachability_observation_issue(view) is None


@pytest.mark.parametrize(
    "move_name",
    (
        "Hidden Power Banana",
        "Hidden Power Ice !!!",
        "Return banana",
        "Frustration !!!",
        "Return 103",
        "Frustration 00",
    ),
)
def test_v6_fabricated_special_move_displays_are_rejected(move_name):
    view = _v5_semantic_valid_view()
    view["player"]["team"][0]["moves"] = [move_name]
    view["player"]["active_details"][0] = copy.deepcopy(view["player"]["team"][0])
    assert public_reachability_observation_issue(view) is not None


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    (
        ("weather", "protect"),
        ("terrain", "leftovers"),
    ),
)
def test_v6_field_roles_reject_unrelated_catalog_ids(field_name, bad_value):
    view = _valid_public_view()
    view["field"][field_name] = bad_value
    assert public_reachability_observation_issue(view) is not None


def test_v6_pseudo_weather_requires_unique_object_key_projection():
    view = _valid_public_view()
    view["field"]["pseudo_weather"] = ["trickroom", "trickroom"]
    assert public_reachability_observation_issue(view) is not None


def test_v6_side_conditions_reject_unrelated_catalog_ids():
    view = _valid_public_view()
    view["player"]["side_conditions"] = ["leftovers"]
    assert public_reachability_observation_issue(view) is not None


@pytest.mark.parametrize("active", ([], [None]))
def test_v6_opponent_active_requires_exact_doubles_cardinality(active):
    view = _valid_public_view()
    view["opponent"]["active"] = active
    assert public_reachability_observation_issue(view) is not None


@pytest.mark.parametrize(
    "active",
    (
        [],
        [{"moves": [{"move": "Tackle", "id": "tackle", "pp": 10,
                      "maxpp": 10, "target": "normal", "disabled": False}]}],
    ),
)
def test_v6_move_request_requires_exact_doubles_cardinality(active):
    view = _valid_public_view()
    view["request"] = {
        "active": active,
        "side": {"name": "Player", "id": "p1", "pokemon": []},
    }
    assert public_reachability_observation_issue(view) is not None


def _v6_review_invalid_mutators():
    def weather_move(view):
        view["public_event_delta"]["events"].append(
            ["-weather", "move:protect"]
        )

    def weather_item(view):
        view["public_event_delta"]["events"].append(
            ["-weather", "item:leftovers"]
        )

    def field_ability(view):
        view["public_event_delta"]["events"].append(
            ["-fieldstart", "ability:intimidate"]
        )

    def side_item(view):
        view["public_event_delta"]["events"].append(
            ["-sidestart", "p1", "item:leftovers"]
        )

    def bogus_typechange(view):
        view["public_event_delta"]["events"].append(
            ["-start", "p1a", "typechange", "banana"]
        )

    def extra_start_payload(view):
        view["public_event_delta"]["events"].append(
            ["-start", "p1a", "confusion", "move:protect"]
        )

    def bad_forme(view):
        view["public_event_delta"]["events"].append(
            ["-formechange", "p1a", "banana", "garbage"]
        )

    def bad_mega(view):
        view["public_event_delta"]["events"].append(
            ["-mega", "p1a", "banana", "leftovers"]
        )

    def bad_primal(view):
        view["public_event_delta"]["events"].append(
            ["-primal", "p1a", "leftovers"]
        )

    def activate_many_actors(view):
        view["public_event_delta"]["events"].append(
            ["-activate", "p1a", "move:protect", "p2a", "p2b"]
        )

    def activate_duplicate_from(view):
        view["public_event_delta"]["events"].append(
            [
                "-activate",
                "p1a",
                "confusion",
                "[from]:move:protect",
                "[from]:move:soak",
            ]
        )

    def bad_special_display(view):
        mon = view["player"]["team"][0]
        mon["moves"] = ["Hidden Power Banana"]
        view["player"]["active_details"][0] = copy.deepcopy(mon)

    def bad_weather_field(view):
        view["field"]["weather"] = "protect"

    def duplicate_pseudo(view):
        view["field"]["pseudo_weather"] = ["trickroom", "trickroom"]

    def bad_side_condition(view):
        view["player"]["side_conditions"] = ["leftovers"]

    def empty_opponent_active(view):
        view["opponent"]["active"] = []

    return (
        weather_move,
        weather_item,
        field_ability,
        side_item,
        bogus_typechange,
        extra_start_payload,
        bad_forme,
        bad_mega,
        bad_primal,
        activate_many_actors,
        activate_duplicate_from,
        bad_special_display,
        bad_weather_field,
        duplicate_pseudo,
        bad_side_condition,
        empty_opponent_active,
    )


@pytest.mark.parametrize("mutator", _v6_review_invalid_mutators())
@pytest.mark.parametrize("evaluator", ("deterministic", "sequential"))
def test_v6_review_invalid_expected_stops_before_worker(mutator, evaluator):
    expected = _v5_semantic_valid_view()
    mutator(expected)
    worker = _FakeReachabilityWorker(
        {("root", "seed-a"): ("done", _v5_semantic_valid_view())},
        rng_draw_counts={("root", "seed-a"): 0},
        normalize_views=False,
    )
    step = PublicReachabilityStep(
        p1_choice="move a",
        p2_choice="move b",
        expected_public_view=expected,
        rng_seeds=("seed-a",),
    )
    if evaluator == "deterministic":
        result = evaluate_deterministic_public_transition(
            worker,
            state={"node": "root"},
            side="p1",
            step=step,
        )
    else:
        result = witness_public_observation_sequence(
            worker,
            state={"node": "root"},
            side="p1",
            steps=(step,),
        )
    assert result.status is ReachabilityStatus.UNSUPPORTED
    assert not result.conclusive
    assert not result.establishes_impossibility
    assert worker.calls == 0


@pytest.mark.parametrize("mutator", _v6_review_invalid_mutators())
@pytest.mark.parametrize("evaluator", ("deterministic", "sequential"))
@pytest.mark.parametrize("signature_mode", ("matching", "mismatching"))
def test_v6_review_invalid_returned_evidence_never_conclusive(
    mutator,
    evaluator,
    signature_mode,
):
    expected = _v5_semantic_valid_view()
    returned = copy.deepcopy(expected)
    if signature_mode == "mismatching":
        returned["winner"] = "different-winner"
    mutator(returned)
    worker = _FakeReachabilityWorker(
        {("root", "seed-a"): ("done", returned)},
        rng_draw_counts={("root", "seed-a"): 0},
        normalize_views=False,
    )
    step = PublicReachabilityStep(
        p1_choice="move a",
        p2_choice="move b",
        expected_public_view=expected,
        rng_seeds=("seed-a",),
    )
    if evaluator == "deterministic":
        result = evaluate_deterministic_public_transition(
            worker,
            state={"node": "root"},
            side="p1",
            step=step,
        )
    else:
        result = witness_public_observation_sequence(
            worker,
            state={"node": "root"},
            side="p1",
            steps=(step,),
        )
    assert result.status is ReachabilityStatus.UNSUPPORTED
    assert not result.conclusive
    assert not result.establishes_impossibility


def _v7_opponent_knowledge_view():
    view = _v5_semantic_valid_view()
    view["opponent"]["preview_species"] = ["Pikachu", "Raichu"]
    view["opponent"]["revealed"] = [
        {
            "species": "Pikachu",
            "moves": [],
            "items": [],
            "abilities": [],
            "hp_percent": 100,
            "status": None,
            "fainted": False,
            "seen": True,
        },
        {
            "species": "Raichu",
            "moves": [],
            "items": [],
            "abilities": [],
            "hp_percent": None,
            "status": None,
            "fainted": False,
            "seen": False,
        },
    ]
    view["opponent"]["active"] = [
        {
            "species": "Pikachu",
            "base_species": "Pikachu",
            "hp_percent": 100,
            "fainted": False,
            "status": None,
            "boosts": _v5_complete_boosts(),
        },
        None,
    ]
    return view


@pytest.mark.parametrize(
    "actions",
    (
        [{"turn": 99, "slot": 1, "move": "thunderbolt", "target": 1}],
        [
            {"turn": 1, "slot": 1, "move": "thunderbolt", "target": 1},
            {"turn": 2, "slot": 2, "move": "protect", "target": None},
        ],
        [
            {"turn": 1, "slot": 1, "move": "thunderbolt", "target": 1},
            {"turn": 1, "slot": 1, "move": "protect", "target": None},
        ],
        [
            {"turn": 1, "slot": 2, "move": "protect", "target": None},
            {"turn": 1, "slot": 1, "move": "thunderbolt", "target": 1},
        ],
    ),
)
def test_v7_selected_action_collection_relationships_are_enforced(actions):
    view = _v5_semantic_valid_view()
    view["opponent_last_actions"] = copy.deepcopy(actions)
    assert public_reachability_observation_issue(view) is not None


def test_v7_older_selected_action_ledger_remains_supported():
    view = _v5_semantic_valid_view()
    view["opponent_last_actions"] = [
        {"turn": 1, "slot": 1, "move": "thunderbolt", "target": 1},
    ]
    assert public_reachability_observation_issue(view) is None


def test_v7_aligned_selected_actions_must_match_public_execution():
    view = _v5_semantic_valid_view()
    view["opponent_last_actions"] = [
        {"turn": 1, "slot": 1, "move": "thunderbolt", "target": 1},
    ]
    view["public_execution_delta"] = {
        "turn": 1,
        "actions": [
            {
                "side": "opponent",
                "slot": 1,
                "outcome": "executed",
                "move": "tackle",
                "source": "selected",
                "provenance": [],
                "effects": [],
            }
        ],
    }
    assert public_reachability_observation_issue(view) is not None


@pytest.mark.parametrize("evaluator", ("deterministic", "sequential"))
def test_v7_selected_action_ledger_is_part_of_certified_signature(evaluator):
    expected = _v5_semantic_valid_view()
    expected["opponent_last_actions"] = [
        {"turn": 1, "slot": 1, "move": "thunderbolt", "target": 1},
    ]
    returned = copy.deepcopy(expected)
    returned["opponent_last_actions"][0]["move"] = "tackle"
    worker = _FakeReachabilityWorker(
        {("root", "seed-a"): ("done", returned)},
        rng_draw_counts={("root", "seed-a"): 0},
        normalize_views=False,
    )
    step = PublicReachabilityStep(
        p1_choice="move a",
        p2_choice="move b",
        expected_public_view=expected,
        rng_seeds=("seed-a",),
    )
    if evaluator == "deterministic":
        result = evaluate_deterministic_public_transition(
            worker,
            state={"node": "root"},
            side="p1",
            step=step,
        )
        assert result.status is ReachabilityStatus.EXHAUSTIVELY_DISPROVED
    else:
        result = witness_public_observation_sequence(
            worker,
            state={"node": "root"},
            side="p1",
            steps=(step,),
        )
        assert result.status is ReachabilityStatus.UNRESOLVED
    assert not result.establishes_reachability


@pytest.mark.parametrize(
    "event",
    (
        ["-start", "p1a", "item:leftovers"],
        ["-end", "p1a", "ability:hugepower"],
        ["-singleturn", "p1a", "move:thunderbolt"],
        ["-activate", "p1a", "item:focusband", "move:thunderbolt"],
        ["-activate", "p1a", "ability:forewarn", "ability:hugepower"],
        ["-mega", "p1a", "pikachu", "gardevoirite"],
        ["-formechange", "p1a", "pikachu"],
        ["-formechange", "p1a", "pikachu", "[from]:ability:hugepower"],
        ["-burst", "p1a", "banana", "leftovers"],
    ),
)
def test_v7_review_invalid_producer_role_events_are_rejected(event):
    view = _v5_semantic_valid_view()
    view["public_event_delta"]["turn"] = 1
    view["public_event_delta"]["events"] = [event]
    assert public_reachability_observation_issue(view) is not None


@pytest.mark.parametrize(
    "event",
    (
        ["-activate", "p2a", "move:spite", "splash", "4"],
        ["-activate", "p2a", "item:leppaberry", "splash", "[consumed]"],
        ["-burst", "p1a", "necrozma", "ultranecroziumz"],
        [
            "-formechange",
            "p1a",
            "cherrimsunshine",
            "[msg]",
            "[from]:ability:flowergift",
        ],
        [
            "-formechange",
            "p1a",
            "darmanitan",
            "[silent]",
            "[from]:ability:zenmode",
        ],
    ),
)
def test_v7_review_genuine_pinned_variants_are_supported(event):
    view = _v5_semantic_valid_view()
    view["public_event_delta"]["turn"] = 1
    view["public_event_delta"]["events"] = [event]
    assert public_reachability_observation_issue(view) is None


@pytest.mark.parametrize(
    "event",
    (
        ["-start", "p1a", "charge"],
        ["-start", "p1a", "charge", "thunderbolt", "[from]:ability:electromorphosis"],
        ["-start", "p1a", "disable", "thunderbolt"],
        ["-start", "p1a", "mimic", "thunderbolt"],
        ["-start", "p1a", "dynamax", "gmax"],
        ["-start", "p1a", "confusion", "[fatigue]"],
        ["-start", "p1a", "uproar", "[upkeep]"],
        ["-start", "p1a", "typechange", "[from]:move:reflecttype", "[of]:p2a"],
        ["-end", "p1a", "move:firespin", "[partiallytrapped]", "[silent]"],
        ["-end", "p1a", "typechange", "[silent]"],
    ),
)
def test_v7_typed_start_end_variants_remain_supported(event):
    view = _v5_semantic_valid_view()
    view["public_event_delta"]["turn"] = 1
    view["public_event_delta"]["events"] = [event]
    assert public_reachability_observation_issue(view) is None


def test_v7_recharge_prevention_is_supported():
    view = _v5_semantic_valid_view()
    view["public_execution_delta"] = {
        "turn": 1,
        "actions": [
            {
                "side": "opponent",
                "slot": 1,
                "outcome": "prevented",
                "reason": "recharge",
                "attempted_move": None,
                "effects": [],
            }
        ],
    }
    assert public_reachability_observation_issue(view) is None


def test_v7_opponent_revealed_must_match_preview_projection():
    view = _v7_opponent_knowledge_view()
    view["opponent"]["revealed"] = []
    assert public_reachability_observation_issue(view) is not None


def test_v7_unseen_opponent_knowledge_requires_exact_defaults():
    view = _v7_opponent_knowledge_view()
    unseen = view["opponent"]["revealed"][1]
    unseen["hp_percent"] = 100
    assert public_reachability_observation_issue(view) is not None


def test_v7_opponent_revealed_preserves_preview_key_order():
    view = _v7_opponent_knowledge_view()
    view["opponent"]["revealed"].reverse()
    assert public_reachability_observation_issue(view) is not None


def test_v7_active_base_species_requires_seen_preview_record():
    view = _v7_opponent_knowledge_view()
    view["opponent"]["active"][0]["base_species"] = "Raichu"
    assert public_reachability_observation_issue(view) is not None



@pytest.mark.parametrize(
    "event",
    (
        ["-activate", "p1a", "move:afteryou", "p2a", "[ability]:hugepower"],
        ["-start", "p1a", "ability:neutralizinggas"],
        ["-formechange", "p1a", "castformsunny", "[from]:ability:zenmode"],
    ),
)
def test_v8_targeted_review_rejects_impossible_producer_relationships(event):
    view = _v5_semantic_valid_view()
    view["public_event_delta"] = {
        "turn": 1,
        "events": [event],
        "unsupported": [],
    }
    assert public_reachability_observation_issue(view) is not None


def test_v8_targeted_review_rejects_catalog_identity_as_prevention_reason():
    view = _v5_semantic_valid_view()
    view["public_execution_delta"] = {
        "turn": 1,
        "actions": [
            {
                "side": "opponent",
                "slot": 1,
                "outcome": "prevented",
                "reason": "item:leftovers",
                "attempted_move": None,
                "effects": [],
            }
        ],
    }
    assert public_reachability_observation_issue(view) is not None


@pytest.mark.parametrize(
    ("ledger_name", "turn", "content_field", "content"),
    (
        ("public_event_delta", 52, "events", [["-crit", "p1a"]]),
        ("public_event_delta", None, "events", [["-crit", "p1a"]]),
        ("public_execution_delta", 52, "actions", []),
    ),
)
def test_v8_targeted_review_enforces_ledger_turn_content_relationships(
    ledger_name,
    turn,
    content_field,
    content,
):
    view = _v5_semantic_valid_view()
    if ledger_name == "public_event_delta":
        view[ledger_name] = {
            "turn": turn,
            "events": content if content_field == "events" else [],
            "unsupported": [],
        }
    else:
        view[ledger_name] = {"turn": turn, "actions": content}
    assert public_reachability_observation_issue(view) is not None


@pytest.mark.parametrize("bad_value", (None, True, 1, [], {}))
@pytest.mark.parametrize(
    ("outcome", "field"),
    (
        ("executed", "side"),
        ("executed", "source"),
        ("prevented", "reason"),
    ),
)
def test_v8_execution_string_discriminators_are_type_guarded(
    outcome,
    field,
    bad_value,
):
    view = _v5_semantic_valid_view()
    if outcome == "executed":
        action = {
            "side": "player",
            "slot": 1,
            "outcome": "executed",
            "move": "tackle",
            "source": "selected",
            "provenance": [],
            "effects": [],
        }
    else:
        action = {
            "side": "player",
            "slot": 1,
            "outcome": "prevented",
            "reason": "recharge",
            "attempted_move": None,
            "effects": [],
        }
    action[field] = bad_value
    view["public_execution_delta"] = {"turn": 1, "actions": [action]}
    assert public_reachability_observation_issue(view) is not None


@pytest.mark.parametrize(
    "event",
    (
        ["-activate", "p1a", "ability:commander"],
        ["-activate", "p1a", "move:trick"],
        ["-activate", "p1a", "move:bind"],
    ),
)
def test_v8_targeted_activation_producers_require_of_payload(event):
    view = _v5_semantic_valid_view()
    view["public_event_delta"] = {
        "turn": 1,
        "events": [event],
        "unsupported": [],
    }
    assert public_reachability_observation_issue(view) is not None


def test_v8_pinned_actor_ability_activation_relationship_remains_supported():
    view = _v5_semantic_valid_view()
    view["public_event_delta"] = {
        "turn": 1,
        "events": [
            ["-activate", "p1a", "ability:mummy", "p2a", "[ability]:hugepower"]
        ],
        "unsupported": [],
    }
    assert public_reachability_observation_issue(view) is None


@pytest.mark.parametrize(
    "event",
    (
        ["-start", "p1a", "ability:slowstart"],
        ["-end", "p1a", "ability:neutralizinggas"],
        ["-formechange", "p1a", "castformsunny", "[msg]", "[from]:ability:forecast"],
        ["-formechange", "p1a", "darmanitangalarzen", "[from]:ability:zenmode"],
    ),
)
def test_v8_pinned_role_relationship_controls_remain_supported(event):
    view = _v5_semantic_valid_view()
    view["public_event_delta"] = {
        "turn": 1,
        "events": [event],
        "unsupported": [],
    }
    assert public_reachability_observation_issue(view) is None


def _v9_selected_opponent_projection_view():
    view = _v5_semantic_valid_view()
    view["public_execution_delta"] = {
        "turn": 1,
        "actions": [
            {
                "side": "opponent",
                "slot": 1,
                "outcome": "executed",
                "move": "thunderbolt",
                "source": "selected",
                "provenance": [],
                "effects": [],
            },
            {
                "side": "opponent",
                "slot": 2,
                "outcome": "executed",
                "move": "protect",
                "source": "selected",
                "provenance": [],
                "effects": [],
            },
        ],
    }
    view["opponent_last_actions"] = [
        {"turn": 1, "slot": 1, "move": "thunderbolt", "target": 1},
        {"turn": 1, "slot": 2, "move": "protect", "target": None},
    ]
    return view


def test_v9_selected_opponent_projection_requires_reverse_correspondence():
    view = _v9_selected_opponent_projection_view()
    view["opponent_last_actions"] = []
    issue = public_reachability_observation_issue(view)
    assert issue is not None
    assert "retain each unambiguous selected opponent move" in issue


def test_v9_selected_opponent_projection_rejects_stale_retained_turn():
    view = _v9_selected_opponent_projection_view()
    for action in view["opponent_last_actions"]:
        action["turn"] = 2
    issue = public_reachability_observation_issue(view)
    assert issue is not None
    assert "must use the selected opponent execution turn" in issue


def test_v9_multiple_selected_moves_from_one_slot_remain_ambiguous():
    view = _v5_semantic_valid_view()
    view["public_execution_delta"] = {
        "turn": 1,
        "actions": [
            {
                "side": "opponent",
                "slot": 1,
                "outcome": "executed",
                "move": "thunderbolt",
                "source": "selected",
                "provenance": [],
                "effects": [],
            },
            {
                "side": "opponent",
                "slot": 1,
                "outcome": "executed",
                "move": "protect",
                "source": "selected",
                "provenance": [],
                "effects": [],
            },
        ],
    }
    view["opponent_last_actions"] = []
    assert public_reachability_observation_issue(view) is None


def test_v9_ambiguous_selected_slot_must_not_be_fabricated_as_retained_action():
    view = _v5_semantic_valid_view()
    view["public_execution_delta"] = {
        "turn": 1,
        "actions": [
            {
                "side": "opponent",
                "slot": 1,
                "outcome": "executed",
                "move": "thunderbolt",
                "source": "selected",
                "provenance": [],
                "effects": [],
            },
            {
                "side": "opponent",
                "slot": 1,
                "outcome": "executed",
                "move": "protect",
                "source": "selected",
                "provenance": [],
                "effects": [],
            },
        ],
    }
    view["opponent_last_actions"] = [
        {"turn": 1, "slot": 1, "move": "thunderbolt", "target": 1}
    ]
    issue = public_reachability_observation_issue(view)
    assert issue is not None
    assert "must omit slots with multiple selected opponent move events" in issue


def test_v9_switch_and_prevented_actions_do_not_require_move_projection():
    view = _v5_semantic_valid_view()
    view["public_execution_delta"] = {
        "turn": 1,
        "actions": [
            {
                "side": "opponent",
                "slot": 1,
                "outcome": "prevented",
                "reason": "recharge",
                "attempted_move": None,
                "effects": [],
            }
        ],
    }
    view["opponent_last_actions"] = []
    assert public_reachability_observation_issue(view) is None


def _v7_review_invalid_mutators():
    def future_action(view):
        view["opponent_last_actions"] = [
            {"turn": view["turn"] + 50, "slot": 1, "move": "thunderbolt", "target": 1}
        ]

    def duplicate_action_slot(view):
        view["opponent_last_actions"] = [
            {"turn": 1, "slot": 1, "move": "thunderbolt", "target": 1},
            {"turn": 1, "slot": 1, "move": "protect", "target": None},
        ]

    def invalid_start_item(view):
        view["public_event_delta"]["turn"] = 1
        view["public_event_delta"]["events"] = [
            ["-start", "p1a", "item:leftovers"]
        ]

    def invalid_forewarn_payload(view):
        view["public_event_delta"]["turn"] = 1
        view["public_event_delta"]["events"] = [
            ["-activate", "p1a", "ability:forewarn", "ability:hugepower"]
        ]

    def missing_revealed_projection(view):
        view["opponent"]["preview_species"] = ["Pikachu"]
        view["opponent"]["revealed"] = []

    def unseen_with_knowledge(view):
        view["opponent"]["preview_species"] = ["Pikachu"]
        view["opponent"]["revealed"] = [
            {
                "species": "Pikachu",
                "moves": [],
                "items": [],
                "abilities": [],
                "hp_percent": 100,
                "status": None,
                "fainted": False,
                "seen": False,
            }
        ]

    def phase_list(view):
        view["phase"] = []

    def weather_list(view):
        view["field"]["weather"] = []

    def terrain_list(view):
        view["field"]["terrain"] = []

    def pseudo_weather_dict(view):
        view["field"]["pseudo_weather"] = [{}]

    def player_side_condition_dict(view):
        view["player"]["side_conditions"] = [{}]

    def opponent_side_condition_dict(view):
        view["opponent"]["side_conditions"] = [{}]

    def move_target_list(view):
        view["request"] = {
            "active": [
                {
                    "moves": [
                        {
                            "move": "Tackle",
                            "id": "tackle",
                            "pp": 35,
                            "maxpp": 56,
                            "target": [],
                            "disabled": False,
                        }
                    ]
                },
                None,
            ],
            "side": {"name": "Player", "id": "p1", "pokemon": []},
        }

    def invalid_prevention_item(view):
        view["public_execution_delta"] = {
            "turn": 1,
            "actions": [
                {
                    "side": "opponent",
                    "slot": 1,
                    "outcome": "prevented",
                    "reason": "item:leftovers",
                    "attempted_move": None,
                    "effects": [],
                }
            ],
        }

    def invalid_after_you_ability_tail(view):
        view["public_event_delta"]["turn"] = 1
        view["public_event_delta"]["events"] = [
            ["-activate", "p1a", "move:afteryou", "p2a", "[ability]:hugepower"]
        ]

    def invalid_start_neutralizing_gas(view):
        view["public_event_delta"]["turn"] = 1
        view["public_event_delta"]["events"] = [
            ["-start", "p1a", "ability:neutralizinggas"]
        ]

    def invalid_zenmode_castform(view):
        view["public_event_delta"]["turn"] = 1
        view["public_event_delta"]["events"] = [
            ["-formechange", "p1a", "castformsunny", "[from]:ability:zenmode"]
        ]

    def future_mechanics_turn(view):
        view["public_event_delta"] = {
            "turn": view["turn"] + 50,
            "events": [["-crit", "p1a"]],
            "unsupported": [],
        }

    def null_mechanics_turn_with_content(view):
        view["public_event_delta"] = {
            "turn": None,
            "events": [["-crit", "p1a"]],
            "unsupported": [],
        }

    def future_empty_execution_turn(view):
        view["public_execution_delta"] = {
            "turn": view["turn"] + 50,
            "actions": [],
        }

    def execution_side_list(view):
        view["public_execution_delta"] = {
            "turn": 1,
            "actions": [
                {
                    "side": [],
                    "slot": 1,
                    "outcome": "executed",
                    "move": "tackle",
                    "source": "selected",
                    "provenance": [],
                    "effects": [],
                }
            ],
        }

    def execution_source_list(view):
        view["public_execution_delta"] = {
            "turn": 1,
            "actions": [
                {
                    "side": "player",
                    "slot": 1,
                    "outcome": "executed",
                    "move": "tackle",
                    "source": [],
                    "provenance": [],
                    "effects": [],
                }
            ],
        }

    def execution_reason_list(view):
        view["public_execution_delta"] = {
            "turn": 1,
            "actions": [
                {
                    "side": "player",
                    "slot": 1,
                    "outcome": "prevented",
                    "reason": [],
                    "attempted_move": None,
                    "effects": [],
                }
            ],
        }

    def missing_selected_opponent_action_projection(view):
        view["public_execution_delta"] = {
            "turn": 1,
            "actions": [
                {
                    "side": "opponent",
                    "slot": 1,
                    "outcome": "executed",
                    "move": "thunderbolt",
                    "source": "selected",
                    "provenance": [],
                    "effects": [],
                },
                {
                    "side": "opponent",
                    "slot": 2,
                    "outcome": "executed",
                    "move": "protect",
                    "source": "selected",
                    "provenance": [],
                    "effects": [],
                },
            ],
        }
        view["opponent_last_actions"] = []


    return (
        future_action,
        duplicate_action_slot,
        invalid_start_item,
        invalid_forewarn_payload,
        missing_revealed_projection,
        unseen_with_knowledge,
        phase_list,
        weather_list,
        terrain_list,
        pseudo_weather_dict,
        player_side_condition_dict,
        opponent_side_condition_dict,
        move_target_list,
        invalid_prevention_item,
        invalid_after_you_ability_tail,
        invalid_start_neutralizing_gas,
        invalid_zenmode_castform,
        future_mechanics_turn,
        null_mechanics_turn_with_content,
        future_empty_execution_turn,
        execution_side_list,
        execution_source_list,
        execution_reason_list,
        missing_selected_opponent_action_projection,
    )


@pytest.mark.parametrize("mutator", _v7_review_invalid_mutators())
@pytest.mark.parametrize("evaluator", ("deterministic", "sequential"))
def test_v7_review_invalid_expected_is_unsupported_before_worker(mutator, evaluator):
    expected = _v5_semantic_valid_view()
    mutator(expected)
    worker = _FakeReachabilityWorker(
        {("root", "seed-a"): ("done", _v5_semantic_valid_view())},
        rng_draw_counts={("root", "seed-a"): 0},
        normalize_views=False,
    )
    step = PublicReachabilityStep(
        p1_choice="move a",
        p2_choice="move b",
        expected_public_view=expected,
        rng_seeds=("seed-a",),
    )
    if evaluator == "deterministic":
        result = evaluate_deterministic_public_transition(
            worker,
            state={"node": "root"},
            side="p1",
            step=step,
        )
    else:
        result = witness_public_observation_sequence(
            worker,
            state={"node": "root"},
            side="p1",
            steps=(step,),
        )
    assert result.status is ReachabilityStatus.UNSUPPORTED
    assert not result.conclusive
    assert worker.calls == 0


@pytest.mark.parametrize("mutator", _v7_review_invalid_mutators())
@pytest.mark.parametrize("evaluator", ("deterministic", "sequential"))
@pytest.mark.parametrize("signature_mode", ("matching", "mismatching"))
def test_v7_review_invalid_returned_evidence_is_never_conclusive(
    mutator,
    evaluator,
    signature_mode,
):
    expected = _v5_semantic_valid_view()
    returned = copy.deepcopy(expected)
    if signature_mode == "mismatching":
        returned["winner"] = "different-winner"
    mutator(returned)
    worker = _FakeReachabilityWorker(
        {("root", "seed-a"): ("done", returned)},
        rng_draw_counts={("root", "seed-a"): 0},
        normalize_views=False,
    )
    step = PublicReachabilityStep(
        p1_choice="move a",
        p2_choice="move b",
        expected_public_view=expected,
        rng_seeds=("seed-a",),
    )
    if evaluator == "deterministic":
        result = evaluate_deterministic_public_transition(
            worker,
            state={"node": "root"},
            side="p1",
            step=step,
        )
    else:
        result = witness_public_observation_sequence(
            worker,
            state={"node": "root"},
            side="p1",
            steps=(step,),
        )
    assert result.status is ReachabilityStatus.UNSUPPORTED
    assert not result.conclusive
    assert not result.establishes_impossibility

