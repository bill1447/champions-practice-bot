from champions_practice.observation_beliefs import (
    BeliefParticle,
    condition_particles,
    public_observation_signature,
)


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


def test_public_signature_is_order_independent():
    left = {"turn": 2, "field": {"terrain": "grassyterrain", "weather": None}}
    right = {"field": {"weather": None, "terrain": "grassyterrain"}, "turn": 2}
    assert public_observation_signature(left) == public_observation_signature(right)


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

