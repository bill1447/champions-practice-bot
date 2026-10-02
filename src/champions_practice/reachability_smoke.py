"""Pinned-Showdown smoke for bounded mechanics reachability witnesses."""

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import public_observation_signature
from champions_practice.reachability import (
    PublicReachabilityStep,
    ReachabilityStatus,
    witness_public_observation_sequence,
)
from champions_practice.search_worker import ShowdownSearchWorker
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
    for digit in "023456789abcdef"
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
    with ShowdownSearchWorker() as worker:
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

        print("Pinned Showdown reachability witness smoke")
        print(f"Witness status: {witnessed.status.value}")
        print(f"Witness branches examined: {witnessed.coverage.outcomes_examined}")
        print(f"Non-witness seed: {miss_seed}")
        print(f"Non-witness status: {missed.status.value}")
        print("RESULT: witnesses are authoritative; bounded misses stay unresolved")


if __name__ == "__main__":
    main()
