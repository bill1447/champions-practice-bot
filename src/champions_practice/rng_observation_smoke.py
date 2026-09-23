"""Real-Showdown observation conditioning with independent RNG-history particles."""

from __future__ import annotations

import hashlib
import time

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import (
    BeliefParticle,
    condition_particles,
    resample_particles,
)
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM

LIVE_SEED = "sodium,deadbeef000000020000000300000004"
P1_PREVIEW = "team 3125"
P2_PREVIEW = "team 1235"
TURN_ONE_P1 = "move hypnosis +1, move imprison"
TURN_ONE_P2 = "move followme, move protect"
TURN_TWO_P1 = "switch 3, switch 4"
TURN_TWO_P2 = "switch 3, switch 4"
PARTICLE_COUNT = 24
RESAMPLE_LIMIT = 8

HUMAN_TEAM = SMOKE_TEAM.replace(
    "- Mystical Fire\n- Protect\n",
    "- Mystical Fire\n- Hypnosis\n",
)


def _particle_seed(index: int) -> str:
    digest = hashlib.sha256(f"rng-particle-{index}".encode()).hexdigest()[:32]
    return f"sodium,{digest}"


def _effective_sample_size(particles: tuple[BeliefParticle, ...]) -> float:
    denominator = sum(particle.weight * particle.weight for particle in particles)
    return 0.0 if denominator <= 0 else 1.0 / denominator


def main() -> None:
    if HUMAN_TEAM == SMOKE_TEAM:
        raise SystemExit("ERROR: RNG fixture did not replace Gardevoir Protect")

    started_at = time.perf_counter()

    with ShowdownSearchWorker() as worker:
        live = worker.start_session(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=HUMAN_TEAM,
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

        particles = tuple(
            BeliefParticle(
                state=worker.create_state(
                    battle_format=CHAMPIONS_FORMAT,
                    p1_team=HUMAN_TEAM,
                    p2_team=SMOKE_TEAM,
                    p1_preview=P1_PREVIEW,
                    p2_preview=P2_PREVIEW,
                    seed=_particle_seed(index),
                ),
                weight=1.0 / PARTICLE_COUNT,
                world_id=f"rng-{index + 1}",
                history_id=f"independent-seed-{index + 1}",
            )
            for index in range(PARTICLE_COUNT)
        )

        worker.choose_session(
            session_id,
            p1_choice=TURN_ONE_P1,
            p2_choice=TURN_ONE_P2,
        )
        after_one = worker.session_view(session_id, side="p2")["view"]

        first_at = time.perf_counter()
        first_update = condition_particles(
            worker,
            particles=particles,
            ai_side="p2",
            ai_choice=TURN_ONE_P2,
            actual_public_view=after_one,
            previews=previews,
        )
        first_seconds = time.perf_counter() - first_at
        if not first_update.particles:
            worker.close_session(session_id)
            raise SystemExit(
                "ERROR: independent RNG histories eliminated every particle on turn one"
            )

        posterior_one = resample_particles(
            first_update.particles,
            limit=RESAMPLE_LIMIT,
            seed=51,
        )

        worker.choose_session(
            session_id,
            p1_choice=TURN_TWO_P1,
            p2_choice=TURN_TWO_P2,
        )
        after_two = worker.session_view(session_id, side="p2")["view"]

        second_at = time.perf_counter()
        second_update = condition_particles(
            worker,
            particles=posterior_one,
            ai_side="p2",
            ai_choice=TURN_TWO_P2,
            actual_public_view=after_two,
            previews=previews,
        )
        second_seconds = time.perf_counter() - second_at
        worker.close_session(session_id)

    if not second_update.particles:
        raise SystemExit(
            "ERROR: conditioned independent RNG histories did not survive turn two"
        )

    posterior_two = resample_particles(
        second_update.particles,
        limit=RESAMPLE_LIMIT,
        seed=52,
    )
    posterior_mass = sum(particle.weight for particle in posterior_two)
    if abs(posterior_mass - 1.0) > 1e-9:
        raise SystemExit("ERROR: resampled posterior is not normalized")

    if any(LIVE_SEED in particle.history_id for particle in posterior_two):
        raise SystemExit("ERROR: live RNG seed leaked into particle history")

    total_seconds = time.perf_counter() - started_at
    live_status = after_one["player"]["active_details"][0]["status"]

    print("Independent-RNG Showdown observation conditioning")
    print(f"Candidate RNG particles: {PARTICLE_COUNT}")
    print(f"Live Hypnosis result: {live_status or 'miss'}")
    print(f"Turn-one branches generated: {first_update.generated}")
    print(f"Turn-one matches: {first_update.matched}")
    print(f"Turn-one posterior before resampling: {len(first_update.particles)}")
    print(f"Turn-one posterior after resampling: {len(posterior_one)}")
    print(f"Turn-two branches generated: {second_update.generated}")
    print(f"Turn-two matches: {second_update.matched}")
    print(f"Turn-two posterior before resampling: {len(second_update.particles)}")
    print(f"Posterior after resampling: {len(posterior_two)}")
    print(f"Posterior mass: {posterior_mass:.6f}")
    print(f"Effective particle count: {_effective_sample_size(posterior_two):.2f}")
    print(f"Turn-one conditioning seconds: {first_seconds:.3f}")
    print(f"Turn-two conditioning seconds: {second_seconds:.3f}")
    print(f"Total seconds: {total_seconds:.3f}")
    print("Live RNG seed supplied to filter: NO")
    print("Showdown engine: real ShowdownSearchWorker states and branches")
    print("RESULT: independent RNG histories survive public conditioning across turns")


if __name__ == "__main__":
    main()
