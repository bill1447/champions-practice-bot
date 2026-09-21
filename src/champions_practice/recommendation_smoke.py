"""Exercise bounded exact recommendations against a real battle snapshot."""

from __future__ import annotations

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.recommendations import (
    recommend_exact_turn_perfect_information,
)
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM

SEED = "sodium,00000001000000020000000300000004"
CANDIDATE_LIMIT = 8
RESPONSE_LIMIT = 8
FAMILY_LIMIT = 5
REFERENCE_LIMIT = 1


def main() -> None:
    with ShowdownSearchWorker() as worker:
        started = worker.start_session(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=SMOKE_TEAM,
            p2_team=SMOKE_TEAM,
            p1_name="Human",
            p2_name="AI",
            seed=SEED,
        )
        session_id = started["session_id"]
        worker.choose_session(
            session_id,
            p1_choice="team 1634",
            p2_choice="team 3125",
        )
        state = worker.session_snapshot(session_id)["state"]
        recommendation = recommend_exact_turn_perfect_information(
            worker,
            state=state,
            side="p1",
            candidate_limit=CANDIDATE_LIMIT,
            response_limit=RESPONSE_LIMIT,
            family_limit=FAMILY_LIMIT,
            reference_limit=REFERENCE_LIMIT,
        )
        worker.close_session(session_id)

    if recommendation.mode != "perfect_information":
        raise SystemExit("ERROR: recommendation mode lost its privacy warning")
    if recommendation.legal_choice_count != 174:
        raise SystemExit("ERROR: recommendation did not enumerate all p1 choices")
    if recommendation.legal_response_count != 142:
        raise SystemExit("ERROR: recommendation did not enumerate all p2 replies")
    if recommendation.strategic_choice_count != 58:
        raise SystemExit("ERROR: p1 choices did not collapse into 58 strategies")
    if recommendation.strategic_response_count != 58:
        raise SystemExit("ERROR: p2 replies did not collapse into 58 strategies")
    if len(recommendation.candidate_shortlist) != CANDIDATE_LIMIT:
        raise SystemExit("ERROR: candidate shortlist is not bounded")
    if len(recommendation.response_shortlist) != RESPONSE_LIMIT:
        raise SystemExit("ERROR: response shortlist is not bounded")
    if recommendation.result.chosen.choice not in recommendation.candidate_shortlist:
        raise SystemExit("ERROR: exact search chose outside its candidate shortlist")
    chosen_samples = [
        sample.score
        for branch in recommendation.result.chosen.branches
        for sample in branch.samples
    ]
    if not all(
        len(branch.samples) == recommendation.rng_sample_count
        for branch in recommendation.result.chosen.branches
    ):
        raise SystemExit("ERROR: final branches did not sample every RNG future")
    if len(set(chosen_samples)) == 1:
        raise SystemExit("ERROR: RNG sampling repeated one identical future")
    total_branches = (
        recommendation.pruning_branch_count + recommendation.final_branch_count
    )
    if total_branches > 500:
        raise SystemExit(
            f"ERROR: recommendation exceeded its 500-fork budget: {total_branches}"
        )

    print("Bounded exact recommendation search")
    print(
        "Legal choices: "
        f"p1={recommendation.legal_choice_count} "
        f"p2={recommendation.legal_response_count}"
    )
    print(
        "Strategic families: "
        f"p1={recommendation.strategic_choice_count} "
        f"p2={recommendation.strategic_response_count}"
    )
    print(
        "Expanded targets: "
        f"p1={recommendation.expanded_candidate_count} "
        f"p2={recommendation.expanded_response_count}"
    )
    print(
        f"Shortlists: candidates={len(recommendation.candidate_shortlist)} "
        f"responses={len(recommendation.response_shortlist)}"
    )
    print(
        f"Exact forks: pruning={recommendation.pruning_branch_count} "
        f"final={recommendation.final_branch_count} total={total_branches}"
    )
    print(f"Final RNG futures per matchup: {recommendation.rng_sample_count}")
    print(f"Chosen: {recommendation.result.chosen.choice}")
    print(
        "Chosen expected-score range: "
        f"{min(chosen_samples):.1f} to {max(chosen_samples):.1f}"
    )
    print("Mode: perfect-information analysis only; not enabled for live CTS AI")
    print("RESULT: full legal space is pruned before bounded exact minimax")


if __name__ == "__main__":
    main()
