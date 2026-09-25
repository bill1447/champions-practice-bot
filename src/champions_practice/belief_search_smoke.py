"""Exercise the p2 practice AI searching exact public-belief worlds."""

from __future__ import annotations

from time import perf_counter

from champions_practice.belief_search import (
    ExactBeliefWorldState,
    search_exact_belief_turn,
    search_selective_continuation,
    shortlist_belief_candidates,
    shortlist_belief_responses,
)
from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.belief_smoke import _hidden_variant_team, _public_priors
from champions_practice.belief_worlds import (
    materialize_public_belief_worlds,
    preview_choice_for_world,
)
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.position_report import (
    build_public_battle_position,
    format_belief_search_evidence,
    format_public_battle_position,
    format_selective_continuation,
)
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


def _assert_demo_redirection_counter(worker: ShowdownSearchWorker) -> None:
    state = worker.create_state(
        battle_format=CHAMPIONS_FORMAT,
        p1_team=SMOKE_TEAM,
        p2_team=SMOKE_TEAM,
        p1_preview="team 1324",
        p2_preview="team 2135",
        p1_name="Human",
        p2_name="Practice AI",
        seed=SEED,
    )
    ai_choices = worker.legal_choices(state=state, side="p2")
    human_choices = worker.legal_choices(state=state, side="p1")

    dire_claw_switch = next(
        choice
        for choice in ai_choices
        if "move direclaw +2" in choice and "switch 4" in choice
    )
    safe_reference = next(
        choice
        for choice in ai_choices
        if "move protect" in choice and "move followme" in choice
    )
    human_punish = next(
        choice
        for choice in human_choices
        if (
            "move followme" in choice
            and "move expandingforce +1 mega" in choice
        )
    )

    resolved = worker.branch_many(
        state=state,
        branches=[
            {
                "p1_choice": human_punish,
                "p2_choice": dire_claw_switch,
            }
        ],
    )
    if len(resolved) != 1:
        raise SystemExit("ERROR: demo regression branch did not resolve exactly once")
    summary = resolved[0].get("summary")
    if not isinstance(summary, dict):
        raise SystemExit("ERROR: demo regression branch returned no exact summary")
    if summary.get("field", {}).get("terrain") != "grassyterrain":
        raise SystemExit("ERROR: demo regression branch did not overwrite Psychic Terrain")
    p2_active = summary.get("p2", {}).get("active", [])
    if not p2_active or not p2_active[0] or not p2_active[0].get("fainted"):
        raise SystemExit(
            "ERROR: demo Mega Gardevoir punish did not actually KO AI Sneasler"
        )

    pruning = shortlist_belief_responses(
        worker,
        world=ExactBeliefWorldState(
            state=state,
            weight=1.0,
            label="demo-turn-one",
        ),
        ai_side="p2",
        candidate_references=[safe_reference, dire_claw_switch],
        response_limit=2,
    )
    if human_punish not in pruning.response_shortlist:
        raise SystemExit(
            "ERROR: response pruning dropped the demo Follow Me + Mega Expanding Force punish"
        )


def main() -> None:
    with ShowdownSearchWorker() as worker:
        _assert_demo_redirection_counter(worker)
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
        # Exact states contain wall-clock timestamps in Showdown's retained battle log,
        # so byte equality here is both unnecessary and flaky. Equal materialized worlds
        # above plus equal semantic recommendations below enforce the anti-cheat boundary.

        pruning = shortlist_belief_candidates(
            worker,
            worlds=standard_states,
            side="p2",
            candidate_limit=8,
        )
        variant_pruning = shortlist_belief_candidates(
            worker,
            worlds=variant_states,
            side="p2",
            candidate_limit=8,
        )
        if pruning != variant_pruning:
            raise SystemExit("ERROR: hidden truth changed autonomous candidate pruning")
        if not pruning.candidate_shortlist:
            raise SystemExit("ERROR: autonomous candidate pruning returned no actions")

        recommendation = search_exact_belief_turn(
            worker,
            worlds=standard_states,
            side="p2",
            choices=list(pruning.candidate_shortlist),
            response_limit=8,
            autonomous_responses=True,
            rng_seeds=RNG_SEEDS,
        )
        variant_recommendation = search_exact_belief_turn(
            worker,
            worlds=variant_states,
            side="p2",
            choices=list(variant_pruning.candidate_shortlist),
            response_limit=8,
            autonomous_responses=True,
            rng_seeds=RNG_SEEDS,
        )
        if recommendation != variant_recommendation:
            raise SystemExit("ERROR: human hidden truth changed the AI recommendation")
        if recommendation.world_count != 12:
            raise SystemExit(
                f"ERROR: expected 12 exact belief worlds, got {recommendation.world_count}"
            )
        if recommendation.chosen.choice not in pruning.candidate_shortlist:
            raise SystemExit("ERROR: belief search chose outside autonomous shortlist")
        if recommendation.evaluated_choices != pruning.candidate_shortlist:
            raise SystemExit("ERROR: autonomous shortlist was not fully evaluated")
        expected_forks = (
            recommendation.world_count
            * len(pruning.candidate_shortlist)
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
        if recommendation.timing.legal_cache_hits < recommendation.world_count - 1:
            raise SystemExit("ERROR: equivalent candidate legality was not cached")
        if recommendation.response_screening_branch_count > 1000:
            raise SystemExit("ERROR: autonomous response screening exceeded its budget")

        continuation = search_selective_continuation(
            worker,
            worlds=standard_states,
            first_turn=recommendation,
            candidate_limit=3,
            next_candidate_limit=4,
            next_response_limit=4,
            rng_seeds=RNG_SEEDS,
        )
        variant_continuation = search_selective_continuation(
            worker,
            worlds=variant_states,
            first_turn=variant_recommendation,
            candidate_limit=3,
            next_candidate_limit=4,
            next_response_limit=4,
            rng_seeds=RNG_SEEDS,
        )
        if continuation != variant_continuation:
            raise SystemExit("ERROR: hidden truth changed the selective continuation")
        if continuation.candidate_limit != 3 or len(continuation.ranking) != 3:
            raise SystemExit("ERROR: selective continuation did not extend three candidates")
        if continuation.branch_count > 1000:
            raise SystemExit("ERROR: selective continuation exceeded its branch budget")
        original_line = next(
            line
            for line in continuation.ranking
            if line.first_choice == recommendation.chosen.choice
        )
        if original_line.protect_chain_slots != (2,):
            raise SystemExit("ERROR: continuation lost Sneasler's consecutive-Protect state")

        position = build_public_battle_position(standard_view)
        if position.turn != 1 or position.terrain != "psychicterrain":
            raise SystemExit("ERROR: reported position lost the searched field state")
        if [active.species for active in position.player.active] != [
            "Indeedee-F",
            "Sneasler",
        ]:
            raise SystemExit("ERROR: reported position lost the AI active slots")
        if [active.species for active in position.opponent.active] != [
            "Metagross",
            "Armarouge",
        ]:
            raise SystemExit("ERROR: reported position lost the human active slots")

        worker.close_session(standard_id)
        worker.close_session(variant_id)

    print("Belief-aware exact practice AI search")
    print("Perspective: p2 AI receives its own sanitized public view of p1")
    print(f"Worlds: {recommendation.world_count} reconstructed exact Showdown states")
    print(
        f"Candidates: {pruning.legal_choice_count} legal -> "
        f"{pruning.strategic_choice_count} strategic families -> "
        f"{len(pruning.candidate_shortlist)} autonomous shortlist; "
        f"{len(recommendation.evaluated_choices)} evaluated"
    )
    print("Responses: autonomously pruned to up to 8 adversarial replies per world")
    print(f"RNG futures: {len(RNG_SEEDS)} per action/response/world")
    print(
        f"Candidate screening: {pruning.screening_branch_count} forks, "
        f"{pruning.screening_seconds * 1000:.1f} ms"
    )
    print(f"Response screening forks: {recommendation.response_screening_branch_count}")
    print(f"Exact belief forks: {recommendation.branch_count}")
    timing = recommendation.timing
    print("Timing breakdown (standard hidden-set run):")
    print(f"  Belief construction: {belief_seconds * 1000:.1f} ms")
    print(f"  World materialization: {materialize_seconds * 1000:.1f} ms")
    print(f"  Exact world reconstruction: {reconstruct_seconds * 1000:.1f} ms")
    print(f"  Candidate legal enumeration: {timing.candidate_legal_seconds * 1000:.1f} ms")
    print(f"  Response legal enumeration: {timing.response_legal_seconds * 1000:.1f} ms")
    print(f"  Response screening: {timing.response_screening_seconds * 1000:.1f} ms")
    print(f"  Exact Showdown branching: {timing.branch_seconds * 1000:.1f} ms")
    print(f"  Python scoring/aggregation: {timing.scoring_seconds * 1000:.1f} ms")
    print(f"  Legal cache: {timing.legal_cache_hits} hits / {timing.legal_cache_misses} misses")
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
    print(format_public_battle_position(position))
    print(format_belief_search_evidence(recommendation, pruning))
    print(format_selective_continuation(continuation))
    print(
        "Selected after continuation: "
        f"{continuation.chosen_choice}"
    )
    print(
        "Anti-cheat: changing the human's real hidden Metagross set changed neither "
        "one-ply nor continuation results"
    )
    print(
        "RESULT: p2 AI exact search now selectively checks what its strongest "
        "first-turn actions enable next"
    )


if __name__ == "__main__":
    main()
