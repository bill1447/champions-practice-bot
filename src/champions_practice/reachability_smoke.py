"""Pinned-Showdown smoke for witness and zero-draw disproof authority."""

from champions_practice.config import CHAMPIONS_FORMAT
import copy

from champions_practice.observation_beliefs import public_observation_signature
from champions_practice.reachability import (
    PublicReachabilityStep,
    ReachabilityStatus,
    evaluate_deterministic_public_transition,
    witness_public_observation_sequence,
)
from champions_practice.search_worker import HypotheticalSearchWorker
from champions_practice.teams import SMOKE_TEAM


P1_PREVIEW = "team 1256"
P2_PREVIEW = "team 4512"
P1_CHOICE = "move psychic +1, move protect"
P2_CHOICE = "move expandingforce +1, move protect"
WITNESS_SEED = (
    "sodium,1111111111111111111111111111111111111111111111111111111111111111"
)
ALT_SEEDS = tuple(
    f"sodium,{digit * 64}"
    for digit in "23456789abcdef"
)


def _active_hp(view: dict) -> tuple[tuple[float, ...], tuple[float, ...]]:
    player = tuple(
        float(pokemon["hp_percent"])
        for pokemon in view["player"]["active_details"]
        if isinstance(pokemon, dict)
    )
    opponent = tuple(
        float(pokemon["hp_percent"])
        for pokemon in view["opponent"]["active"]
        if isinstance(pokemon, dict)
    )
    return player, opponent


def main() -> None:
    with HypotheticalSearchWorker() as worker:
        state = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=SMOKE_TEAM,
            p2_team=SMOKE_TEAM,
            p1_preview=P1_PREVIEW,
            p2_preview=P2_PREVIEW,
            seed=(
                "sodium,87654321000000020000000300000004"
            ),
        )
        before = worker.state_view(state=state, side="p2")
        target_branch = worker.branch_many(
            state=state,
            branches=[
                {
                    "p1_choice": P1_CHOICE,
                    "p2_choice": P2_CHOICE,
                    "rng_seed": WITNESS_SEED,
                    "include_state": True,
                    "view_side": "p2",
                }
            ],
        )[0]
        target = target_branch.get("view")
        if not isinstance(target, dict):
            raise SystemExit("ERROR: witness fixture produced no public view")
        if _active_hp(before) == _active_hp(target):
            raise SystemExit(
                "ERROR: reachability fixture did not produce public damage"
            )

        witnessed = witness_public_observation_sequence(
            worker,
            state=state,
            side="p2",
            steps=(
                PublicReachabilityStep(
                    p1_choice=P1_CHOICE,
                    p2_choice=P2_CHOICE,
                    expected_public_view=target,
                    rng_seeds=(WITNESS_SEED,),
                ),
            ),
        )
        if witnessed.status is not ReachabilityStatus.WITNESSED:
            raise SystemExit(
                f"ERROR: known Showdown witness was not retained: {witnessed}"
            )

        alternatives = worker.branch_many(
            state=state,
            branches=[
                {
                    "p1_choice": P1_CHOICE,
                    "p2_choice": P2_CHOICE,
                    "rng_seed": seed,
                    "include_state": True,
                    "view_side": "p2",
                }
                for seed in ALT_SEEDS
            ],
        )
        wanted = public_observation_signature(target)
        miss_seed = next(
            (
                seed
                for seed, branch in zip(ALT_SEEDS, alternatives, strict=True)
                if isinstance(branch.get("view"), dict)
                and public_observation_signature(branch["view"]) != wanted
            ),
            None,
        )
        if miss_seed is None:
            raise SystemExit(
                "ERROR: reachability smoke could not find a distinct RNG outcome"
            )

        missed = witness_public_observation_sequence(
            worker,
            state=state,
            side="p2",
            steps=(
                PublicReachabilityStep(
                    p1_choice=P1_CHOICE,
                    p2_choice=P2_CHOICE,
                    expected_public_view=target,
                    rng_seeds=(miss_seed,),
                ),
            ),
        )
        if missed.status is not ReachabilityStatus.UNRESOLVED:
            raise SystemExit(
                "ERROR: bounded non-witness became conclusive mechanics evidence: "
                f"{missed}"
            )
        if missed.establishes_impossibility:
            raise SystemExit(
                "ERROR: finite RNG miss was promoted to impossibility"
            )

        deterministic_candidates = (
            (
                "move followme, switch 3",
                "move wideguard, switch 4",
            ),
            (
                "switch 3, switch 4",
                "switch 3, switch 4",
            ),
            (
                "move trickroom, switch 3",
                "move wideguard, switch 4",
            ),
        )
        deterministic = None
        for p1_choice, p2_choice in deterministic_candidates:
            if p1_choice not in worker.legal_choices(state=state, side="p1"):
                continue
            if p2_choice not in worker.legal_choices(state=state, side="p2"):
                continue
            branch = worker.branch_many(
                state=state,
                branches=[
                    {
                        "p1_choice": p1_choice,
                        "p2_choice": p2_choice,
                        "include_state": True,
                        "view_side": "p2",
                        "include_rng_draw_count": True,
                    }
                ],
            )[0]
            if branch.get("rng_draw_count") == 0 and isinstance(
                branch.get("view"),
                dict,
            ):
                deterministic = (p1_choice, p2_choice, branch["view"])
                break

        if deterministic is None:
            raise SystemExit(
                "ERROR: deterministic reachability smoke found no zero-draw fixture"
            )

        deterministic_p1, deterministic_p2, deterministic_view = deterministic
        deterministic_witness = evaluate_deterministic_public_transition(
            worker,
            state=state,
            side="p2",
            step=PublicReachabilityStep(
                p1_choice=deterministic_p1,
                p2_choice=deterministic_p2,
                expected_public_view=deterministic_view,
            ),
        )
        if deterministic_witness.status is not ReachabilityStatus.WITNESSED:
            raise SystemExit(
                "ERROR: zero-draw exact outcome was not witnessed: "
                f"{deterministic_witness}"
            )

        impossible_view = copy.deepcopy(deterministic_view)
        impossible_view["winner"] = "__impossible_zero_draw_winner__"
        deterministic_disproof = evaluate_deterministic_public_transition(
            worker,
            state=state,
            side="p2",
            step=PublicReachabilityStep(
                p1_choice=deterministic_p1,
                p2_choice=deterministic_p2,
                expected_public_view=impossible_view,
            ),
        )
        if (
            deterministic_disproof.status
            is not ReachabilityStatus.EXHAUSTIVELY_DISPROVED
        ):
            raise SystemExit(
                "ERROR: zero-draw mismatch did not produce exhaustive disproof: "
                f"{deterministic_disproof}"
            )

        randomized_target = copy.deepcopy(target)
        randomized_target["winner"] = "__impossible_randomized_winner__"
        randomized_mismatch = evaluate_deterministic_public_transition(
            worker,
            state=state,
            side="p2",
            step=PublicReachabilityStep(
                p1_choice=P1_CHOICE,
                p2_choice=P2_CHOICE,
                expected_public_view=randomized_target,
                rng_seeds=(WITNESS_SEED,),
            ),
        )
        if randomized_mismatch.status is not ReachabilityStatus.UNRESOLVED:
            raise SystemExit(
                "ERROR: randomized mismatch gained negative authority: "
                f"{randomized_mismatch}"
            )

        print("Pinned Showdown reachability authority smoke")
        print(f"Witness status: {witnessed.status.value}")
        print(f"Witness branches examined: {witnessed.coverage.outcomes_examined}")
        print(f"Non-witness seed: {miss_seed}")
        print(f"Non-witness status: {missed.status.value}")
        print(
            "Zero-draw commands: "
            f"{deterministic_p1!r} / {deterministic_p2!r}"
        )
        print(
            "Zero-draw disproof status: "
            f"{deterministic_disproof.status.value}"
        )
        print(
            "Randomized mismatch status: "
            f"{randomized_mismatch.status.value}"
        )
        print(
            "RESULT: zero-draw mismatches can be disproved; "
            "randomized misses stay unresolved"
        )


if __name__ == "__main__":
    main()
