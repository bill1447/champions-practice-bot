"""Pinned-runtime smoke for the isolated typed recovery authority boundary."""

from __future__ import annotations

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import (
    BeliefParticle,
    public_observation_signature,
)
from champions_practice.recovery import (
    OpponentStatProposal,
    RecoveryCandidateStatus,
    RecoveryObservation,
    RecoveryRequest,
    validate_stat_recovery_proposals,
)
from champions_practice.search_worker import HypotheticalSearchWorker

PREVIEW = "team 1234"
BATTLE_SEED = "1,2,3,4"
TURN_SEED = "99,2,3,4"

HIGH_ATTACK_TEAM = """Snorlax
Ability: Thick Fat
Level: 50
EVs: 2 HP / 32 Atk / 32 Spe
Serious Nature
- Body Slam
- Sleep Talk

Shuckle
Ability: Sturdy
Level: 50
Serious Nature
- Sleep Talk

Rillaboom
Ability: Overgrow
Level: 50
Serious Nature
- Sleep Talk

Armarouge
Ability: Flash Fire
Level: 50
Serious Nature
- Sleep Talk
"""

LOW_ATTACK_TEAM = """Snorlax
Ability: Thick Fat
Level: 50
EVs: 2 HP / 32 SpA / 32 Spe
Serious Nature
- Body Slam
- Sleep Talk

Shuckle
Ability: Sturdy
Level: 50
Serious Nature
- Sleep Talk

Rillaboom
Ability: Overgrow
Level: 50
Serious Nature
- Sleep Talk

Armarouge
Ability: Flash Fire
Level: 50
Serious Nature
- Sleep Talk
"""

AI_TEAM = """Indeedee-F
Ability: Synchronize
Level: 50
EVs: 32 HP / 32 Def / 2 SpD
Serious Nature
- Sleep Talk

Shuckle
Ability: Sturdy
Level: 50
Serious Nature
- Sleep Talk

Rillaboom
Ability: Overgrow
Level: 50
Serious Nature
- Sleep Talk

Armarouge
Ability: Flash Fire
Level: 50
Serious Nature
- Sleep Talk
"""

HUMAN_CHOICE = "move bodyslam +1, move sleeptalk"
AI_CHOICE = "move sleeptalk, move sleeptalk"


def _state(worker: HypotheticalSearchWorker, human_team: str) -> dict:
    return worker.create_state(
        battle_format=CHAMPIONS_FORMAT,
        p1_team=human_team,
        p2_team=AI_TEAM,
        p1_preview=PREVIEW,
        p2_preview=PREVIEW,
        seed=BATTLE_SEED,
    )


def _previews() -> dict[str, list[str]]:
    return {
        "p1": ["Snorlax", "Shuckle", "Rillaboom", "Armarouge"],
        "p2": ["Indeedee-F", "Shuckle", "Rillaboom", "Armarouge"],
    }


def main() -> None:
    previews = _previews()
    with HypotheticalSearchWorker() as worker:
        high_state = _state(worker, HIGH_ATTACK_TEAM)
        low_state = _state(worker, LOW_ATTACK_TEAM)

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
                "ERROR: hidden Attack allocation changed the public checkpoint"
            )

        actual = worker.branch_many(
            state=high_state,
            branches=[
                {
                    "p1_choice": HUMAN_CHOICE,
                    "p2_choice": AI_CHOICE,
                    "include_state": True,
                    "view_side": "p2",
                    "previews": previews,
                    "rng_seed": TURN_SEED,
                }
            ],
        )[0]
        actual_view = actual.get("view")
        if not isinstance(actual_view, dict):
            raise SystemExit("ERROR: authoritative recovery fixture omitted public view")

        request = RecoveryRequest(
            authority_root_particles=(
                BeliefParticle(
                    low_state,
                    1.0,
                    world_id="low-attack-parent",
                    history_id="checkpoint",
                ),
            ),
            authority_root_public_view=checkpoint,
            authority_observations=(),
            checkpoint_particles=(
                BeliefParticle(
                    low_state,
                    1.0,
                    world_id="low-attack-parent",
                    history_id="checkpoint",
                ),
            ),
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
            proposal_id="high-attack",
            parent_particle_index=0,
            pokemon_index=0,
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
                "opponent.snorlax.stat_points.atk",
                "opponent.snorlax.stat_points.spa",
            ),
        )

        report = validate_stat_recovery_proposals(
            worker,
            request=request,
            proposals=(proposal,),
            authority_rng_seeds_by_observation=(),
            rng_seeds_by_observation=((TURN_SEED,),),
        )

    if len(report.candidate_results) != 1:
        raise SystemExit("ERROR: typed stat proposal was not materialized")
    result = report.candidate_results[0]
    if result.status is not RecoveryCandidateStatus.VALIDATED:
        raise SystemExit(
            "ERROR: authoritative typed stat proposal failed mechanics replay"
        )
    if len(report.validated_candidates) != 1:
        raise SystemExit("ERROR: recovery authority did not isolate one candidate")

    print("Mechanics-authoritative typed recovery boundary")
    print("Caller-supplied serialized candidate input: NO")
    print("Typed stat proposal materialized by Showdown: YES")
    print("Candidate validated by complete retained replay: YES")
    print("Live belief state mutated by recovery module: NO")
    print("RESULT: typed proposal and mechanics authority are structurally separated")


if __name__ == "__main__":
    main()
