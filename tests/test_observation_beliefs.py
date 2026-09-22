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
