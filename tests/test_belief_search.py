from typing import Any

from champions_practice.belief_search import (
    ExactBeliefWorldState,
    search_exact_belief_turn,
    search_selective_continuation,
    shortlist_belief_responses,
)


def _pokemon(hp: int) -> dict[str, Any]:
    return {
        "species": "Testmon",
        "hp": hp,
        "maxhp": 100,
        "fainted": hp == 0,
        "status": None,
    }


def _summary(p1_hp: int, p2_hp: int) -> dict[str, Any]:
    return {
        "ended": False,
        "winner": None,
        "field": {
            "weather": None,
            "terrain": None,
            "pseudoWeather": [],
        },
        "p1": {
            "name": "P1",
            "pokemon": [_pokemon(p1_hp)],
            "active": [],
            "sideConditions": [],
        },
        "p2": {
            "name": "P2",
            "pokemon": [_pokemon(p2_hp)],
            "active": [],
            "sideConditions": [],
        },
    }


class FakeBeliefWorker:
    def __init__(self) -> None:
        self.states = {
            "A": {
                "p1": ["attack", "safe"],
                "p2": ["counter", "protect"],
            },
            "B": {
                "p1": ["attack", "safe"],
                "p2": ["counter", "switch"],
            },
        }
        self.legal_calls = 0
        self.outcomes = {
            ("A", "attack", "counter"): _summary(10, 100),
            ("A", "attack", "protect"): _summary(60, 100),
            ("A", "safe", "counter"): _summary(80, 90),
            ("A", "safe", "protect"): _summary(85, 95),
            ("B", "attack", "counter"): _summary(100, 20),
            ("B", "attack", "switch"): _summary(100, 30),
            ("B", "safe", "counter"): _summary(80, 90),
            ("B", "safe", "switch"): _summary(82, 92),
        }

    def legal_choices(self, *, state, side):
        self.legal_calls += 1
        return self.states[state["id"]][side]

    def branch_many(self, *, state, branches):
        results = []
        for index, branch in enumerate(branches):
            results.append(
                {
                    "index": index,
                    "summary": self.outcomes[
                        (
                            state["id"],
                            branch["p1_choice"],
                            branch["p2_choice"],
                        )
                    ],
                }
            )
        return results


def test_belief_search_prefers_robust_choice_across_worlds() -> None:
    worker = FakeBeliefWorker()
    worlds = (
        ExactBeliefWorldState(state={"id": "A"}, weight=1.0, label="world-a"),
        ExactBeliefWorldState(state={"id": "B"}, weight=3.0, label="world-b"),
    )

    result = search_exact_belief_turn(
        worker,
        worlds=worlds,
        side="p1",
    )

    # Attack is excellent in world B but catastrophic in world A. The search prioritizes
    # worst-world resilience before public-prior weighted expectation.
    assert result.chosen.choice == "safe"
    assert result.world_count == 2
    assert result.evaluated_choices == ("attack", "safe")
    assert result.branch_count == 8
    assert result.response_screening_branch_count == 0
    assert result.timing.total_seconds >= 0
    assert result.timing.candidate_legal_seconds >= 0
    assert result.timing.response_legal_seconds >= 0
    assert result.timing.response_screening_seconds >= 0
    assert result.timing.branch_seconds >= 0
    assert result.timing.scoring_seconds >= 0
    assert result.timing.legal_cache_hits >= 0
    assert result.timing.legal_cache_misses >= 0
    assert {world.label for world in result.chosen.worlds} == {"world-a", "world-b"}


def test_belief_search_uses_only_choices_legal_in_every_world() -> None:
    worker = FakeBeliefWorker()
    worker.states["B"]["p1"] = ["safe"]
    worlds = (
        ExactBeliefWorldState(state={"id": "A"}, weight=1.0),
        ExactBeliefWorldState(state={"id": "B"}, weight=1.0),
    )

    result = search_exact_belief_turn(
        worker,
        worlds=worlds,
        side="p1",
        choices=["attack", "safe"],
    )

    assert [candidate.choice for candidate in result.ranking] == ["safe"]
    assert result.evaluated_choices == ("safe",)


def test_belief_search_averages_rng_before_world_minimax() -> None:
    class RngWorker(FakeBeliefWorker):
        def branch_many(self, *, state, branches):
            results = []
            for index, branch in enumerate(branches):
                base = self.outcomes[(state["id"], branch["p1_choice"], branch["p2_choice"])]
                summary = {
                    **base,
                    "p1": {
                        **base["p1"],
                        "pokemon": [
                            _pokemon(
                                base["p1"]["pokemon"][0]["hp"]
                                + (5 if branch.get("rng_seed") == "high" else -5)
                            )
                        ],
                    },
                }
                results.append({"index": index, "summary": summary})
            return results

    worker = RngWorker()
    worlds = (ExactBeliefWorldState(state={"id": "A"}, weight=1.0),)
    result = search_exact_belief_turn(
        worker,
        worlds=worlds,
        side="p1",
        choices=["safe"],
        rng_seeds=("low", "high"),
    )

    assert result.branch_count == 4
    assert result.chosen.worlds[0].legal_response_count == 2
    assert result.chosen.worlds[0].score_breakdown is not None
    assert result.chosen.worlds[0].worst_sample_summary is not None
    assert result.chosen.worlds[0].worst_sample_score is not None


def test_legal_choice_cache_reuses_equivalent_side_state() -> None:
    worker = FakeBeliefWorker()
    shared_p1 = {"pokemon": [{"moves": ["attack", "safe"]}], "active": ["p1a"]}
    worlds = (
        ExactBeliefWorldState(
            state={
                "id": "A",
                "turn": 1,
                "requestState": "move",
                "sides": [shared_p1, {"active": ["p2a"], "hidden": "first"}],
            },
            weight=1.0,
        ),
        ExactBeliefWorldState(
            state={
                "id": "B",
                "turn": 1,
                "requestState": "move",
                "sides": [shared_p1, {"active": ["p2a"], "hidden": "second"}],
            },
            weight=1.0,
        ),
    )

    result = search_exact_belief_turn(worker, worlds=worlds, side="p1")

    assert result.evaluated_choices == ("attack", "safe")
    assert result.timing.legal_cache_hits >= 1
    assert result.timing.legal_cache_misses < 4


def test_response_pruning_scores_target_variants_before_truncating() -> None:
    class TargetWorker:
        def legal_choices(self, *, state, side):
            if side == "p1":
                return [
                    "move hit +1, move hit +1",
                    "move hit +2, move hit +1",
                    "move protect, move hit +1",
                ]
            return ["move safe, move safe"]

        def branch_many(self, *, state, branches):
            results = []
            for index, branch in enumerate(branches):
                response = branch["p1_choice"]
                p2_hp = 10 if response == "move hit +1, move hit +1" else 80
                results.append({"index": index, "summary": _summary(100, p2_hp)})
            return results

    pruning = shortlist_belief_responses(
        TargetWorker(),
        world=ExactBeliefWorldState(state={"id": "target"}, weight=1.0),
        ai_side="p2",
        candidate_references=["move safe, move safe"],
        response_limit=2,
    )

    assert "move hit +1, move hit +1" in pruning.response_shortlist


def test_autonomous_response_pruning_is_bounded() -> None:
    worker = FakeBeliefWorker()
    worlds = (ExactBeliefWorldState(state={"id": "A"}, weight=1.0),)
    result = search_exact_belief_turn(
        worker,
        worlds=worlds,
        side="p1",
        choices=["safe"],
        response_limit=1,
        autonomous_responses=True,
    )
    assert result.branch_count == 1
    assert result.response_screening_branch_count > 0
    assert result.chosen.worlds[0].legal_response_count == 1


def test_selective_continuation_can_reject_a_myopic_one_ply_winner() -> None:
    class ContinuationWorker:
        legal = {
            "initial": {
                "p1": ["move greedy", "move setup"],
                "p2": ["move punish"],
            },
            "after-greedy": {
                "p1": ["move finish"],
                "p2": ["move counter"],
            },
            "after-setup": {
                "p1": ["move payoff"],
                "p2": ["move counter"],
            },
        }

        def legal_choices(self, *, state, side):
            return self.legal[state["id"]][side]

        def branch_many(self, *, state, branches):
            results = []
            for index, branch in enumerate(branches):
                state_id = state["id"]
                p1_choice = branch["p1_choice"]
                if state_id == "initial":
                    if p1_choice == "move greedy":
                        summary = _summary(100, 80)
                        next_id = "after-greedy"
                    else:
                        summary = _summary(95, 95)
                        next_id = "after-setup"
                elif state_id == "after-greedy":
                    summary = _summary(0, 80)
                    next_id = "lost"
                else:
                    summary = _summary(80, 0)
                    next_id = "won"
                result = {"index": index, "summary": summary}
                if branch.get("include_state"):
                    result["state"] = {"id": next_id, "requestState": "move"}
                results.append(result)
            return results

    worker = ContinuationWorker()
    worlds = (
        ExactBeliefWorldState(
            state={"id": "initial", "requestState": "move"},
            weight=1.0,
            label="world-a",
        ),
    )
    first_turn = search_exact_belief_turn(
        worker,
        worlds=worlds,
        side="p1",
        rng_seeds=("low",),
    )

    continuation = search_selective_continuation(
        worker,
        worlds=worlds,
        first_turn=first_turn,
        candidate_limit=2,
        next_candidate_limit=1,
        next_response_limit=1,
        rng_seeds=("low",),
    )

    assert first_turn.chosen.choice == "move greedy"
    assert continuation.chosen_choice == "move setup"
    assert continuation.ranking[0].next_search is not None
    assert continuation.ranking[0].next_search.chosen.choice == "move payoff"
    assert continuation.branch_count > 2
