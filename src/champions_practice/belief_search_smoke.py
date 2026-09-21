"""Exercise exact one-ply search over public-information opponent worlds."""

from __future__ import annotations

from champions_practice.belief_search import (
    ExactBeliefWorldState,
    search_exact_belief_turn,
)
from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.belief_smoke import (
    _hidden_variant_team,
    _public_priors,
    _start_turn_one,
)
from champions_practice.belief_worlds import (
    materialize_public_belief_worlds,
    preview_choice_for_world,
)
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM

SEED = "sodium,00000001000000020000000300000004"
CANDIDATES = [
    "move followme, move rockslide",
    "move followme, move closecombat 1",
    "move psychic 1, move rockslide",
    "move psychic 1, move closecombat 1",
]
RNG_SEEDS = (
    "sodium,2222222222222222222222222222222222222222222222222222222222222222",
    "sodium,cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
)


def _world_states(worker, belief, worlds):
    reconstructed = []
    for index, world in enumerate(worlds):
        state = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=SMOKE_TEAM,
            p2_team=world.team_text,
            p1_preview="team 1235",
            p2_preview=preview_choice_for_world(belief, world),
            p1_name="Human",
            p2_name="Belief Opponent",
            seed=SEED,
        )
        reconstructed.append(
            ExactBeliefWorldState(
                state=state,
                weight=world.weight,
                label=f"world-{index + 1}",
            )
        )
    return tuple(reconstructed)


def main() -> None:
    with ShowdownSearchWorker() as worker:
        standard_id = _start_turn_one(worker, SMOKE_TEAM)
        variant_id = _start_turn_one(worker, _hidden_variant_team())

        standard_view = worker.session_view(standard_id)["view"]
        variant_view = worker.session_view(variant_id)["view"]
        if standard_view != variant_view:
            raise SystemExit("ERROR: hidden truth changed the public turn-one view")

        standard_belief = build_public_opponent_belief(standard_view)
        variant_belief = build_public_opponent_belief(variant_view)
        priors = _public_priors()
        standard_worlds = materialize_public_belief_worlds(
            standard_belief,
            priors,
            limit=32,
        )
        variant_worlds = materialize_public_belief_worlds(
            variant_belief,
            priors,
            limit=32,
        )
        if standard_worlds != variant_worlds:
            raise SystemExit("ERROR: hidden truth changed materialized worlds")

        standard_states = _world_states(worker, standard_belief, standard_worlds)
        variant_states = _world_states(worker, variant_belief, variant_worlds)
        if standard_states != variant_states:
            raise SystemExit("ERROR: hidden truth changed reconstructed exact worlds")

        recommendation = search_exact_belief_turn(
            worker,
            worlds=standard_states,
            side="p1",
            choices=CANDIDATES,
            response_limit=8,
            rng_seeds=RNG_SEEDS,
        )
        variant_recommendation = search_exact_belief_turn(
            worker,
            worlds=variant_states,
            side="p1",
            choices=CANDIDATES,
            response_limit=8,
            rng_seeds=RNG_SEEDS,
        )
        if recommendation != variant_recommendation:
            raise SystemExit("ERROR: hidden truth changed the belief-aware recommendation")
        if recommendation.world_count != 12:
            raise SystemExit(
                f"ERROR: expected 12 exact belief worlds, got {recommendation.world_count}"
            )
        if recommendation.chosen.choice not in CANDIDATES:
            raise SystemExit("ERROR: belief search chose outside the candidate set")
        if len(recommendation.chosen.worlds) != recommendation.world_count:
            raise SystemExit("ERROR: chosen action was not evaluated in every world")

        worker.close_session(standard_id)
        worker.close_session(variant_id)

    print("Belief-aware exact search")
    print(f"Worlds: {recommendation.world_count} reconstructed exact Showdown states")
    print(f"Candidates: {len(CANDIDATES)} public-player actions")
    print("Responses: up to 8 legal replies per world")
    print(f"RNG futures: {len(RNG_SEEDS)} per action/response/world")
    print(f"Exact forks: {recommendation.branch_count}")
    print(f"Chosen: {recommendation.chosen.choice}")
    print(
        "Chosen scores: "
        f"worst-world={recommendation.chosen.worst_world_score:.1f} "
        f"weighted={recommendation.chosen.weighted_score:.1f}"
    )
    print("Anti-cheat: changing the real hidden Metagross set changed nothing")
    print("RESULT: exact search now evaluates actions across public-belief worlds")


if __name__ == "__main__":
    main()
