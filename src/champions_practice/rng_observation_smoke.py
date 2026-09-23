"""Real-Showdown observation conditioning with independent RNG-history particles."""

from __future__ import annotations

import time

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import (
    BeliefParticle,
    condition_particles,
    public_observation_signature,
    resample_particles,
)
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM

LIVE_SEED = "sodium,deadbeef000000020000000300000004"
P1_PREVIEW = "team 2135"
P2_PREVIEW = "team 1235"
TURN_ONE_P1 = "move protect, move trickroom"
TURN_ONE_P2 = "move followme, move protect"
TURN_TWO_P1 = "move protect, move imprison"
TURN_TWO_P2 = "move followme, switch 3"
PARTICLE_COUNT = 24
RESAMPLE_LIMIT = 8


def _particle_seed(index: int) -> str:
    values = (index + 1, index + 101, index + 201, index + 301)
    return "sodium," + "".join(f"{value:08x}" for value in values)


def _effective_sample_size(particles: tuple[BeliefParticle, ...]) -> float:
    denominator = sum(particle.weight * particle.weight for particle in particles)
    return 0.0 if denominator <= 0 else 1.0 / denominator


def main() -> None:
    started_at = time.perf_counter()

    with ShowdownSearchWorker() as worker:
        live = worker.start_session(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=SMOKE_TEAM,
            p2_team=SMOKE_TEAM,
            p1_name="Human",
            p2_name="Practice AI",
            seed=LIVE_SEED,
        )
        session_id = live["session_id"]
        worker.choose_session(
            session_id,
            p1_choice=P1_PREVIEW,
            p2_choice=P2_PREVIEW,
        )
        preview = worker.session_view(session_id, side="p2")["view"]
        previews = {
            "p1": preview["opponent"]["preview_species"],
            "p2": [mon["species"] for mon in preview["player"]["team"]],
        }

        worker.choose_session(
            session_id,
            p1_choice=TURN_ONE_P1,
            p2_choice=TURN_ONE_P2,
        )
        after_one = worker.session_view(session_id, side="p2")["view"]
        after_one_signature = public_observation_signature(after_one)

        particles = []
        for index in range(PARTICLE_COUNT):
            state = worker.create_state(
                battle_format=CHAMPIONS_FORMAT,
                p1_team=SMOKE_TEAM,
                p2_team=SMOKE_TEAM,
                p1_preview=P1_PREVIEW,
                p2_preview=P2_PREVIEW,
                seed=_particle_seed(index),
            )
            resolved = worker.branch_many(
                state=state,
                branches=[
                    {
                        "p1_choice": TURN_ONE_P1,
                        "p2_choice": TURN_ONE_P2,
                        "include_state": True,
                    }
                ],
            )
            next_state = resolved[0].get("state")
            if not isinstance(next_state, dict):
                raise SystemExit("ERROR: particle turn-one branch returned no state")
            view = worker.state_view(
                state=next_state,
                side="p2",
                previews=previews,
            )
            if public_observation_signature(view) != after_one_signature:
                continue
            particles.append(
                BeliefParticle(
                    state=next_state,
                    weight=1.0,
                    world_id=f"rng-{index + 1}",
                    history_id=f"seed-{index + 1}",
                )
            )

        particles = resample_particles(tuple(particles), limit=PARTICLE_COUNT, seed=51)
        if len(particles) < 2:
            raise SystemExit(
                "ERROR: independent RNG initialization did not retain multiple particles"
            )

        worker.choose_session(
            session_id,
            p1_choice=TURN_TWO_P1,
            p2_choice=TURN_TWO_P2,
        )
        after_two = worker.session_view(session_id, side="p2")["view"]

        conditioned_at = time.perf_counter()
        update = condition_particles(
            worker,
            particles=particles,
            ai_side="p2",
            ai_choice=TURN_TWO_P2,
            actual_public_view=after_two,
            previews=previews,
        )
        conditioning_seconds = time.perf_counter() - conditioned_at
        worker.close_session(session_id)

    if not update.particles:
        raise SystemExit(
            "ERROR: independent RNG histories eliminated every particle"
        )

    posterior = resample_particles(
        update.particles,
        limit=RESAMPLE_LIMIT,
        seed=52,
    )
    posterior_mass = sum(particle.weight for particle in posterior)
    if abs(posterior_mass - 1.0) > 1e-9:
        raise SystemExit("ERROR: resampled posterior is not normalized")

    if any(LIVE_SEED in particle.history_id for particle in posterior):
        raise SystemExit("ERROR: live RNG seed leaked into particle history")

    total_seconds = time.perf_counter() - started_at

    print("Independent-RNG Showdown observation conditioning")
    print(f"Candidate RNG particles: {PARTICLE_COUNT}")
    print(f"Turn-one public-compatible particles: {len(particles)}")
    print(f"Turn-two branches generated: {update.generated}")
    print(f"Turn-two matches: {update.matched}")
    print(f"Turn-two posterior before resampling: {len(update.particles)}")
    print(f"Posterior after resampling: {len(posterior)}")
    print(f"Posterior mass: {posterior_mass:.6f}")
    print(f"Effective particle count: {_effective_sample_size(posterior):.2f}")
    print(f"Conditioning seconds: {conditioning_seconds:.3f}")
    print(f"Total seconds: {total_seconds:.3f}")
    print("Live RNG seed supplied to filter: NO")
    print("Showdown engine: real ShowdownSearchWorker states and branches")
    print("RESULT: public observation can retain independent RNG-history particles")


if __name__ == "__main__":
    main()
