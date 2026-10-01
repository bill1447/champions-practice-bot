"""Pinned-runtime smoke for bounded opponent stat-point recovery proposals."""

from __future__ import annotations

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import (
    BeliefParticle,
    public_observation_signature,
)
from champions_practice.recovery import (
    BoundedOpponentStatProposalGenerator,
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


def _state(worker: HypotheticalSearchWorker, opponent_team: str) -> dict:
    return worker.create_state(
        battle_format=CHAMPIONS_FORMAT,
        p1_team=opponent_team,
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


def _snorlax_points(state: dict) -> dict[str, int]:
    pokemon = state["sides"][0]["pokemon"][0]
    return {
        stat: int(pokemon["set"]["evs"].get(stat, 0))
        for stat in ("hp", "atk", "def", "spa", "spd", "spe")
    }


def main() -> None:
    previews = _previews()
    with HypotheticalSearchWorker() as worker:
        high_state = _state(worker, HIGH_ATTACK_TEAM)
        low_state = _state(worker, LOW_ATTACK_TEAM)
        direct_rejections = worker.materialize_recovery_stat_proposals(
            state=low_state,
            side="p1",
            proposals=[
                {
                    "proposal_id": "hp-change",
                    "pokemon_index": 0,
                    "stat_points": {
                        "hp": 3,
                        "atk": 0,
                        "def": 0,
                        "spa": 31,
                        "spd": 0,
                        "spe": 32,
                    },
                },
                {
                    "proposal_id": "over-cap",
                    "pokemon_index": 0,
                    "stat_points": {
                        "hp": 2,
                        "atk": 32,
                        "def": 32,
                        "spa": 32,
                        "spd": 0,
                        "spe": 0,
                    },
                },
            ],
        )
        rejection_reasons = {
            result["proposal_id"]: result.get("rejected")
            for result in direct_rejections
        }
        if rejection_reasons.get("hp-change") != "hp-broadening-disabled":
            raise SystemExit("ERROR: materializer accepted HP-point broadening")
        if rejection_reasons.get("over-cap") != "invalid-stat-points":
            raise SystemExit("ERROR: materializer accepted an illegal stat-point total")

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
                "ERROR: hidden stat-point allocation changed public checkpoint"
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
            raise SystemExit("ERROR: authoritative stat fixture omitted public view")

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
            raise SystemExit("ERROR: low-Attack fixture omitted public view")
        if public_observation_signature(low_view) == public_observation_signature(
            actual_view
        ):
            raise SystemExit(
                "ERROR: stat-point fixture did not produce public damage divergence"
            )

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

        proposals = BoundedOpponentStatProposalGenerator(
            max_proposals=64
        ).generate(request)
        if not proposals:
            raise SystemExit("ERROR: bounded stat generator produced no proposals")
        snorlax_proposals = [
            proposal for proposal in proposals if proposal.species == "Snorlax"
        ]
        if not snorlax_proposals:
            raise SystemExit("ERROR: stat generator produced no Snorlax proposals")
        if any(
            proposal.stat_point_dict["hp"] != 2
            for proposal in snorlax_proposals
        ):
            raise SystemExit("ERROR: stat generator changed Snorlax HP points")
        if not any(
            proposal.stat_point_dict
            == {
                "hp": 2,
                "atk": 32,
                "def": 0,
                "spa": 0,
                "spd": 0,
                "spe": 32,
            }
            for proposal in snorlax_proposals
        ):
            raise SystemExit(
                "ERROR: generator missed legal SpA-to-Attack stat transfer"
            )

        report = validate_stat_recovery_proposals(
            worker,
            request=request,
            proposals=proposals,
            authority_rng_seeds_by_observation=(),
            rng_seeds_by_observation=((TURN_SEED,),),
        )
        if not report.candidate_results:
            reasons = sorted(
                {failure.reason for failure in report.materialization_failures}
            )
            raise SystemExit(
                "ERROR: Showdown materialized no stat proposals: "
                f"{reasons!r}"
            )

    validated = report.validated_candidates
    if not validated:
        raise SystemExit(
            "ERROR: mechanics replay failed to recover any stat-point hypothesis"
        )
    if any(
        _snorlax_points(result.candidate.particle.state)["atk"] != 32
        for result in validated
    ):
        raise SystemExit(
            "ERROR: replay accepted a stat hypothesis with the wrong Attack investment"
        )
    if any(
        _snorlax_points(result.candidate.particle.state)["hp"] != 2
        for result in validated
    ):
        raise SystemExit("ERROR: validated recovery candidate changed HP points")

    print("Bounded opponent stat-point recovery proposals")
    print(f"Generated proposals: {len(proposals)}")
    print(f"Showdown-materialized candidates: {len(report.candidate_results)}")
    print(
        "Materialization rejections: "
        f"{len(report.materialization_failures)}"
    )
    print(f"Replay-validated candidates: {len(validated)}")
    print("Direct HP-point materialization accepted: NO")
    print("Illegal >66-point materialization accepted: NO")
    print("HP stat-point mutation attempted by generator: NO")
    print("Wrong low-Attack parent explains observed damage: NO")
    print("Validated candidates require 32 Attack points: YES")
    print("RESULT: bounded hidden stat-point broadening is mechanics-authoritative")


if __name__ == "__main__":
    main()
