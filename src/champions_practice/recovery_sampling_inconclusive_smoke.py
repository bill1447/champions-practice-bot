"""Pinned-runtime regression: finite RNG misses are recovery-inconclusive."""

from __future__ import annotations

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import (
    BeliefParticle,
    identity_member_lineage,
    public_observation_signature,
)
from champions_practice.recovery import (
    OpponentStatProposal,
    RecoveryCandidateStatus,
    RecoveryObservation,
    RecoveryOpeningAuthority,
    RecoveryRequest,
    validate_stat_recovery_proposals,
)
from champions_practice.recovery_stat_proposal_smoke import (
    AI_CHOICE,
    AI_TEAM,
    BATTLE_SEED,
    HIGH_ATTACK_TEAM,
    HUMAN_CHOICE,
    LOW_ATTACK_TEAM,
    PREVIEW,
    TURN_SEED,
    _previews,
)
from champions_practice.search_worker import HypotheticalSearchWorker


def _branch_view(
    worker: HypotheticalSearchWorker,
    *,
    state: dict,
    seed: str,
    previews: dict[str, list[str]],
) -> dict:
    result = worker.branch_many(
        state=state,
        branches=[
            {
                "p1_choice": HUMAN_CHOICE,
                "p2_choice": AI_CHOICE,
                "include_state": True,
                "view_side": "p2",
                "previews": previews,
                "rng_seed": seed,
            }
        ],
    )[0]
    view = result.get("view")
    if not isinstance(view, dict):
        raise SystemExit("ERROR: sampling fixture omitted public view")
    return view


def main() -> None:
    previews = _previews()
    with HypotheticalSearchWorker() as worker:
        low_opening = worker.create_state_with_opening_authority(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=LOW_ATTACK_TEAM,
            p2_team=AI_TEAM,
            p1_preview=PREVIEW,
            p2_preview=PREVIEW,
            seed=BATTLE_SEED,
        )
        low_state = low_opening["state"]
        high_state = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=HIGH_ATTACK_TEAM,
            p2_team=AI_TEAM,
            p1_preview=PREVIEW,
            p2_preview=PREVIEW,
            seed=BATTLE_SEED,
        )

        checkpoint = worker.state_view(
            state=low_state,
            side="p2",
            previews=previews,
        )
        high_checkpoint = worker.state_view(
            state=high_state,
            side="p2",
            previews=previews,
        )
        if public_observation_signature(checkpoint) != public_observation_signature(
            high_checkpoint
        ):
            raise SystemExit(
                "ERROR: hidden Attack allocation changed sampling checkpoint"
            )

        actual_view = _branch_view(
            worker,
            state=high_state,
            seed=TURN_SEED,
            previews=previews,
        )
        wanted = public_observation_signature(actual_view)

        miss_seed = None
        for first in range(1, 129):
            seed = f"{first},2,3,4"
            if seed == TURN_SEED:
                continue
            sampled_view = _branch_view(
                worker,
                state=high_state,
                seed=seed,
                previews=previews,
            )
            if public_observation_signature(sampled_view) != wanted:
                miss_seed = seed
                break
        if miss_seed is None:
            raise SystemExit(
                "ERROR: sampling fixture could not find a non-witness RNG seed"
            )

        root_particle = BeliefParticle(
            low_state,
            1.0,
            world_id="sampling-parent",
            history_id="checkpoint",
            p1_member_lineage=identity_member_lineage(low_state, "p1"),
            p2_member_lineage=identity_member_lineage(low_state, "p2"),
        )
        request = RecoveryRequest(
            authority_root_particles=(root_particle,),
            opening_authorities=(
                RecoveryOpeningAuthority(
                    world_id="sampling-parent",
                    history_id="checkpoint",
                    battle_format=CHAMPIONS_FORMAT,
                    p1_team=LOW_ATTACK_TEAM,
                    p2_team=AI_TEAM,
                    p1_name="Search P1",
                    p2_name="Search P2",
                    seed=BATTLE_SEED,
                    p1_preview_choice=PREVIEW,
                    p2_preview_choice=PREVIEW,
                    p1_root_to_input=low_opening["preview_lineage"]["p1"],
                    p2_root_to_input=low_opening["preview_lineage"]["p2"],
                ),
            ),
            authority_root_public_view=checkpoint,
            authority_observations=(),
            authority_history_complete=True,
            checkpoint_particles=(root_particle,),
            checkpoint_public_view=checkpoint,
            observations=(
                RecoveryObservation(
                    ai_choice=AI_CHOICE,
                    resolved_opponent_choice=HUMAN_CHOICE,
                    previous_public_view=checkpoint,
                    public_view=actual_view,
                ),
            ),
            ai_side="p2",
            previews=previews,
        )
        proposal = OpponentStatProposal(
            proposal_id="high-attack-witness",
            parent_particle_index=0,
            pokemon_index=0,
            root_pokemon_index=0,
            species="Snorlax",
            stat_points=(
                ("hp", 2),
                ("atk", 32),
                ("def", 0),
                ("spa", 0),
                ("spd", 0),
                ("spe", 32),
            ),
            changed_hidden_dimensions=(
                "opponent.member0.snorlax.stat_points.atk",
                "opponent.member0.snorlax.stat_points.spa",
            ),
        )

        missed = validate_stat_recovery_proposals(
            worker,
            request=request,
            proposals=(proposal,),
            authority_rng_seeds_by_observation=(),
            rng_seeds_by_observation=((miss_seed,),),
        )
        witnessed = validate_stat_recovery_proposals(
            worker,
            request=request,
            proposals=(proposal,),
            authority_rng_seeds_by_observation=(),
            rng_seeds_by_observation=((TURN_SEED,),),
        )

    missed_result = missed.candidate_results[0]
    witnessed_result = witnessed.candidate_results[0]
    if missed_result.status is not RecoveryCandidateStatus.SAMPLING_EXHAUSTED:
        raise SystemExit(
            "ERROR: finite RNG miss was treated as authoritative: "
            f"{missed_result.status.value}"
        )
    if missed_result.checkpoint_compatible is not True:
        raise SystemExit(
            "ERROR: suffix sampling miss corrupted known checkpoint compatibility"
        )
    if missed_result.final_particles:
        raise SystemExit("ERROR: sampling-exhausted candidate exposed particles")
    if witnessed_result.status is not RecoveryCandidateStatus.VALIDATED:
        raise SystemExit(
            "ERROR: same candidate did not validate with witness RNG seed: "
            f"{witnessed_result.status.value}"
        )
    if not witnessed_result.final_particles:
        raise SystemExit("ERROR: witnessed candidate returned no validated particle")

    print("Recovery sampling exhaustion authority")
    print(f"Non-witness sampled seed: {miss_seed}")
    print(f"Witness seed: {TURN_SEED}")
    print("Finite sample miss reported mechanically impossible: NO")
    print("Sampling-exhausted candidate exposed particles: NO")
    print("Same candidate validates with witness seed: YES")
    print("RESULT: not sampled never means mechanically impossible")


if __name__ == "__main__":
    main()
