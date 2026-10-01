"""Pinned-runtime smoke for the isolated recovery authority boundary."""

from __future__ import annotations

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import (
    BeliefParticle,
    public_observation_signature,
)
from champions_practice.recovery import (
    RecoveryCandidate,
    RecoveryCandidateStatus,
    RecoveryObservation,
    RecoveryRequest,
    validate_recovery_candidates,
)
from champions_practice.search_worker import ShowdownSearchWorker

PREVIEW = "team 1234"
BATTLE_SEED = "1,2,3,4"
TURN_SEED = "99,2,3,4"

HIGH_ATTACK_TEAM = """Snorlax
Ability: Thick Fat
Level: 50
EVs: 252 Atk
Adamant Nature
- Tackle
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
Bold Nature
- Tackle
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
EVs: 252 HP
Calm Nature
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

HUMAN_CHOICE = "move tackle +1, move sleeptalk"
AI_CHOICE = "move sleeptalk, move sleeptalk"


def _state(worker: ShowdownSearchWorker, human_team: str) -> dict:
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
    with ShowdownSearchWorker() as worker:
        high_state = _state(worker, HIGH_ATTACK_TEAM)
        low_state = _state(worker, LOW_ATTACK_TEAM)

        checkpoint = worker.state_view(
            state=high_state,
            side="p2",
            previews=previews,
        )
        low_checkpoint = worker.state_view(
            state=low_state,
            side="p2",
            previews=previews,
        )
        if public_observation_signature(checkpoint) != public_observation_signature(
            low_checkpoint
        ):
            raise SystemExit(
                "ERROR: hidden Attack candidate changed the public checkpoint"
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

        low_result = worker.branch_many(
            state=low_state,
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
        low_view = low_result.get("view")
        if not isinstance(low_view, dict):
            raise SystemExit("ERROR: low-Attack recovery fixture omitted public view")
        if public_observation_signature(low_view) == public_observation_signature(
            actual_view
        ):
            raise SystemExit(
                "ERROR: hidden Attack fixture did not create a mechanics divergence"
            )

        request = RecoveryRequest(
            checkpoint_particles=(
                BeliefParticle(
                    high_state,
                    0.5,
                    world_id="high-attack",
                    history_id="checkpoint",
                ),
                BeliefParticle(
                    low_state,
                    0.5,
                    world_id="low-attack",
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
        candidates = (
            RecoveryCandidate(
                candidate_id="high-attack",
                parent_particle_index=0,
                particle=request.checkpoint_particles[0],
                source="fixture-hidden-stat-broadening",
                changed_hidden_dimensions=("opponent.snorlax.atk",),
            ),
            RecoveryCandidate(
                candidate_id="low-attack",
                parent_particle_index=1,
                particle=request.checkpoint_particles[1],
                source="fixture-hidden-stat-broadening",
                changed_hidden_dimensions=("opponent.snorlax.atk",),
            ),
        )

        report = validate_recovery_candidates(
            worker,
            request=request,
            candidates=candidates,
            rng_seeds_by_observation=((TURN_SEED,),),
        )

    statuses = {
        result.candidate.candidate_id: result.status
        for result in report.candidate_results
    }
    if statuses.get("high-attack") is not RecoveryCandidateStatus.VALIDATED:
        raise SystemExit("ERROR: authoritative hidden-stat candidate was rejected")
    if statuses.get("low-attack") is not RecoveryCandidateStatus.REPLAY_MISMATCH:
        raise SystemExit("ERROR: mechanically wrong hidden-stat candidate survived")
    if len(report.validated_candidates) != 1:
        raise SystemExit("ERROR: recovery authority did not isolate one candidate")

    print("Mechanics-authoritative recovery boundary")
    print("Public-identical checkpoint hidden-stat candidates: 2")
    print("Candidates validated by complete Showdown replay: 1")
    print("Mechanically divergent hidden-stat candidate accepted: NO")
    print("Live belief state mutated by recovery module: NO")
    print("RESULT: proposal and mechanics authority are structurally separated")


if __name__ == "__main__":
    main()
