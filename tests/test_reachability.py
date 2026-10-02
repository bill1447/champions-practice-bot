from __future__ import annotations

import copy

import pytest

from champions_practice.reachability import (
    PUBLIC_OBSERVATION_SCHEMA_VERSION,
    PublicReachabilityStep,
    ReachabilityCoverage,
    ReachabilityResult,
    ReachabilityStatus,
    evaluate_deterministic_public_transition,
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
    raw_opponent = spec.get("opponent")
    if isinstance(raw_opponent, dict) and isinstance(raw_opponent.get("active"), list):
        for index, pokemon in enumerate(raw_opponent["active"]):
            if pokemon is None:
                opponent_active.append(None)
                continue
            opponent_active.append(
                {
                    "species": pokemon.get("species", f"Species{index + 1}"),
                    "base_species": pokemon.get(
                        "base_species",
                        pokemon.get("species", f"Species{index + 1}"),
                    ),
                    "hp_percent": pokemon.get("hp_percent", 100),
                    "fainted": pokemon.get("fainted", False),
                    "status": pokemon.get("status"),
                    "boosts": pokemon.get("boosts", {}),
                }
            )

    view = {
        "turn": turn,
        "phase": "move",
        "opponent_last_actions": [],
        "public_execution_delta": {"turn": None, "actions": []},
        "public_event_delta": {"turn": None, "events": [], "unsupported": []},
        "ended": False,
        "winner": winner,
        "field": {"weather": None, "terrain": None, "pseudo_weather": []},
        "request": {"wait": True, "side": {"pokemon": []}},
        "player": {
            "name": "Player",
            "active": [],
            "active_details": [],
            "side_conditions": [],
            "team": [],
        },
        "opponent": {
            "name": "Opponent",
            "preview_species": [],
            "side_conditions": [],
            "active": opponent_active,
            "revealed": [],
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
    assert PUBLIC_OBSERVATION_SCHEMA_VERSION == "showdown-player-view-v1"
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
