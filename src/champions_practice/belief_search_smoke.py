"""Exercise the p2 practice AI searching exact public-belief worlds."""

from __future__ import annotations

from time import perf_counter

from champions_practice.belief_search import (
    ExactBeliefWorldState,
    search_exact_belief_turn,
)
from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.belief_smoke import _hidden_variant_team, _public_priors
from champions_practice.belief_worlds import (
    materialize_public_belief_worlds,
    preview_choice_for_world,
)
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM

SEED = "sodium,00000001000000020000000300000004"
AI_PREVIEW = "team 1235"
HUMAN_PREVIEW = "team 6412"
CANDIDATES = [
    "move followme, move rockslide",
    "move followme, move closecombat +1",
    "move psychic +1, move rockslide",
    "move psychic +1, move closecombat +1",
]
RNG_SEEDS = (
    "sodium,2222222222222222222222222222222222222222222222222222222222222222",
    "sodium,cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
)


def _start_ai_view(
    worker: ShowdownSearchWorker,
    human_team: str,
) -> tuple[str, dict]:
    started = worker.start_session(
        battle_format=CHAMPIONS_FORMAT,
        p1_team=human_team,
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
    return session_id, worker.session_view(session_id, side="p2")["view"]


def _world_states(worker, belief, worlds):
    reconstructed = []
    for index, world in enumerate(worlds):
        state = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=world.team_text,
            p2_team=SMOKE_TEAM,
            p1_preview=preview_choice_for_world(belief, world),
            p2_preview=AI_PREVIEW,
            p1_name="Human Belief World",
            p2_name="Practice AI",
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
        standard_id, standard_view = _start_ai_view(worker, SMOKE_TEAM)
        variant_id, variant_view = _start_ai_view(worker, _hidden_variant_team())

        if standard_view != variant_view:
            raise SystemExit("ERROR: human hidden truth changed the p2 AI public view")

        belief_started = perf_counter()
        standard_belief = build_public_opponent_belief(standard_view)
        belief_seconds = perf_counter() - belief_started
        variant_belief = build_public_opponent_belief(variant_view)
        priors = _public_priors()
        materialize_started = perf_counter()
        standard_worlds = materialize_public_belief_worlds(
            standard_belief,
            priors,
            limit=32,
        )
        materialize_seconds = perf_counter() - materialize_started
        variant_worlds = materialize_public_belief_worlds(
            variant_belief,
            priors,
            limit=32,
        )
        if standard_worlds != variant_worlds:
            raise SystemExit("ERROR: human hidden truth changed materialized worlds")

        reconstruct_started = perf_counter()
        standard_states = _world_states(worker, standard_belief, standard_worlds)
        reconstruct_seconds = perf_counter() - reconstruct_started
        variant_states = _world_states(worker, variant_belief, variant_worlds)
        if standard_states != variant_states:
            raise SystemExit("ERROR: human hidden truth changed reconstructed exact worlds")

        recommendation = search_exact_belief_turn(
            worker,
            worlds=standard_states,
            side="p2",
            choices=CANDIDATES,
            response_limit=8,
            rng_seeds=RNG_SEEDS,
        )
        variant_recommendation = search_exact_belief_turn(
            worker,
            worlds=variant_states,
            side="p2",
            choices=CANDIDATES,
            response_limit=8,
            rng_seeds=RNG_SEEDS,
        )
        if recommendation != variant_recommendation:
            raise SystemExit("ERROR: human hidden truth changed the AI recommendation")
        if recommendation.world_count != 12:
            raise SystemExit(
                f"ERROR: expected 12 exact belief worlds, got {recommendation.world_count}"
            )
        if recommendation.chosen.choice not in CANDIDATES:
            raise SystemExit("ERROR: belief search chose outside the candidate set")
        if recommendation.evaluated_choices != tuple(CANDIDATES):
            raise SystemExit(
                "ERROR: intended candidate coverage changed: "
                f"expected {CANDIDATES!r}, got {recommendation.evaluated_choices!r}"
            )
        expected_forks = (
            recommendation.world_count
            * len(CANDIDATES)
            * 8
            * len(RNG_SEEDS)
        )
        if recommendation.branch_count != expected_forks:
            raise SystemExit(
                f"ERROR: expected {expected_forks} exact forks, "
                f"got {recommendation.branch_count}"
            )
        if len(recommendation.chosen.worlds) != recommendation.world_count:
            raise SystemExit("ERROR: chosen action was not evaluated in every world")

        worker.close_session(standard_id)
        worker.close_session(variant_id)

    print("Belief-aware exact practice AI search")
    print("Perspective: p2 AI receives its own sanitized public view of p1")
    print(f"Worlds: {recommendation.world_count} reconstructed exact Showdown states")
    print(
        f"Candidates: {len(CANDIDATES)} supplied; "
        f"{len(recommendation.evaluated_choices)} evaluated"
    )
    print("Responses: up to 8 legal human replies per world")
    print(f"RNG futures: {len(RNG_SEEDS)} per action/response/world")
    print(f"Exact forks: {recommendation.branch_count}")
    timing = recommendation.timing
    print("Timing breakdown (standard hidden-set run):")
    print(f"  Belief construction: {belief_seconds * 1000:.1f} ms")
    print(f"  World materialization: {materialize_seconds * 1000:.1f} ms")
    print(f"  Exact world reconstruction: {reconstruct_seconds * 1000:.1f} ms")
    print(f"  Candidate legal enumeration: {timing.candidate_legal_seconds * 1000:.1f} ms")
    print(f"  Response legal enumeration: {timing.response_legal_seconds * 1000:.1f} ms")
    print(f"  Exact Showdown branching: {timing.branch_seconds * 1000:.1f} ms")
    print(f"  Python scoring/aggregation: {timing.scoring_seconds * 1000:.1f} ms")
    print(f"  Belief search total: {timing.total_seconds * 1000:.1f} ms")
    measured_pipeline = (
        belief_seconds
        + materialize_seconds
        + reconstruct_seconds
        + timing.total_seconds
    )
    print(f"  Measured pipeline total: {measured_pipeline * 1000:.1f} ms")
    print(f"Chosen: {recommendation.chosen.choice}")
    print(
        "Chosen scores: "
        f"worst-world={recommendation.chosen.worst_world_score:.1f} "
        f"weighted={recommendation.chosen.weighted_score:.1f}"
    )
    print("Anti-cheat: changing the human's real hidden Metagross set changed nothing")
    print("RESULT: p2 AI exact search now evaluates actions across public-belief worlds")


if __name__ == "__main__":
    main()
