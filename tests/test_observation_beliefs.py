import pytest

from champions_practice.observation_beliefs import (
    BeliefParticle,
    classify_public_observation_mismatch,
    condition_particles,
    filter_choices_by_public_actions,
    is_stochastic_observation_path,
    observed_joint_move_candidates,
    observed_public_actions,
    public_observation_signature,
    public_opponent_actions_fully_observed,
    public_opponent_moves_fully_observed,
    resample_particles,
    resample_particles_by_world,
)
from champions_practice.search_worker import FORCED_WAIT_CHOICE


class FakeWorker:
    def __init__(self, views):
        self.views = views

    def legal_choices(self, *, state, side):
        return ["move a", "move b"]

    def branch_many(self, *, state, branches):
        return [
            {"state": {"id": state["id"], "branch": index}}
            for index, _branch in enumerate(branches)
        ]

    def state_view(self, *, state, side, previews=None):
        return self.views[state["branch"]]


def test_condition_particles_filters_public_mismatches_and_normalizes():
    matching = {"turn": 2, "opponent": {"active": ["A"]}}
    other = {"turn": 2, "opponent": {"active": ["B"]}}
    worker = FakeWorker([matching, other])
    update = condition_particles(
        worker,
        particles=(BeliefParticle({"id": 1}, 1.0, world_id="w1"),),
        ai_side="p2",
        ai_choice="move x",
        actual_public_view=matching,
    )

    assert update.generated == 2
    assert update.matched == 1
    assert len(update.particles) == 1
    assert update.particles[0].weight == 1.0
    assert update.structural_mismatches == 1
    assert update.structural_mismatch_paths == (
        ("$.opponent.active[0]", 1),
    )
    assert update.structural_mismatch_worlds == (("w1", 1),)
    assert len(update.structural_mismatch_examples) == 1
    example = update.structural_mismatch_examples[0]
    assert example.world_id == "w1"
    assert example.path == "$.opponent.active[0]"
    assert example.actual == "A"
    assert example.simulated == "B"


def test_public_seen_roster_exhaustively_excludes_wrong_bring_four() -> None:
    actual = {
        "turn": 2,
        "opponent": {
            "active": [
                {"species": "Rillaboom"},
                {"species": "Armarouge"},
            ],
            "revealed": [
                {"species": "Indeedee-F", "seen": True},
                {"species": "Sneasler", "seen": True},
                {"species": "Rillaboom", "seen": True},
                {"species": "Armarouge", "seen": True},
                {"species": "Gardevoir", "seen": False},
                {"species": "Metagross", "seen": False},
            ],
        },
    }

    def state(world_id: str, selected: tuple[str, ...]) -> dict:
        return {
            "id": world_id,
            "sides": [
                {
                    "pokemon": [
                        {"set": {"species": species}}
                        for species in selected
                    ]
                },
                {"pokemon": [{"set": {"species": "Gardevoir"}}]},
            ],
        }

    class RosterWorker:
        def __init__(self) -> None:
            self.branched_worlds: list[str] = []

        def legal_choices(self, *, state, side):
            assert side == "p1"
            return ["move protect, move protect"]

        def branch_many(self, *, state, branches):
            self.branched_worlds.append(state["id"])
            return [
                {
                    "state": state,
                    "view": actual,
                    "member_lineage": {"p1": [0, 1, 2, 3], "p2": [0]},
                }
                for _branch in branches
            ]

    worker = RosterWorker()
    good = BeliefParticle(
        state(
            "good",
            ("Indeedee-F", "Sneasler", "Rillaboom", "Armarouge"),
        ),
        0.5,
        world_id="good",
    )
    wrong = BeliefParticle(
        state(
            "wrong",
            ("Indeedee-F", "Sneasler", "Gardevoir", "Metagross"),
        ),
        0.5,
        world_id="wrong",
    )

    update = condition_particles(
        worker,
        particles=(good, wrong),
        ai_side="p2",
        ai_choice="move protect, move protect",
        actual_public_view=actual,
        rng_seeds=("rng",),
    )

    assert worker.branched_worlds == ["good"]
    assert update.matched_world_ids == ("good",)
    assert update.exhaustively_excluded_world_ids == ("wrong",)
    assert update.sampled_unresolved_world_ids == ()
    assert len(update.particles) == 1
    assert update.particles[0].world_id == "good"


def test_public_signature_uses_champions_opponent_hp_bucket() -> None:
    actual = {
        "turn": 2,
        "opponent": {
            "active": [
                {
                    "species": "Rillaboom",
                    "hp_percent": 28,
                    "fainted": False,
                }
            ],
            "revealed": [
                {
                    "species": "Rillaboom",
                    "hp_percent": 28,
                    "fainted": False,
                }
            ],
        },
    }
    same_public_bucket = {
        "turn": 2,
        "opponent": {
            "active": [
                {
                    "species": "Rillaboom",
                    "hp_percent": 28.9,
                    "fainted": False,
                }
            ],
            "revealed": [
                {
                    "species": "Rillaboom",
                    "hp_percent": 28.1,
                    "fainted": False,
                }
            ],
        },
    }
    next_public_bucket = {
        "turn": 2,
        "opponent": {
            "active": [
                {
                    "species": "Rillaboom",
                    "hp_percent": 29.0,
                    "fainted": False,
                }
            ],
            "revealed": [
                {
                    "species": "Rillaboom",
                    "hp_percent": 29,
                    "fainted": False,
                }
            ],
        },
    }

    assert public_observation_signature(actual) == public_observation_signature(
        same_public_bucket
    )
    assert public_observation_signature(actual) != public_observation_signature(
        next_public_bucket
    )


def test_public_signature_keeps_nonzero_champions_hp_at_one_percent() -> None:
    actual = {
        "opponent": {
            "active": [{"hp_percent": 1, "fainted": False}],
        },
    }
    precise_positive = {
        "opponent": {
            "active": [{"hp_percent": 0.9, "fainted": False}],
        },
    }

    assert public_observation_signature(actual) == public_observation_signature(
        precise_positive
    )


def test_public_signature_does_not_relax_own_side_hp() -> None:
    actual = {
        "player": {
            "active_details": [
                {"hp": 134, "maxhp": 207, "hp_percent": 64.7}
            ],
        },
    }
    simulated = {
        "player": {
            "active_details": [
                {"hp": 131, "maxhp": 207, "hp_percent": 63.3}
            ],
        },
    }

    assert public_observation_signature(actual) != public_observation_signature(
        simulated
    )


def test_public_signature_keeps_quantitative_event_hp_exact() -> None:
    actual = {
        "public_event_delta": {
            "turn": 1,
            "events": [["-damage", "p1a", "28/100"]],
            "unsupported": [],
        },
    }
    simulated = {
        "public_event_delta": {
            "turn": 1,
            "events": [["-damage", "p1a", "29/100"]],
            "unsupported": [],
        },
    }

    assert public_observation_signature(actual) != public_observation_signature(
        simulated
    )


def test_condition_particles_accepts_same_opponent_hp_bucket() -> None:
    actual = {
        "turn": 2,
        "opponent": {
            "active": [
                {
                    "species": "Rillaboom",
                    "hp_percent": 28,
                    "fainted": False,
                }
            ],
        },
    }
    worker = FakeWorker(
        [
            {
                "turn": 2,
                "opponent": {
                    "active": [
                        {
                            "species": "Rillaboom",
                            "hp_percent": 28.9,
                            "fainted": False,
                        }
                    ],
                },
            },
            {
                "turn": 2,
                "opponent": {
                    "active": [
                        {
                            "species": "Rillaboom",
                            "hp_percent": 29.0,
                            "fainted": False,
                        }
                    ],
                },
            },
        ]
    )

    update = condition_particles(
        worker,
        particles=(BeliefParticle({"id": 1}, 1.0, world_id="w1"),),
        ai_side="p2",
        ai_choice="move x",
        actual_public_view=actual,
    )

    assert update.generated == 2
    assert update.matched == 1
    assert len(update.particles) == 1
    assert update.particles[0].weight == 1.0


def test_public_signature_is_order_independent():
    left = {"turn": 2, "field": {"terrain": "grassyterrain", "weather": None}}
    right = {"field": {"weather": None, "terrain": "grassyterrain"}, "turn": 2}
    assert public_observation_signature(left) == public_observation_signature(right)


def test_public_execution_delta_distinguishes_executed_from_prevented_action():
    base = {
        "turn": 2,
        "player": {"active": ["Indeedee-F"]},
        "opponent": {"active": ["Murkrow"]},
    }
    executed = {
        **base,
        "public_execution_delta": {
            "turn": 1,
            "actions": [
                {
                    "slot": 1,
                    "outcome": "executed",
                    "move": "haze",
                    "effects": [],
                }
            ],
        },
    }
    prevented = {
        **base,
        "public_execution_delta": {
            "turn": 1,
            "actions": [
                {
                    "slot": 1,
                    "outcome": "prevented",
                    "reason": "par",
                    "effects": [],
                }
            ],
        },
    }

    assert public_observation_signature(executed) != public_observation_signature(
        prevented
    )
    kind, paths = classify_public_observation_mismatch(executed, prevented)
    assert kind == "structural"
    assert any(path.startswith("$.public_execution_delta") for path in paths)


def test_public_execution_delta_preserves_mechanically_visible_order():
    base = {
        "turn": 2,
        "player": {"active": ["Lucario", "Dusclops"]},
        "opponent": {"active": ["Snorlax", "Slowbro"]},
    }
    tackle_then_growl = {
        **base,
        "public_execution_delta": {
            "turn": 1,
            "actions": [
                {
                    "side": "opponent",
                    "slot": 1,
                    "outcome": "executed",
                    "move": "tackle",
                    "source": "selected",
                    "provenance": [],
                    "target": {"side": "player", "slot": 2},
                    "effects": ["-immune"],
                },
                {
                    "side": "opponent",
                    "slot": 2,
                    "outcome": "executed",
                    "move": "growl",
                    "source": "selected",
                    "provenance": [],
                    "target": {"side": "player", "slot": 2},
                    "effects": [],
                },
            ],
        },
    }
    growl_then_tackle = {
        **base,
        "public_execution_delta": {
            **tackle_then_growl["public_execution_delta"],
            "actions": list(
                reversed(tackle_then_growl["public_execution_delta"]["actions"])
            ),
        },
    }

    assert public_observation_signature(
        tackle_then_growl
    ) != public_observation_signature(growl_then_tackle)


def test_public_execution_delta_distinguishes_called_move_provenance():
    base = {
        "turn": 3,
        "player": {"active": ["Sandslash"]},
        "opponent": {"active": ["Vaporeon"]},
    }
    defense_curl = {
        **base,
        "public_execution_delta": {
            "turn": 2,
            "actions": [
                {
                    "side": "player",
                    "slot": 1,
                    "outcome": "executed",
                    "move": "sleeptalk",
                    "source": "selected",
                    "provenance": [],
                    "target": {"side": "player", "slot": 1},
                    "effects": [],
                },
                {
                    "side": "player",
                    "slot": 1,
                    "outcome": "executed",
                    "move": "defensecurl",
                    "source": "called",
                    "provenance": ["[from]:move:sleeptalk"],
                    "target": {"side": "player", "slot": 1},
                    "effects": [],
                },
            ],
        },
    }
    swords_dance = {
        **base,
        "public_execution_delta": {
            **defense_curl["public_execution_delta"],
            "actions": [
                defense_curl["public_execution_delta"]["actions"][0],
                {
                    **defense_curl["public_execution_delta"]["actions"][1],
                    "move": "swordsdance",
                },
            ],
        },
    }

    assert public_observation_signature(defense_curl) != public_observation_signature(
        swords_dance
    )


class ExactSelectedCommandWorker(FakeWorker):
    def validate_choices(self, *, state, side, candidates):
        return list(candidates)


def test_public_event_delta_distinguishes_substitute_outcomes():
    base = {
        "turn": 2,
        "player": {"active": ["Armarouge"]},
        "opponent": {"active": ["Snorlax"]},
    }
    broken = {
        **base,
        "public_event_delta": {
            "turn": 1,
            "events": [["-end", "p1a", "substitute"]],
        },
    }
    survived = {
        **base,
        "public_event_delta": {
            "turn": 1,
            "events": [
                ["-activate", "p1a", "move:substitute", "[damage]"],
            ],
        },
    }

    assert public_observation_signature(broken) != public_observation_signature(
        survived
    )
    kind, paths = classify_public_observation_mismatch(broken, survived)
    assert kind == "structural"
    assert any(path.startswith("$.public_event_delta") for path in paths)


def test_conditioning_rejects_same_snapshot_with_wrong_public_event_delta():
    base = {
        "turn": 2,
        "player": {"active": ["Armarouge"]},
        "opponent": {"active": ["Snorlax"]},
    }
    broken = {
        **base,
        "public_event_delta": {
            "turn": 1,
            "events": [["-end", "p1a", "substitute"]],
        },
    }
    survived = {
        **base,
        "public_event_delta": {
            "turn": 1,
            "events": [
                ["-activate", "p1a", "move:substitute", "[damage]"],
            ],
        },
    }
    worker = FakeWorker([broken, survived])

    update = condition_particles(
        worker,
        particles=(BeliefParticle({"id": 1}, 1.0, world_id="w1"),),
        ai_side="p2",
        ai_choice="move psychic +1",
        actual_public_view=broken,
    )

    assert update.generated == 2
    assert update.matched == 1
    assert len(update.particles) == 1


def test_public_signature_ignores_names_and_preserves_winner_role():
    left = {
        "winner": "Practice AI",
        "player": {"name": "Practice AI", "active": ["Indeedee-F"]},
        "opponent": {"name": "Human", "active": ["Metagross"]},
        "request": {"side": {"name": "Practice AI", "id": "p2"}},
    }
    right = {
        "winner": "Search P2",
        "player": {"name": "Search P2", "active": ["Indeedee-F"]},
        "opponent": {"name": "Search P1", "active": ["Metagross"]},
        "request": {"side": {"name": "Search P2", "id": "p2"}},
    }
    opponent_won = {
        **right,
        "winner": "Search P1",
    }

    assert public_observation_signature(left) == public_observation_signature(right)
    assert public_observation_signature(left) != public_observation_signature(opponent_won)


class SelectiveWorker(FakeWorker):
    def legal_choices(self, *, state, side):
        return ["move legal"]

    def branch_many(self, *, state, branches):
        return [{"state": {"id": state["id"], "branch": 0}} for _ in branches]


def test_condition_particles_drops_world_when_requested_response_is_illegal():
    worker = SelectiveWorker([{"turn": 2}])
    update = condition_particles(
        worker,
        particles=(BeliefParticle({"id": 1}, 1.0, world_id="w1"),),
        ai_side="p2",
        ai_choice="move x",
        actual_public_view={"turn": 2},
        opponent_choices={"w1": ("move illegal",)},
    )

    assert update.generated == 0
    assert update.matched == 0
    assert update.particles == ()

class ProgressiveRevealWorker:
    def legal_choices(self, *, state, side):
        return [f"move {move}" for move in state["hidden_moves"]]

    def branch_many(self, *, state, branches):
        resolved = []
        for branch in branches:
            response = branch["p1_choice"]
            move = response.removeprefix("move ")
            resolved.append(
                {
                    "state": {
                        **state,
                        "turn": state["turn"] + 1,
                        "revealed_moves": (*state["revealed_moves"], move),
                    }
                }
            )
        return resolved

    def state_view(self, *, state, side, previews=None):
        return {
            "turn": state["turn"],
            "opponent": {
                "active": ["Metagross"],
                "revealed_moves": list(state["revealed_moves"]),
            },
        }


def test_progressive_move_revelation_narrows_worlds_without_exposing_other_moves():
    worker = ProgressiveRevealWorker()
    particles = (
        BeliefParticle(
            {
                "turn": 1,
                "hidden_moves": ("psychicfangs", "protect", "bulletpunch", "stompingtantrum"),
                "revealed_moves": (),
            },
            1 / 3,
            world_id="has-both",
        ),
        BeliefParticle(
            {
                "turn": 1,
                "hidden_moves": ("psychicfangs", "bulletpunch", "stompingtantrum", "icepunch"),
                "revealed_moves": (),
            },
            1 / 3,
            world_id="has-first-only",
        ),
        BeliefParticle(
            {
                "turn": 1,
                "hidden_moves": ("protect", "bulletpunch", "stompingtantrum", "icepunch"),
                "revealed_moves": (),
            },
            1 / 3,
            world_id="missing-first",
        ),
    )

    after_first = condition_particles(
        worker,
        particles=particles,
        ai_side="p2",
        ai_choice="move protect",
        actual_public_view={
            "turn": 2,
            "opponent": {
                "active": ["Metagross"],
                "revealed_moves": ["psychicfangs"],
            },
        },
    )

    assert {particle.world_id for particle in after_first.particles} == {
        "has-both",
        "has-first-only",
    }
    assert sum(particle.weight for particle in after_first.particles) == 1.0
    for particle in after_first.particles:
        view = worker.state_view(state=particle.state, side="p2")
        assert view["opponent"]["revealed_moves"] == ["psychicfangs"]
        assert "hidden_moves" not in view["opponent"]

    after_second = condition_particles(
        worker,
        particles=after_first.particles,
        ai_side="p2",
        ai_choice="move protect",
        actual_public_view={
            "turn": 3,
            "opponent": {
                "active": ["Metagross"],
                "revealed_moves": ["psychicfangs", "protect"],
            },
        },
    )

    assert [particle.world_id for particle in after_second.particles] == ["has-both"]
    assert after_second.particles[0].weight == 1.0
    final_view = worker.state_view(state=after_second.particles[0].state, side="p2")
    assert final_view["opponent"]["revealed_moves"] == ["psychicfangs", "protect"]
    assert "hidden_moves" not in final_view["opponent"]

class ItemRevealWorker:
    def legal_choices(self, *, state, side):
        return ["move tackle"]

    def branch_many(self, *, state, branches):
        resolved = []
        for _branch in branches:
            damage = 20 if state["turn"] == 1 else 40
            hp = max(0, state["hp"] - damage)
            item_consumed = state["item_consumed"]
            revealed_item = state["revealed_item"]
            if (
                state["hidden_item"] == "sitrusberry"
                and not item_consumed
                and hp > 0
                and hp <= 50
            ):
                hp += 25
                item_consumed = True
                revealed_item = "sitrusberry"
            resolved.append(
                {
                    "state": {
                        **state,
                        "turn": state["turn"] + 1,
                        "hp": hp,
                        "item_consumed": item_consumed,
                        "revealed_item": revealed_item,
                    }
                }
            )
        return resolved

    def state_view(self, *, state, side, previews=None):
        opponent = {
            "active": ["Rillaboom"],
            "hp": state["hp"],
        }
        if state["revealed_item"] is not None:
            opponent["revealed_item"] = state["revealed_item"]
        return {
            "turn": state["turn"],
            "opponent": opponent,
        }


def test_item_stays_hidden_until_public_activation_then_eliminates_incompatible_worlds():
    worker = ItemRevealWorker()
    particles = (
        BeliefParticle(
            {
                "turn": 1,
                "hp": 100,
                "hidden_item": "sitrusberry",
                "item_consumed": False,
                "revealed_item": None,
            },
            0.5,
            world_id="sitrus",
        ),
        BeliefParticle(
            {
                "turn": 1,
                "hp": 100,
                "hidden_item": "safetygoggles",
                "item_consumed": False,
                "revealed_item": None,
            },
            0.5,
            world_id="goggles",
        ),
    )

    before_activation = condition_particles(
        worker,
        particles=particles,
        ai_side="p2",
        ai_choice="move protect",
        actual_public_view={
            "turn": 2,
            "opponent": {
                "active": ["Rillaboom"],
                "hp": 80,
            },
        },
    )

    assert {particle.world_id for particle in before_activation.particles} == {
        "sitrus",
        "goggles",
    }
    assert sum(particle.weight for particle in before_activation.particles) == 1.0
    for particle in before_activation.particles:
        view = worker.state_view(state=particle.state, side="p2")
        assert "revealed_item" not in view["opponent"]
        assert "hidden_item" not in view["opponent"]

    after_activation = condition_particles(
        worker,
        particles=before_activation.particles,
        ai_side="p2",
        ai_choice="move protect",
        actual_public_view={
            "turn": 3,
            "opponent": {
                "active": ["Rillaboom"],
                "hp": 65,
                "revealed_item": "sitrusberry",
            },
        },
    )

    assert [particle.world_id for particle in after_activation.particles] == ["sitrus"]
    assert after_activation.particles[0].weight == 1.0
    final_view = worker.state_view(state=after_activation.particles[0].state, side="p2")
    assert final_view["opponent"]["revealed_item"] == "sitrusberry"
    assert "hidden_item" not in final_view["opponent"]

class BenchedStateWorker:
    def legal_choices(self, *, state, side):
        if state["turn"] == 1:
            return ["switch metagross"]
        return ["move tackle"]

    def branch_many(self, *, state, branches):
        resolved = []
        for branch in branches:
            response = branch["p1_choice"]
            next_state = {
                **state,
                "turn": state["turn"] + 1,
                "roster": {
                    name: dict(mon)
                    for name, mon in state["roster"].items()
                },
            }
            if response == "switch metagross":
                next_state["active"] = "Metagross"
            resolved.append({"state": next_state})
        return resolved

    def state_view(self, *, state, side, previews=None):
        active = state["active"]
        bench = []
        for name, mon in state["roster"].items():
            if name == active:
                continue
            public_mon = {
                "name": name,
                "hp": mon["hp"],
                "status": mon["status"],
            }
            if mon["revealed_item"] is not None:
                public_mon["revealed_item"] = mon["revealed_item"]
            bench.append(public_mon)

        active_mon = state["roster"][active]
        public_active = {
            "name": active,
            "hp": active_mon["hp"],
            "status": active_mon["status"],
        }
        if active_mon["revealed_item"] is not None:
            public_active["revealed_item"] = active_mon["revealed_item"]

        return {
            "turn": state["turn"],
            "opponent": {
                "active": [public_active],
                "bench": bench,
            },
        }


def test_benched_public_state_persists_across_switch_and_later_turn():
    worker = BenchedStateWorker()
    particles = (
        BeliefParticle(
            {
                "turn": 1,
                "active": "Rillaboom",
                "roster": {
                    "Rillaboom": {
                        "hp": 65,
                        "status": "par",
                        "revealed_item": "sitrusberry",
                        "item_consumed": True,
                        "hidden_moves": ("woodhammer", "fakeout", "uturn", "protect"),
                    },
                    "Metagross": {
                        "hp": 100,
                        "status": None,
                        "revealed_item": None,
                        "item_consumed": False,
                        "hidden_moves": ("psychicfangs", "protect", "bulletpunch", "stompingtantrum"),
                    },
                },
            },
            1.0,
            world_id="persistent-bench",
        ),
    )

    after_switch = condition_particles(
        worker,
        particles=particles,
        ai_side="p2",
        ai_choice="move protect",
        actual_public_view={
            "turn": 2,
            "opponent": {
                "active": [
                    {
                        "name": "Metagross",
                        "hp": 100,
                        "status": None,
                    }
                ],
                "bench": [
                    {
                        "name": "Rillaboom",
                        "hp": 65,
                        "status": "par",
                        "revealed_item": "sitrusberry",
                    }
                ],
            },
        },
    )

    assert len(after_switch.particles) == 1
    switched_state = after_switch.particles[0].state
    benched_rillaboom = switched_state["roster"]["Rillaboom"]
    assert benched_rillaboom["hp"] == 65
    assert benched_rillaboom["status"] == "par"
    assert benched_rillaboom["revealed_item"] == "sitrusberry"
    assert benched_rillaboom["item_consumed"] is True

    switched_view = worker.state_view(state=switched_state, side="p2")
    assert switched_view["opponent"]["bench"] == [
        {
            "name": "Rillaboom",
            "hp": 65,
            "status": "par",
            "revealed_item": "sitrusberry",
        }
    ]
    assert "hidden_moves" not in switched_view["opponent"]["bench"][0]
    assert "item_consumed" not in switched_view["opponent"]["bench"][0]

    after_later_turn = condition_particles(
        worker,
        particles=after_switch.particles,
        ai_side="p2",
        ai_choice="move protect",
        actual_public_view={
            "turn": 3,
            "opponent": {
                "active": [
                    {
                        "name": "Metagross",
                        "hp": 100,
                        "status": None,
                    }
                ],
                "bench": [
                    {
                        "name": "Rillaboom",
                        "hp": 65,
                        "status": "par",
                        "revealed_item": "sitrusberry",
                    }
                ],
            },
        },
    )

    assert len(after_later_turn.particles) == 1
    later_bench = after_later_turn.particles[0].state["roster"]["Rillaboom"]
    assert later_bench["hp"] == 65
    assert later_bench["status"] == "par"
    assert later_bench["revealed_item"] == "sitrusberry"
    assert later_bench["item_consumed"] is True
    assert after_later_turn.particles[0].weight == 1.0

class NoActionAmbiguityWorker:
    def legal_choices(self, *, state, side):
        return [f"move {move}" for move in state["hidden_moves"]]

    def branch_many(self, *, state, branches):
        resolved = []
        for branch in branches:
            response = branch["p1_choice"]
            if state["faints_before_action"]:
                next_state = {
                    **state,
                    "turn": state["turn"] + 1,
                    "hp": 0,
                    "fainted": True,
                    "revealed_moves": state["revealed_moves"],
                }
            else:
                move = response.removeprefix("move ")
                next_state = {
                    **state,
                    "turn": state["turn"] + 1,
                    "hp": 10,
                    "fainted": False,
                    "revealed_moves": (*state["revealed_moves"], move),
                }
            resolved.append({"state": next_state})
        return resolved

    def state_view(self, *, state, side, previews=None):
        return {
            "turn": state["turn"],
            "opponent": {
                "active": [
                    {
                        "name": "Metagross",
                        "hp": state["hp"],
                        "fainted": state["fainted"],
                        "revealed_moves": list(state["revealed_moves"]),
                    }
                ]
            },
        }


def test_unobserved_action_keeps_multiple_hidden_worlds_when_opponent_faints_first():
    worker = NoActionAmbiguityWorker()
    particles = (
        BeliefParticle(
            {
                "turn": 1,
                "hp": 40,
                "fainted": False,
                "faints_before_action": True,
                "hidden_moves": ("psychicfangs", "protect"),
                "revealed_moves": (),
            },
            1 / 3,
            world_id="psychic-fangs-world",
        ),
        BeliefParticle(
            {
                "turn": 1,
                "hp": 40,
                "fainted": False,
                "faints_before_action": True,
                "hidden_moves": (
                    "stompingtantrum",
                    "bulletpunch",
                    "icepunch",
                    "protect",
                ),
                "revealed_moves": (),
            },
            1 / 3,
            world_id="stomping-tantrum-world",
        ),
        BeliefParticle(
            {
                "turn": 1,
                "hp": 100,
                "fainted": False,
                "faints_before_action": False,
                "hidden_moves": ("psychicfangs", "protect"),
                "revealed_moves": (),
            },
            1 / 3,
            world_id="survives-and-acts",
        ),
    )

    update = condition_particles(
        worker,
        particles=particles,
        ai_side="p2",
        ai_choice="move knockout",
        actual_public_view={
            "turn": 2,
            "opponent": {
                "active": [
                    {
                        "name": "Metagross",
                        "hp": 0,
                        "fainted": True,
                        "revealed_moves": [],
                    }
                ]
            },
        },
    )

    assert {particle.world_id for particle in update.particles} == {
        "psychic-fangs-world",
        "stomping-tantrum-world",
    }
    assert len(update.particles) == 2
    assert all(particle.weight == 0.5 for particle in update.particles)

    for particle in update.particles:
        view = worker.state_view(state=particle.state, side="p2")
        active = view["opponent"]["active"][0]
        assert active["fainted"] is True
        assert active["revealed_moves"] == []
        assert "hidden_moves" not in active

class ProtectChainWorker:
    def legal_choices(self, *, state, side):
        return ["move protect"]

    def branch_many(self, *, state, branches):
        resolved = []
        for branch in branches:
            rng_seed = branch.get("rng_seed")
            consecutive = state["consecutive_protects"]

            if consecutive == 0:
                succeeded = True
            else:
                succeeded = rng_seed == "success"

            resolved.append(
                {
                    "state": {
                        **state,
                        "turn": state["turn"] + 1,
                        "consecutive_protects": consecutive + 1 if succeeded else 0,
                        "last_protect_succeeded": succeeded,
                        "revealed_moves": ("protect",),
                    }
                }
            )
        return resolved

    def state_view(self, *, state, side, previews=None):
        return {
            "turn": state["turn"],
            "opponent": {
                "active": [
                    {
                        "name": "Metagross",
                        "revealed_moves": list(state["revealed_moves"]),
                        "last_protect_succeeded": state["last_protect_succeeded"],
                    }
                ]
            },
        }


def test_consecutive_protect_state_persists_and_controls_next_turn_outcomes():
    worker = ProtectChainWorker()
    particles = (
        BeliefParticle(
            {
                "turn": 1,
                "consecutive_protects": 0,
                "last_protect_succeeded": False,
                "revealed_moves": (),
            },
            1.0,
            world_id="protect-chain",
        ),
    )

    after_first = condition_particles(
        worker,
        particles=particles,
        ai_side="p2",
        ai_choice="move attack",
        actual_public_view={
            "turn": 2,
            "opponent": {
                "active": [
                    {
                        "name": "Metagross",
                        "revealed_moves": ["protect"],
                        "last_protect_succeeded": True,
                    }
                ]
            },
        },
    )

    assert len(after_first.particles) == 1
    first_state = after_first.particles[0].state
    assert first_state["consecutive_protects"] == 1

    first_view = worker.state_view(state=first_state, side="p2")
    assert "consecutive_protects" not in first_view["opponent"]["active"][0]

    after_second = condition_particles(
        worker,
        particles=after_first.particles,
        ai_side="p2",
        ai_choice="move attack",
        actual_public_view={
            "turn": 3,
            "opponent": {
                "active": [
                    {
                        "name": "Metagross",
                        "revealed_moves": ["protect"],
                        "last_protect_succeeded": False,
                    }
                ]
            },
        },
        rng_seeds=("success", "fail"),
    )

    assert after_second.generated == 2
    assert after_second.matched == 1
    assert len(after_second.particles) == 1
    assert after_second.particles[0].weight == 1.0
    assert after_second.particles[0].state["consecutive_protects"] == 0
    assert "fail" in after_second.particles[0].history_id



def test_resample_particles_bounds_count_and_preserves_normalized_mass():
    particles = tuple(
        BeliefParticle(
            {"id": index},
            weight,
            world_id=f"w{index}",
        )
        for index, weight in enumerate((0.5, 0.2, 0.15, 0.1, 0.05), 1)
    )

    resampled = resample_particles(particles, limit=3, seed=51)

    assert len(resampled) <= 3
    assert abs(sum(particle.weight for particle in resampled) - 1.0) < 1e-9
    assert all(particle.weight > 0 for particle in resampled)


def test_world_aware_resampling_preserves_each_surviving_world() -> None:
    particles = (
        BeliefParticle({"id": "a1"}, 0.45, world_id="a"),
        BeliefParticle({"id": "a2"}, 0.35, world_id="a"),
        BeliefParticle({"id": "b1"}, 0.10, world_id="b"),
        BeliefParticle({"id": "c1"}, 0.06, world_id="c"),
        BeliefParticle({"id": "d1"}, 0.04, world_id="d"),
    )

    resampled = resample_particles_by_world(particles, limit=4, seed=55)

    assert len(resampled) <= 4
    assert {particle.world_id for particle in resampled} == {"a", "b", "c", "d"}
    assert sum(particle.weight for particle in resampled) == pytest.approx(1.0)



class PublicActionFilterWorker:
    choices = (
        "move psychic +1, move protect",
        "move psychic +2, move protect",
        "move trickroom, move protect",
        "move psychic +1, move closecombat +1",
    )

    def legal_choices(self, *, state, side):
        return list(self.choices)

    def branch_many(self, *, state, branches):
        resolved = []
        for index, branch in enumerate(branches):
            response = branch["p1_choice"]
            commands = [command.strip().split() for command in response.split(",")]
            actions = []
            for slot, tokens in enumerate(commands, start=1):
                if len(tokens) < 2 or tokens[0] != "move":
                    continue
                target = next(
                    (
                        int(token)
                        for token in tokens[2:]
                        if token.lstrip("+-").isdigit()
                    ),
                    None,
                )
                actions.append(
                    {
                        "slot": slot,
                        "move": tokens[1],
                        "target": target,
                    }
                )
            resolved.append(
                {
                    "state": {
                        "turn": 2,
                        "response": response,
                        "rng_seed": branch.get("rng_seed"),
                        "actions": actions,
                    },
                    "view": {
                        "turn": 2,
                        "opponent_last_actions": actions,
                    },
                    "index": index,
                }
            )
        return resolved


def test_public_actions_filter_move_and_target_before_rng_branching() -> None:
    worker = PublicActionFilterWorker()
    actual = {
        "turn": 2,
        "opponent_last_actions": [
            {"slot": 1, "move": "psychic", "target": 1},
            {"slot": 2, "move": "protect", "target": None},
        ],
    }

    update = condition_particles(
        worker,
        particles=(BeliefParticle({"turn": 1}, 1.0, world_id="world"),),
        ai_side="p2",
        ai_choice="move protect, move protect",
        actual_public_view=actual,
        rng_seeds=("rng-a", "rng-b"),
    )

    assert update.generated == 2
    assert update.matched == 2
    assert len(update.particles) == 2
    assert all(
        "move psychic +1, move protect" in particle.history_id
        for particle in update.particles
    )


def test_partial_public_action_only_constrains_observed_slot() -> None:
    worker = PublicActionFilterWorker()
    actual = {
        "turn": 2,
        "opponent_last_actions": [
            {"slot": 1, "move": "psychic", "target": 1},
        ],
    }

    update = condition_particles(
        worker,
        particles=(BeliefParticle({"turn": 1}, 1.0, world_id="world"),),
        ai_side="p2",
        ai_choice="move protect, move protect",
        actual_public_view=actual,
        rng_seeds=("rng",),
    )

    assert update.generated == 2
    assert update.matched == 2
    assert {
        particle.state["response"] for particle in update.particles
    } == {
        "move psychic +1, move protect",
        "move psychic +1, move closecombat +1",
    }


def test_public_action_filter_fails_open_when_parser_cannot_match_legal_set() -> None:
    worker = PublicActionFilterWorker()
    actual = {
        "turn": 2,
        "opponent_last_actions": [
            {"slot": 1, "move": "impossiblemove", "target": 1},
        ],
    }

    update = condition_particles(
        worker,
        particles=(BeliefParticle({"turn": 1}, 1.0, world_id="world"),),
        ai_side="p2",
        ai_choice="move protect, move protect",
        actual_public_view=actual,
        rng_seeds=("rng",),
    )

    assert update.generated == len(worker.choices)
    assert update.matched == len(worker.choices)
    assert {
        particle.state["response"] for particle in update.particles
    } == set(worker.choices)



def test_incomplete_public_action_never_uses_unrevealed_submitted_command() -> None:
    worker = PublicActionFilterWorker()
    actual = {
        "turn": 2,
        "opponent_last_actions": [
            {"slot": 1, "move": "psychic", "target": 1},
        ],
    }

    update = condition_particles(
        worker,
        particles=(BeliefParticle({"turn": 1}, 1.0, world_id="world"),),
        ai_side="p2",
        ai_choice="move protect, move protect",
        actual_public_view=actual,
        rng_seeds=("rng",),
    )

    assert update.generated == 2
    assert {
        particle.state["response"] for particle in update.particles
    } == {
        "move psychic +1, move protect",
        "move psychic +1, move closecombat +1",
    }


def _public_switch_state() -> dict:
    return {
        "sides": [
            {
                "pokemon": [
                    {"set": {"species": "Indeedee-F"}},
                    {"set": {"species": "Sneasler"}},
                    {"set": {"species": "Rillaboom"}},
                    {"set": {"species": "Armarouge"}},
                ]
            },
            {
                "pokemon": [
                    {"set": {"species": "Gardevoir"}},
                    {"set": {"species": "Metagross"}},
                ]
            },
        ]
    }


def test_mixed_public_move_and_selected_switch_resolve_particle_command() -> None:
    previous = {
        "turn": 3,
        "opponent_last_actions": [
            {"turn": 2, "slot": 1, "move": "protect", "target": -1},
            {"turn": 2, "slot": 2, "move": "trickroom", "target": None},
        ],
    }
    actual = {
        "turn": 4,
        "opponent": {
            "active": [
                {"species": "Indeedee-F"},
                {"species": "Rillaboom"},
            ]
        },
        "opponent_last_actions": [
            {"turn": 3, "slot": 1, "move": "protect", "target": -1},
            {"turn": 3, "slot": 2, "switch_species": "rillaboom"},
        ],
    }
    choices = (
        "move protect, switch 3",
        "move protect, switch 4",
        "move protect, move trickroom",
    )

    actions = observed_public_actions(
        actual,
        previous_public_view=previous,
    )
    filtered = filter_choices_by_public_actions(
        choices,
        actual,
        previous_public_view=previous,
        state=_public_switch_state(),
        side="p1",
        fail_open=False,
    )

    assert actions == (
        (1, "move", "protect", -1),
        (2, "switch", "rillaboom", None),
    )
    assert filtered == ("move protect, switch 3",)
    assert public_opponent_actions_fully_observed(
        actual,
        previous_public_view=previous,
    )
    assert not public_opponent_moves_fully_observed(
        actual,
        previous_public_view=previous,
    )
    assert observed_joint_move_candidates(
        actual,
        previous_public_view=previous,
    ) == ()


def test_public_switch_species_mapping_fails_open_for_ambiguous_projection() -> None:
    actual = {
        "turn": 4,
        "opponent": {
            "active": [
                {"species": "Indeedee-F"},
                {"species": "Rillaboom"},
            ]
        },
        "opponent_last_actions": [
            {"turn": 3, "slot": 1, "move": "protect", "target": -1},
            {"turn": 3, "slot": 2, "switch_species": "zoroark"},
        ],
    }
    choices = (
        "move protect, switch 3",
        "move protect, switch 4",
    )

    assert filter_choices_by_public_actions(
        choices,
        actual,
        state=_public_switch_state(),
        side="p1",
    ) == choices
    assert filter_choices_by_public_actions(
        choices,
        actual,
        state=_public_switch_state(),
        side="p1",
        fail_open=False,
    ) == ()


def test_prevented_public_action_completes_joint_command_evidence() -> None:
    previous = {
        "turn": 1,
        "opponent_last_actions": [],
        "public_execution_delta": {"turn": None, "actions": []},
    }
    actual = {
        "turn": 2,
        "opponent": {"active": [{"species": "Sneasler"}, {"species": "Indeedee-F"}]},
        "opponent_last_actions": [
            {"turn": 1, "slot": 1, "move": "protect", "target": -1},
        ],
        "public_execution_delta": {
            "turn": 1,
            "actions": [
                {
                    "side": "opponent",
                    "slot": 1,
                    "outcome": "executed",
                    "move": "protect",
                    "source": "selected",
                    "provenance": [],
                    "effects": [],
                },
                {
                    "side": "opponent",
                    "slot": 2,
                    "outcome": "prevented",
                    "reason": "move:imprison",
                    "attempted_move": "trickroom",
                    "effects": [],
                },
            ],
        },
    }

    candidates = observed_joint_move_candidates(
        actual,
        previous_public_view=previous,
    )

    assert "move protect, move trickroom" in candidates
    assert public_opponent_moves_fully_observed(
        actual,
        previous_public_view=previous,
    )


def test_called_execution_does_not_invent_selected_command_evidence() -> None:
    previous = {
        "turn": 1,
        "opponent_last_actions": [],
        "public_execution_delta": {"turn": None, "actions": []},
    }
    actual = {
        "turn": 2,
        "opponent": {"active": [{"species": "Sneasler"}, {"species": "Indeedee-F"}]},
        "opponent_last_actions": [
            {"turn": 1, "slot": 1, "move": "protect", "target": -1},
        ],
        "public_execution_delta": {
            "turn": 1,
            "actions": [
                {
                    "side": "opponent",
                    "slot": 2,
                    "outcome": "executed",
                    "move": "psychic",
                    "source": "called",
                    "provenance": ["[from]:move:instruct"],
                    "effects": [],
                },
            ],
        },
    }

    assert observed_joint_move_candidates(
        actual,
        previous_public_view=previous,
    ) == ()
    assert not public_opponent_moves_fully_observed(
        actual,
        previous_public_view=previous,
    )


def test_fully_public_execution_can_condition_the_revealed_command() -> None:
    worker = PublicActionFilterWorker()
    actual = {
        "turn": 2,
        "opponent_last_actions": [
            {"slot": 1, "move": "psychic", "target": 1},
            {"slot": 2, "move": "protect", "target": None},
        ],
    }

    update = condition_particles(
        worker,
        particles=(BeliefParticle({"turn": 1}, 1.0, world_id="world"),),
        ai_side="p2",
        ai_choice="move protect, move protect",
        actual_public_view=actual,
        rng_seeds=("rng",),
    )

    assert update.generated == 1
    assert len(update.particles) == 1
    assert update.particles[0].state["response"] == (
        "move psychic +1, move protect"
    )


def test_observation_mismatch_boundary_separates_stochastic_from_structural() -> None:
    actual = {
        "turn": 2,
        "field": {"terrain": "psychicterrain"},
        "opponent": {
            "active": [
                {
                    "species": "Armarouge",
                    "hp_percent": 11,
                    "status": "psn",
                    "fainted": False,
                    "boosts": {"def": -1},
                }
            ]
        },
    }
    stochastic = {
        "turn": 2,
        "field": {"terrain": "psychicterrain"},
        "opponent": {
            "active": [
                {
                    "species": "Armarouge",
                    "hp_percent": 14,
                    "status": "slp",
                    "fainted": False,
                    "boosts": {"def": 0},
                }
            ]
        },
    }
    structural = {
        **stochastic,
        "field": {"terrain": None},
    }

    kind, paths = classify_public_observation_mismatch(actual, stochastic)
    assert kind == "stochastic-only"
    assert paths
    assert all(is_stochastic_observation_path(path) for path in paths)

    kind, paths = classify_public_observation_mismatch(actual, structural)
    assert kind == "structural"
    assert "$.field.terrain" in paths


class DirectValidationWorker(PublicActionFilterWorker):
    def __init__(self):
        self.legal_calls = 0
        self.validate_calls = 0

    def legal_choices(self, *, state, side):
        self.legal_calls += 1
        return super().legal_choices(state=state, side=side)

    def validate_choices(self, *, state, side, candidates):
        self.validate_calls += 1
        legal = set(self.choices)
        return [candidate for candidate in candidates if candidate in legal]


def test_fully_observed_moves_use_bounded_validation_not_full_enumeration() -> None:
    worker = DirectValidationWorker()
    actual = {
        "turn": 2,
        "opponent": {
            "active": [
                {"species": "Indeedee-F"},
                {"species": "Sneasler"},
            ]
        },
        "opponent_last_actions": [
            {"slot": 1, "move": "psychic", "target": 1},
            {"slot": 2, "move": "protect", "target": -2},
        ],
    }

    update = condition_particles(
        worker,
        particles=(BeliefParticle({"turn": 1}, 1.0, world_id="world"),),
        ai_side="p2",
        ai_choice="move protect, move protect",
        actual_public_view=actual,
        rng_seeds=("rng",),
    )

    assert worker.validate_calls == 1
    assert worker.legal_calls == 0
    assert update.generated == 1



def test_unchanged_public_actions_do_not_constrain_later_transition() -> None:
    worker = DirectValidationWorker()
    previous = {
        "turn": 2,
        "opponent": {
            "active": [
                {"species": "Indeedee-F"},
                {"species": "Sneasler"},
            ]
        },
        "opponent_last_actions": [
            {"turn": 1, "slot": 1, "move": "psychic", "target": 1},
            {"turn": 1, "slot": 2, "move": "protect", "target": -2},
        ],
    }
    actual = {
        **previous,
        "turn": 3,
    }

    update = condition_particles(
        worker,
        particles=(BeliefParticle({"turn": 2}, 1.0, world_id="world"),),
        ai_side="p2",
        ai_choice="switch 3, pass",
        actual_public_view=actual,
        previous_public_view=previous,
        rng_seeds=("rng",),
    )

    assert worker.validate_calls == 0
    assert worker.legal_calls == 1
    assert update.generated == len(worker.choices)


def test_same_moves_on_new_turn_are_fresh_public_evidence() -> None:
    worker = DirectValidationWorker()
    previous = {
        "turn": 2,
        "opponent": {
            "active": [
                {"species": "Indeedee-F"},
                {"species": "Sneasler"},
            ]
        },
        "opponent_last_actions": [
            {"turn": 1, "slot": 1, "move": "psychic", "target": 1},
            {"turn": 1, "slot": 2, "move": "protect", "target": -2},
        ],
    }
    actual = {
        "turn": 3,
        "opponent": previous["opponent"],
        "opponent_last_actions": [
            {"turn": 2, "slot": 1, "move": "psychic", "target": 1},
            {"turn": 2, "slot": 2, "move": "protect", "target": -2},
        ],
    }

    update = condition_particles(
        worker,
        particles=(BeliefParticle({"turn": 2}, 1.0, world_id="world"),),
        ai_side="p2",
        ai_choice="move protect, move protect",
        actual_public_view=actual,
        previous_public_view=previous,
        rng_seeds=("rng",),
    )

    assert worker.validate_calls == 1
    assert worker.legal_calls == 0
    assert update.generated == 1



def test_quantitative_public_transition_payload_is_signature_authority() -> None:
    two_hits = {
        "turn": 2,
        "public_event_delta": {
            "turn": 1,
            "events": [
                [
                    "-hitcount",
                    "p2a",
                    "2",
                    "[action]",
                    "opponent",
                    "1",
                    "bulletseed",
                    "selected",
                ]
            ],
            "unsupported": [],
        },
    }
    five_hits = {
        "turn": 2,
        "public_event_delta": {
            "turn": 1,
            "events": [
                [
                    "-hitcount",
                    "p2a",
                    "5",
                    "[action]",
                    "opponent",
                    "1",
                    "bulletseed",
                    "selected",
                ]
            ],
            "unsupported": [],
        },
    }

    assert public_observation_signature(two_hits) != public_observation_signature(
        five_hits
    )


def test_unsupported_public_transition_evidence_fails_closed_before_replay() -> None:
    update = condition_particles(
        object(),
        particles=(BeliefParticle({"turn": 1}, 1.0, world_id="world"),),
        ai_side="p2",
        ai_choice="move protect",
        actual_public_view={
            "turn": 2,
            "public_event_delta": {
                "turn": 1,
                "events": [],
                "unsupported": ["futuremechanic"],
            },
        },
    )

    assert update.particles == ()
    assert update.generated == 0
    assert update.matched == 0
    assert update.structural_mismatches == 1


def test_public_signature_ignores_auxiliary_action_history() -> None:
    left = {
        "turn": 2,
        "opponent_last_actions": [
            {"turn": 1, "slot": 1, "move": "psychic", "target": 1},
        ],
        "opponent": {"active": ["A"]},
    }
    right = {
        "turn": 2,
        "opponent_last_actions": [],
        "opponent": {"active": ["A"]},
    }

    assert public_observation_signature(left) == public_observation_signature(right)


def _tracked_lineage_state() -> dict:
    return {
        "turn": 1,
        "sides": [
            {"pokemon": [{"id": "A"}, {"id": "B"}, {"id": "C"}]},
            {"pokemon": [{"id": "X"}]},
        ],
    }


class _LineageBranchWorker:
    def __init__(self, *, include_lineage: bool) -> None:
        self.include_lineage = include_lineage

    def validate_choices(self, *, state, side, candidates):
        return list(candidates)

    def legal_choices(self, *, state, side):
        return ["move human"]

    def branch_many(self, *, state, branches):
        child = {
            "turn": 2,
            "sides": [
                {
                    "pokemon": [
                        state["sides"][0]["pokemon"][2],
                        state["sides"][0]["pokemon"][1],
                        state["sides"][0]["pokemon"][0],
                    ]
                },
                {"pokemon": list(state["sides"][1]["pokemon"])},
            ],
        }
        results = []
        for _branch in branches:
            result = {"state": child, "view": {"turn": 2}}
            if self.include_lineage:
                result["member_lineage"] = {
                    "p1": [2, 1, 0],
                    "p2": [0],
                }
            results.append(result)
        return results


def test_conditioning_composes_stable_member_lineage() -> None:
    state = _tracked_lineage_state()
    particle = BeliefParticle(
        state,
        1.0,
        world_id="world",
        history_id="root",
        p1_member_lineage=(0, 1, 2),
        p2_member_lineage=(0,),
    )

    update = condition_particles(
        _LineageBranchWorker(include_lineage=True),
        particles=(particle,),
        ai_side="p2",
        ai_choice="move ai",
        actual_public_view={"turn": 2},
        previous_public_view={"turn": 1},
        rng_seeds=("seed",),
    )

    assert len(update.particles) == 1
    survivor = update.particles[0]
    assert survivor.p1_member_lineage == (2, 1, 0)
    assert survivor.p2_member_lineage == (0,)


def test_tracked_conditioning_rejects_missing_branch_member_lineage() -> None:
    state = _tracked_lineage_state()
    particle = BeliefParticle(
        state,
        1.0,
        world_id="world",
        history_id="root",
        p1_member_lineage=(0, 1, 2),
        p2_member_lineage=(0,),
    )

    with pytest.raises(RuntimeError, match="omitted required stable member lineage"):
        condition_particles(
            _LineageBranchWorker(include_lineage=False),
            particles=(particle,),
            ai_side="p2",
            ai_choice="move ai",
            actual_public_view={"turn": 2},
            previous_public_view={"turn": 1},
                rng_seeds=("seed",),
        )



def test_condition_particles_rejects_raw_empty_ai_choice() -> None:
    with pytest.raises(ValueError, match="raw empty AI choice"):
        condition_particles(
            object(),
            particles=(BeliefParticle({"turn": 1}, 1.0),),
            ai_side="p2",
            ai_choice="",
            actual_public_view={"turn": 2},
            )


def test_forced_wait_token_is_non_empty() -> None:
    assert FORCED_WAIT_CHOICE
    assert FORCED_WAIT_CHOICE.strip()


def _public_transform_test_view(
    event: list[str] | None,
    *,
    request_side: str | None = "p2",
    event_turn: int | None = 3,
) -> dict:
    request = (
        {"side": {"id": request_side}}
        if request_side is not None
        else None
    )
    events = (
        [event]
        if event is not None
        else [["-singleturn", "p1a", "move:protect"]]
    )
    return {
        "turn": 4,
        "request": request,
        "opponent": {
            "active": [
                {"species": "Gardevoir"},
                {"species": "Rillaboom"},
            ]
        },
        "opponent_last_actions": [
            {"turn": 3, "slot": 1, "move": "protect", "target": -1},
            {"turn": 3, "slot": 2, "move": "woodhammer", "target": 1},
        ],
        "public_event_delta": {
            "turn": event_turn,
            "events": events,
            "unsupported": [],
        },
    }


def test_public_no_mega_event_excludes_transform_modifiers() -> None:
    actual = _public_transform_test_view(None)

    candidates = observed_joint_move_candidates(actual)

    assert set(candidates) == {
        "move protect, move woodhammer",
        "move protect, move woodhammer +1",
    }

def test_public_mega_event_requires_mega_compatible_command() -> None:
    actual = _public_transform_test_view(
        ["-mega", "p1a", "gardevoir", "gardevoirite"]
    )

    candidates = observed_joint_move_candidates(actual)

    assert set(candidates) == {
        "move protect mega, move woodhammer",
        "move protect mega, move woodhammer +1",
        "move protect megax, move woodhammer",
        "move protect megax, move woodhammer +1",
        "move protect megay, move woodhammer",
        "move protect megay, move woodhammer +1",
    }

def test_partial_public_gardevoir_move_excludes_unseen_mega_modifier() -> None:
    actual = _public_transform_test_view(None)
    actual["opponent_last_actions"] = [
        {"turn": 3, "slot": 1, "move": "protect", "target": -1},
    ]

    responses = (
        "move protect, move trickroom",
        "move protect mega, move trickroom",
        "move protect, move followme",
    )

    assert filter_choices_by_public_actions(
        responses,
        actual,
        fail_open=False,
    ) == (
        "move protect, move trickroom",
        "move protect, move followme",
    )


def test_partial_public_gardevoir_mega_requires_mega_modifier() -> None:
    actual = _public_transform_test_view(
        ["-mega", "p1a", "gardevoir", "gardevoirite"]
    )
    actual["opponent_last_actions"] = [
        {"turn": 3, "slot": 1, "move": "protect", "target": -1},
    ]

    responses = (
        "move protect, move trickroom",
        "move protect mega, move trickroom",
        "move protect megax, move followme",
        "move protect ultra, move followme",
    )

    assert filter_choices_by_public_actions(
        responses,
        actual,
        fail_open=False,
    ) == (
        "move protect mega, move trickroom",
        "move protect megax, move followme",
    )


def test_partial_non_mega_species_keeps_legacy_fail_open_behavior() -> None:
    actual = _public_transform_test_view(None)
    actual["opponent"]["active"][0]["species"] = "Sneasler"
    actual["opponent_last_actions"] = [
        {"turn": 3, "slot": 1, "move": "protect", "target": -1},
    ]

    responses = (
        "move protect, move trickroom",
        "move protect mega, move trickroom",
    )

    assert filter_choices_by_public_actions(
        responses,
        actual,
        fail_open=False,
    ) == responses


def test_partial_transform_alignment_ambiguity_fails_open() -> None:
    actual = _public_transform_test_view(
        ["-mega", "p1a", "gardevoir", "gardevoirite"],
        event_turn=2,
    )
    actual["opponent_last_actions"] = [
        {"turn": 3, "slot": 1, "move": "protect", "target": -1},
    ]

    responses = (
        "move protect, move trickroom",
        "move protect mega, move trickroom",
    )

    assert filter_choices_by_public_actions(
        responses,
        actual,
        fail_open=False,
    ) == responses


def test_public_burst_event_requires_ultra_command() -> None:
    actual = _public_transform_test_view(
        ["-burst", "p1a", "necrozmaduskmane", "ultranecroziumz"]
    )

    assert set(observed_joint_move_candidates(actual)) == {
        "move protect ultra, move woodhammer",
        "move protect ultra, move woodhammer +1",
    }


def test_player_side_mega_does_not_invent_opponent_mega() -> None:
    actual = _public_transform_test_view(
        ["-mega", "p2a", "gardevoir", "gardevoirite"]
    )

    assert set(observed_joint_move_candidates(actual)) == {
        "move protect, move woodhammer",
        "move protect, move woodhammer +1",
    }


def test_ambiguous_transform_alignment_fails_open() -> None:
    missing_side = _public_transform_test_view(
        ["-mega", "p1a", "gardevoir", "gardevoirite"],
        request_side=None,
    )
    stale_delta = _public_transform_test_view(
        ["-mega", "p1a", "gardevoir", "gardevoirite"],
        event_turn=2,
    )

    for actual in (missing_side, stale_delta):
        candidates = observed_joint_move_candidates(actual)
        assert "move protect, move woodhammer +1" in candidates
        assert "move protect mega, move woodhammer +1" in candidates
        assert "move protect megax, move woodhammer +1" in candidates
        assert "move protect megay, move woodhammer +1" in candidates
        assert "move protect ultra, move woodhammer +1" in candidates



def test_offline_rejection_audit_records_prebranch_state_and_exact_values():
    from champions_practice.observation_beliefs import _REJECTION_AUDIT

    class DiagnosticWorker(FakeWorker):
        def branch_many(self, *, state, branches):
            return [
                {"state": {"id": state["id"], "branch": index}}
                for index, _ in enumerate(branches)
            ]

    candidate = {
        "id": 1,
        "sides": [
            {"pokemon": [
                {"isActive": True, "species": "Rillaboom", "hp": 156,
                 "maxhp": 207, "item": "sitrusberry",
                 "boosts": {"atk": -1}},
            ]},
            {"pokemon": [
                {"isActive": True, "species": "Gardevoir", "hp": 147,
                 "maxhp": 147, "item": "gardevoirite",
                 "boosts": {"def": 0}},
            ]},
        ],
    }
    records = []
    token = _REJECTION_AUDIT.set(records)
    try:
        condition_particles(
            DiagnosticWorker([{"turn": 8, "opponent": {"hp_percent": 35}},
                              {"turn": 8, "opponent": {"hp_percent": 35}}]),
            particles=(BeliefParticle(candidate, 1.0, world_id="w"),),
            ai_side="p2",
            ai_choice="move a",
            actual_public_view={"turn": 8, "opponent": {"hp_percent": 28}},
            rng_seeds=("seed-a",),
            damage_probe_limit=0,
        )
    finally:
        _REJECTION_AUDIT.reset(token)
    mismatch = next(
        item for item in records
        if item.get("outcome") == "sample-mismatch-unresolved"
    )
    assert any(
        diff["path"] == "$.opponent.hp_percent"
        and diff["actual"] == 28 and diff["simulated"] == 35
        for diff in mismatch["first_value_differences"]
    )
    assert mismatch["candidate_start_active"][0]["hp"] == 156
    assert mismatch["candidate_start_active"][0]["item"] == "sitrusberry"
    assert mismatch["candidate_start_active"][0]["boosts"]["atk"] == -1
    assert mismatch["candidate_start_active"][1]["hp"] == 147
