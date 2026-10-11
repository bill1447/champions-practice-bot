"""Offline native oracle controls for public-equivalent pending-command histories.

Known exact fixture states are soundness oracles only, never production inputs.
This tests retention/continuation of a witnessed finite queue domain, not general
world completeness or an approved production admission path.
"""

from dataclasses import replace
from time import perf_counter

from champions_practice.belief_controller import BeliefDecisionEngine
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import (
    BeliefParticle,
    identity_member_lineage,
    public_observation_signature,
    resample_particles_by_world,
)
from champions_practice.persistent_admission_smoke import SEEDS, SPECIES, fixture
from champions_practice.queue_retention import pending_queue_key, retain_pending_queues
from champions_practice.queue_shadow import condition_queue_histories
from champions_practice.search_worker import FORCED_WAIT_CHOICE, ShowdownSearchWorker


def relevant_native(state):
    fields = (
        "hp",
        "status",
        "statusState",
        "boosts",
        "volatiles",
        "ability",
        "item",
        "isActive",
        "activeTurns",
        "activeMoveActions",
        "lastMove",
        "moveSlots",
    )
    return [
        [
            (mon["set"]["species"], {key: mon.get(key) for key in fields})
            for mon in sorted(side["pokemon"], key=lambda mon: mon["set"]["species"])
        ]
        for side in state["sides"]
    ]


def main():
    team, priors = fixture()
    own = dict(priors)
    own["Incineroar"] = (replace(priors["Incineroar"][0], nature="Jolly"),)
    own_team = "\n\n".join(own[species][0].team_text for species in SPECIES)
    witnessed = 0
    with ShowdownSearchWorker(startup_timeout_seconds=60) as worker:
        for seed in SEEDS:
            root = worker.create_state(
                battle_format=CHAMPIONS_FORMAT,
                p1_team=team,
                p2_team=own_team,
                p1_preview="team 4123",
                p2_preview="team 1234",
                seed=seed,
            )
            branches = worker.branch_many(
                state=root,
                branches=[
                    {
                        "p1_choice": "move protect, move " + move + " +1",
                        "p2_choice": "move partingshot +2, move protect",
                        "rng_seed": seed,
                        "include_state": True,
                    }
                    for move in ("darkestlariat", "partingshot")
                ],
            )
            states = [branch["state"] for branch in branches]
            views = [worker.state_view(state=state, side="p2") for state in states]
            assert views[0]["phase"] == "switch"
            assert public_observation_signature(views[0]) == public_observation_signature(views[1])
            assert pending_queue_key(states[0]) != pending_queue_key(states[1])
            batch = tuple(
                BeliefParticle(
                    state=state,
                    weight=0.5,
                    world_id="declared-set",
                    history_id=str(index),
                    p1_member_lineage=identity_member_lineage(state, "p1"),
                    p2_member_lineage=identity_member_lineage(state, "p2"),
                )
                for index, state in enumerate(states)
            )
            # The oracle history is whichever native pending class ordinary
            # one-slot resampling discards. Retention must keep both classes.
            old = resample_particles_by_world(batch, limit=1, seed=53)
            oracle = next(
                p for p in batch if pending_queue_key(p.state) != pending_queue_key(old[0].state)
            )
            kept = retain_pending_queues(batch, limit=2, seed=53)
            assert not kept.unresolved_reason and len(kept.particles) == 2
            assert any(
                pending_queue_key(p.state) == pending_queue_key(oracle.state)
                for p in kept.particles
            )
            capped = retain_pending_queues(batch, limit=1)
            assert not capped.particles and capped.unresolved_reason == "pending-queue-capacity"
            own_choice = "switch 4, pass"
            assert own_choice in worker.legal_choices(state=oracle.state, side="p2")
            child = worker.branch_many(
                state=oracle.state,
                branches=[
                    {
                        "p1_choice": FORCED_WAIT_CHOICE,
                        "p2_choice": own_choice,
                        "rng_seed": seed,
                        "include_state": True,
                    }
                ],
            )[0]["state"]
            after = worker.state_view(state=child, side="p2")
            tagged = tuple(replace(p, world_id="queue-" + p.history_id) for p in kept.particles)
            engine = BeliefDecisionEngine(
                ".", battle_format=CHAMPIONS_FORMAT, ai_team=own_team, opponent_priors=priors
            )
            # Fixed fixture RNG is used only by this oracle control. Live audit
            # shadows generate their own seeds and never receive the real seed.
            engine._particle_seed = lambda: seed
            engine.rng_sample_batches = (1,)
            update = condition_queue_histories(
                worker,
                engine,
                particles=tagged,
                own_choice=own_choice,
                after=after,
                before=views[0],
                deadline=perf_counter() + 8,
            )
            true_id = "queue-" + oracle.history_id
            assert true_id not in update.exhaustively_excluded_world_ids
            assert update.particles and true_id in update.matched_world_ids, (
                update.matched_world_ids,
                update.sampled_unresolved_world_ids,
                update.unsupported_public_evidence,
                update.structural_mismatch_examples,
            )
            for particle in update.particles:
                projection = worker.state_view(state=particle.state, side="p2")
                assert public_observation_signature(projection) == public_observation_signature(
                    after
                )
                assert worker.legal_choices(
                    state=particle.state, side="p2"
                ) == worker.legal_choices(state=child, side="p2")
                assert relevant_native(particle.state) == relevant_native(child)
                choices = {
                    side: worker.legal_choices(state=child, side=side)[0] for side in ("p1", "p2")
                }
                for future_seed in SEEDS:
                    future = [
                        worker.branch_many(
                            state=parent,
                            branches=[
                                {
                                    "p1_choice": choices["p1"],
                                    "p2_choice": choices["p2"],
                                    "rng_seed": future_seed,
                                    "include_state": True,
                                }
                            ],
                        )[0]["state"]
                        for parent in (particle.state, child)
                    ]
                    assert relevant_native(future[0]) == relevant_native(future[1])
                    assert public_observation_signature(
                        worker.state_view(state=future[0], side="p2")
                    ) == public_observation_signature(worker.state_view(state=future[1], side="p2"))
            witnessed += 1
    print(
        f"RESULT: {witnessed}/{len(SEEDS)} native pending-queue true histories retained and witnessed; false exclusions=0"
    )
    print("Oversized queue domain: unresolved, zero installable particles")
    print("Relevant native counters, volatiles, PP and matched next-boundary outcomes: equivalent")
    print("Production history admission: unchanged")


if __name__ == "__main__":
    main()
