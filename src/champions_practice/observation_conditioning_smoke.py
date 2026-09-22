"""Integration smoke for observation-conditioned exact belief particles."""

from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.belief_smoke import _public_priors
from champions_practice.belief_worlds import materialize_public_belief_worlds, reconstruct_midgame_belief_worlds
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.midgame_reconstruction_smoke import AI_PREVIEW, HUMAN_PREVIEW, SEED, TURN_ONE, TURN_TWO
from champions_practice.observation_beliefs import BeliefParticle, condition_particles
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM


def main():
    with ShowdownSearchWorker() as worker:
        started = worker.start_session(
            battle_format=CHAMPIONS_FORMAT, p1_team=SMOKE_TEAM, p2_team=SMOKE_TEAM,
            p1_name="Human", p2_name="Practice AI", seed=SEED,
        )
        session_id = started["session_id"]
        worker.choose_session(session_id, p1_choice=HUMAN_PREVIEW, p2_choice=AI_PREVIEW)
        preview_view = worker.session_view(session_id, side="p2")["view"]
        preview_belief = build_public_opponent_belief(preview_view)
        worker.choose_session(session_id, p1_choice=TURN_ONE.p1_choice, p2_choice=TURN_ONE.p2_choice)
        after_one = worker.session_view(session_id, side="p2")["view"]
        belief = build_public_opponent_belief(after_one)
        worlds = materialize_public_belief_worlds(belief, _public_priors(), limit=32)
        reconstructed = reconstruct_midgame_belief_worlds(
            worker, battle_format=CHAMPIONS_FORMAT, belief=belief, preview_belief=preview_belief,
            worlds=worlds, ai_team=SMOKE_TEAM, ai_preview=AI_PREVIEW, public_turns=(TURN_ONE,),
            opponent_side="p1", seed=SEED,
        )
        particles = tuple(
            BeliefParticle(item.state, item.world.weight, world_id=f"world-{index}")
            for index, item in enumerate(reconstructed, 1)
        )
        worker.choose_session(session_id, p1_choice=TURN_TWO.p1_choice, p2_choice=TURN_TWO.p2_choice)
        actual = worker.session_view(session_id, side="p2")["view"]
        previews = {"p1": preview_view["opponent"]["preview_species"], "p2": [mon["species"] for mon in preview_view["player"]["team"]]}
        responses = {particle.world_id: (TURN_TWO.p1_choice,) for particle in particles}
        update = condition_particles(
            worker, particles=particles, ai_side="p2", ai_choice=TURN_TWO.p2_choice,
            actual_public_view=actual, opponent_choices=responses, previews=previews,
        )
        worker.close_session(session_id)

    if not update.particles:
        raise SystemExit("ERROR: actual public observation eliminated every particle")
    if abs(sum(p.weight for p in update.particles) - 1.0) > 1e-9:
        raise SystemExit("ERROR: posterior particle weights are not normalized")
    if any(p.state.get("turn", 0) < 3 for p in update.particles):
        raise SystemExit("ERROR: surviving particle did not advance to the observed turn")

    print("Observation-conditioned stateful belief integration")
    print(f"Prior particles: {len(particles)}")
    print(f"Turn-one posterior: {len(first_update.particles)}")\n    print(f"Generated futures: {first_update.generated + update.generated}")
    print(f"Observation matches: {update.matched}")
    print(f"Posterior particles: {len(update.particles)}")
    print("Observation: real sanitized p2 view after opponent switch + AI double switch")
    print("Boundary: posterior survival decided only by sanitized public observation")
    print("RESULT: exact belief particles advance through a real battle observation")


if __name__ == "__main__":
    main()