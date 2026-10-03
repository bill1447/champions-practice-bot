"""Pinned-Showdown smoke for the isolated finite damage-roll domain."""

from __future__ import annotations

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import HypotheticalSearchWorker
from champions_practice.stochastic_domains import (
    DAMAGE_ROLL_BUCKETS,
    enumerate_showdown_damage_rolls,
)
from champions_practice.teams import SMOKE_TEAM


P1_PREVIEW = "team 1256"
P2_PREVIEW = "team 4512"
BASE_DAMAGE = 137


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
        before = worker.state_view(state=state, side="p1")

        domain = enumerate_showdown_damage_rolls(
            worker,
            state=state,
            base_damage=BASE_DAMAGE,
        )

        after = worker.state_view(state=state, side="p1")
        if before != after:
            raise SystemExit(
                "ERROR: isolated damage-roll enumeration mutated the input state"
            )
        if not domain.exhaustive:
            raise SystemExit("ERROR: damage-roll domain was not exhaustive")
        if len(domain.outcomes) != DAMAGE_ROLL_BUCKETS:
            raise SystemExit("ERROR: damage-roll domain did not contain 16 buckets")
        if tuple(outcome.bucket for outcome in domain.outcomes) != tuple(range(16)):
            raise SystemExit("ERROR: damage-roll buckets were incomplete or reordered")
        if any(outcome.rng_draw_count != 1 for outcome in domain.outcomes):
            raise SystemExit(
                "ERROR: a damage-roll bucket consumed more than one PRNG draw"
            )
        if len(domain.unique_damages) != DAMAGE_ROLL_BUCKETS:
            raise SystemExit(
                "ERROR: chosen smoke base damage did not distinguish all 16 buckets"
            )

        print("Pinned Showdown finite damage-roll domain smoke")
        print(f"Base damage: {domain.base_damage}")
        print(f"Buckets: {len(domain.outcomes)}")
        print(f"Unique damage outcomes: {len(domain.unique_damages)}")
        print(f"Damages: {domain.damages}")
        print(
            "RESULT: Battle#randomizer finite domain is exhaustive and remains "
            "isolated from transition reachability authority"
        )


if __name__ == "__main__":
    main()
