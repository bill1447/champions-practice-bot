"""Real pinned-Showdown smoke for PR #181 finite damage witness conditioning."""

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.midgame_reconstruction_smoke import (
    AI_PREVIEW,
    HUMAN_PREVIEW,
    SEED,
    TURN_ONE,
)
from champions_practice.observation_beliefs import (
    BeliefParticle,
    _has_aligned_public_damage_difference,
    condition_particles,
    public_observation_signature,
)
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM


def main() -> None:
    with ShowdownSearchWorker() as worker:
        state = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=SMOKE_TEAM,
            p2_team=SMOKE_TEAM,
            p1_preview=HUMAN_PREVIEW,
            p2_preview=AI_PREVIEW,
            seed=SEED,
        )
        branch = {
            "p1_choice": TURN_ONE.p1_choice,
            "p2_choice": TURN_ONE.p2_choice,
            "rng_seed": SEED,
            "include_state": True,
            "view_side": "p2",
        }
        baseline = worker.branch_many(state=state, branches=[branch])[0]["view"]
        variants = worker.branch_many(
            state=state,
            branches=[
                {**branch, "damage_bucket": bucket}
                for bucket in range(16)
            ],
        )
        if len(variants) != 16 or any(
            variant.get("damage_bucket") != bucket
            or not isinstance(variant.get("damage_roll_calls"), int)
            or variant["damage_roll_calls"] < 1
            for bucket, variant in enumerate(variants)
        ):
            raise SystemExit("ERROR: pinned damage-bucket branch replay is incomplete")

        candidate = next(
            (
                variant
                for variant in variants
                if _has_aligned_public_damage_difference(
                    variant["view"], baseline
                )
                and public_observation_signature(variant["view"])
                != public_observation_signature(baseline)
            ),
            None,
        )
        if candidate is None:
            raise SystemExit("ERROR: fixture produced no alternative public HP roll")

        update = condition_particles(
            worker,
            particles=(BeliefParticle(state, 1.0, world_id="world"),),
            ai_side="p2",
            ai_choice=TURN_ONE.p2_choice,
            actual_public_view=candidate["view"],
            opponent_choices={"world": (TURN_ONE.p1_choice,)},
            rng_seeds=(SEED,),
        )
        if (
            update.matched_world_ids != ("world",)
            or not update.particles
            or not any(
                public_observation_signature(
                    worker.state_view(state=item.state, side="p2")
                ) == public_observation_signature(candidate["view"])
                for item in update.particles
            )
        ):
            raise SystemExit(
                "ERROR: exact public damage witness was not admitted"
            )

    print("RESULT: pinned-Showdown damage-bucket witness conditioning passed")
    print(f"Examined branches: {update.generated}")
    print("Boundary: no sampled miss becomes exhaustive exclusion")


if __name__ == "__main__":
    main()
