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
