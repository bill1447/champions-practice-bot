"""Authority regressions for bounded, pinned damage-bucket witness conditioning."""

from __future__ import annotations

import pytest

from champions_practice.observation_beliefs import BeliefParticle, condition_particles


def _view(hp: int, *, crit: bool = False, terrain: str = "none") -> dict:
    events = [["-damage", "p2a", f"{hp}/200"]]
    if crit:
        events.insert(0, ["-crit", "p2a"])
    return {
        "turn": 2,
        "terrain": terrain,
        "player": {"active": [{"hp": hp, "condition": f"{hp}/200"}]},
        "request": {"side": {"id": "p2"}, "hp": hp},
        "public_event_delta": {
            "turn": 1,
            "events": events,
            "unsupported": [],
        },
    }


class DamageBucketWorker:
    def __init__(
        self,
        *,
        observed_hp: int,
        legal_buckets: tuple[int, ...],
        witness_terrain: str = "none",
        witness_crit: bool = False,
        attest_randomizer: bool = True,
    ) -> None:
        self.observed_hp = observed_hp
        self.legal_buckets = legal_buckets
        self.witness_terrain = witness_terrain
        self.witness_crit = witness_crit
        self.attest_randomizer = attest_randomizer
        self.probe_buckets: list[int] = []

    def legal_choices(self, *, state, side):
        assert side == "p1"
        return ["move woodhammer"]

    def branch_many(self, *, state, branches):
        results = []
        for branch in branches:
            bucket = branch.get("damage_bucket")
            if bucket is None:
                view = _view(131)
                results.append({"state": {"hp": 131}, "view": view})
                continue
            self.probe_buckets.append(bucket)
            hp = self.observed_hp if bucket in self.legal_buckets else 131
            view = _view(
                hp,
                crit=self.witness_crit and bucket in self.legal_buckets,
                terrain=self.witness_terrain if bucket in self.legal_buckets else "none",
            )
            result = {
                "state": {"hp": hp, "damage_bucket": bucket},
                "view": view,
                "damage_bucket": bucket,
            }
            if self.attest_randomizer:
                result["damage_roll_calls"] = 1
            results.append(result)
        return results


def _condition(worker: DamageBucketWorker, actual_view: dict):
    return condition_particles(
        worker,
        particles=(BeliefParticle({"hp": 177}, 1.0, world_id="world"),),
        ai_side="p2",
        ai_choice="move protect",
        actual_public_view=actual_view,
        rng_seeds=("sampled-seed",),
    )


def test_discrete_damage_bucket_witness_installs_exact_simulated_successor():
    worker = DamageBucketWorker(observed_hp=134, legal_buckets=(7,))
    result = _condition(worker, _view(134))

    assert worker.probe_buckets == list(range(16))
    assert result.generated == 17
    assert result.matched == 1
    assert result.matched_world_ids == ("world",)
    assert result.sampled_unresolved_world_ids == ()
    assert len(result.particles) == 1
    assert result.particles[0].state == {"hp": 134, "damage_bucket": 7}
    assert result.particles[0].weight == pytest.approx(1.0)
    assert "damage-bucket-7" in result.particles[0].history_id


def test_min_max_interval_cannot_invent_unenumerated_hp():
    worker = DamageBucketWorker(observed_hp=135, legal_buckets=(0, 15))
    result = _condition(worker, _view(134))

    assert worker.probe_buckets == list(range(16))
    assert result.matched == 0
    assert result.particles == ()
    assert result.sampled_unresolved_world_ids == ("world",)
    assert result.exhaustively_excluded_world_ids == ()


@pytest.mark.parametrize(
    ("terrain", "crit"),
    [("electric", False), ("none", True)],
)
def test_damage_hp_witness_cannot_erase_structural_or_crit_evidence(
    terrain: str, crit: bool
):
    worker = DamageBucketWorker(
        observed_hp=134,
        legal_buckets=(7,),
        witness_terrain=terrain,
        witness_crit=crit,
    )
    result = _condition(worker, _view(134))

    assert result.matched == 0
    assert result.particles == ()
    assert result.sampled_unresolved_world_ids == ("world",)
    assert result.exhaustively_excluded_world_ids == ()


def test_unauthenticated_damage_bucket_results_are_never_admitted():
    worker = DamageBucketWorker(
        observed_hp=134,
        legal_buckets=(7,),
        attest_randomizer=False,
    )
    result = _condition(worker, _view(134))

    assert result.matched == 0
    assert result.matched_world_ids == ()
    assert result.sampled_unresolved_world_ids == ("world",)


def test_without_corresponding_public_damage_events_no_extra_probe():
    worker = DamageBucketWorker(observed_hp=134, legal_buckets=(7,))
    expected = _view(134)
    expected["public_event_delta"]["events"] = [["-heal", "p2a", "134/200"]]
    result = _condition(worker, expected)

    assert worker.probe_buckets == []
    assert result.generated == 1
    assert result.matched == 0


def test_public_crit_must_be_present_in_exact_replayed_branch():
    worker = DamageBucketWorker(observed_hp=134, legal_buckets=(7,))
    actual = _view(134, crit=True)
    result = _condition(worker, actual)

    assert result.matched == 0
    assert result.exhaustively_excluded_world_ids == ()
