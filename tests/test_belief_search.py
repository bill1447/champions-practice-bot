from typing import Any

from champions_practice.belief_search import (
    ExactBeliefWorldState,
    search_exact_belief_turn,
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
    assert result.timing.total_seconds >= 0
    assert result.timing.candidate_legal_seconds >= 0
    assert result.timing.response_legal_seconds >= 0
    assert result.timing.branch_seconds >= 0
    assert result.timing.scoring_seconds >= 0
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
                base = self.outcomes[
                    (state["id"], branch["p1_choice"], branch["p2_choice"])
                ]
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
