"""Integration smoke for sequential observation-conditioned belief particles."""

from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.belief_smoke import _public_priors
from champions_practice.belief_worlds import (
    materialize_public_belief_worlds,
    reconstruct_midgame_belief_worlds,
)
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.midgame_reconstruction_smoke import (
    AI_PREVIEW,
    HUMAN_PREVIEW,
    SEED,
    TURN_ONE,
    TURN_TWO,
)
from champions_practice.observation_beliefs import (
    BeliefParticle,
    condition_particles,
)
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM


def main():
    with ShowdownSearchWorker() as worker:
        started = worker.start_session(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=SMOKE_TEAM,
            p2_team=SMOKE_TEAM,
            p1_name="Human",
            p2_name="Practice AI",
            seed=SEED,
        )
        session_id = started["session_id"]
        worker.choose_session(
            session_id,
            p1_choice=HUMAN_PREVIEW,
            p2_choice=AI_PREVIEW,
        )
        preview_view = worker.session_view(session_id, side="p2")["view"]
        preview_belief = build_public_opponent_belief(preview_view)
        worlds = materialize_public_belief_worlds(
            preview_belief,
            _public_priors(),
            limit=32,
        )
        reconstructed = reconstruct_midgame_belief_worlds(
            worker,
            battle_format=CHAMPIONS_FORMAT,
            belief=preview_belief,
            preview_belief=preview_belief,
            worlds=worlds,
            ai_team=SMOKE_TEAM,
            ai_preview=AI_PREVIEW,
            public_turns=(),
            opponent_side="p1",
            seed=SEED,
        )
        particles = tuple(
            BeliefParticle(
                item.state,
                item.world.weight,
                world_id=f"world-{index}",
            )
            for index, item in enumerate(reconstructed, 1)
        )
        previews = {
            "p1": preview_view["opponent"]["preview_species"],
            "p2": [
                mon["species"]
                for mon in preview_view["player"]["team"]
            ],
        }

        worker.choose_session(
            session_id,
            p1_choice=TURN_ONE.p1_choice,
            p2_choice=TURN_ONE.p2_choice,
        )
        after_one = worker.session_view(session_id, side="p2")["view"]
        first_responses = {
            particle.world_id: (TURN_ONE.p1_choice,)
            for particle in particles
        }
        first_update = condition_particles(
            worker,
            particles=particles,
            ai_side="p2",
            ai_choice=TURN_ONE.p2_choice,
            actual_public_view=after_one,
            opponent_choices=first_responses,
            previews=previews,
        )
        if not first_update.particles:
            raise SystemExit(
                "ERROR: turn-one observation eliminated every particle"
            )

        worker.choose_session(
            session_id,
            p1_choice=TURN_TWO.p1_choice,
            p2_choice=TURN_TWO.p2_choice,
        )
        after_two = worker.session_view(session_id, side="p2")["view"]
        second_responses = {
            particle.world_id: (TURN_TWO.p1_choice,)
            for particle in first_update.particles
        }
        second_update = condition_particles(
            worker,
            particles=first_update.particles,
            ai_side="p2",
            ai_choice=TURN_TWO.p2_choice,
            actual_public_view=after_two,
            opponent_choices=second_responses,
            previews=previews,
        )
        worker.close_session(session_id)

    if not second_update.particles:
        raise SystemExit(
            "ERROR: turn-two observation eliminated every particle"
        )
    posterior_mass = sum(
        particle.weight for particle in second_update.particles
    )
    if abs(posterior_mass - 1.0) > 1e-9:
        raise SystemExit(
            "ERROR: posterior particle weights are not normalized"
        )
    if any(
        particle.state.get("turn", 0) < 3
        for particle in second_update.particles
    ):
        raise SystemExit(
            "ERROR: surviving particle did not advance to observed turn"
        )

    print("Sequential observation-conditioned belief integration")
    print(f"Preview particles: {len(particles)}")
    print(f"Turn-one matches: {first_update.matched}")
    print(f"Turn-one posterior: {len(first_update.particles)}")
    print(f"Turn-two matches: {second_update.matched}")
    print(f"Turn-two posterior: {len(second_update.particles)}")
    print(f"Posterior mass: {posterior_mass:.6f}")
    print("Boundary: survival uses only sanitized public observations")
    print("RESULT: belief particles condition sequentially across turns")


if __name__ == "__main__":
    main()