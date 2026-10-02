"""Pinned-runtime regression for pre-opening static recovery authority."""

from __future__ import annotations

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import (
    BeliefParticle,
    identity_member_lineage,
)
from champions_practice.recovery import (
    BoundedOpponentStatProposalGenerator,
    RecoveryCandidateStatus,
    RecoveryObservation,
    RecoveryOpeningAuthority,
    RecoveryRequest,
    validate_stat_recovery_proposals,
)
from champions_practice.search_worker import HypotheticalSearchWorker

PREVIEW = "team 1234"
BATTLE_SEED = "1,2,3,4"
TURN_SEED = "17,2,3,4"
QUIET = "move sleeptalk, move sleeptalk"

HUMAN_TEAM = """Rillaboom
Ability: Overgrow
Level: 50
Serious Nature
- Sleep Talk

Shuckle
Ability: Sturdy
Level: 50
Serious Nature
- Sleep Talk

Armarouge
Ability: Flash Fire
Level: 50
Serious Nature
- Sleep Talk

Metagross
Ability: Clear Body
Level: 50
Serious Nature
- Sleep Talk
"""

HUMAN_SPD_TEAM = """Rillaboom
Ability: Overgrow
Level: 50
EVs: 32 SpD
Serious Nature
- Sleep Talk

Shuckle
Ability: Sturdy
Level: 50
Serious Nature
- Sleep Talk

Armarouge
Ability: Flash Fire
Level: 50
Serious Nature
- Sleep Talk

Metagross
Ability: Clear Body
Level: 50
Serious Nature
- Sleep Talk
"""

AI_TEAM = """Porygon-Z
Ability: Download
Level: 50
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


def _previews() -> dict[str, list[str]]:
    return {
        "p1": ["Rillaboom", "Shuckle", "Armarouge", "Metagross"],
        "p2": ["Porygon-Z", "Shuckle", "Rillaboom", "Armarouge"],
    }


def _boosts(state: dict) -> tuple[int, int]:
    boosts = state["sides"][1]["pokemon"][0].get("boosts", {})
    return int(boosts.get("atk", 0)), int(boosts.get("spa", 0))


def _single_stat_proposal(
    proposals,
    *,
    stat: str,
):
    for proposal in proposals:
        if proposal.species != "Rillaboom":
            continue
        points = proposal.stat_point_dict
        if points["hp"] != 0 or points[stat] != 32:
            continue
        if any(
            points[other] != 0
            for other in ("atk", "def", "spa", "spd", "spe")
            if other != stat
        ):
            continue
        return proposal
    raise SystemExit(f"ERROR: generator omitted Rillaboom 32-{stat} proposal")


def main() -> None:
    previews = _previews()
    with HypotheticalSearchWorker() as worker:
        opening = worker.create_state_with_opening_authority(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=HUMAN_TEAM,
            p2_team=AI_TEAM,
            p1_preview=PREVIEW,
            p2_preview=PREVIEW,
            seed=BATTLE_SEED,
        )
        root_state = opening["state"]
        true_spd_state = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=HUMAN_SPD_TEAM,
            p2_team=AI_TEAM,
            p1_preview=PREVIEW,
            p2_preview=PREVIEW,
            seed=BATTLE_SEED,
        )

        if _boosts(root_state) != (0, 1):
            raise SystemExit(
                f"ERROR: base fixture did not produce Download SpA +1: {_boosts(root_state)}"
            )
        if _boosts(true_spd_state) != (1, 0):
            raise SystemExit(
                "ERROR: 32-SpD fixture did not change Download to Attack +1: "
                f"{_boosts(true_spd_state)}"
            )

        root_view = worker.state_view(
            state=root_state,
            side="p2",
            previews=previews,
        )
        suffix = worker.branch_many(
            state=root_state,
            branches=[
                {
                    "p1_choice": QUIET,
                    "p2_choice": QUIET,
                    "include_state": True,
                    "view_side": "p2",
                    "previews": previews,
                    "rng_seed": TURN_SEED,
                }
            ],
        )[0]
        suffix_view = suffix.get("view")
        if not isinstance(suffix_view, dict):
            raise SystemExit("ERROR: opening-authority fixture omitted suffix view")

        root_particle = BeliefParticle(
            root_state,
            1.0,
            world_id="download-root",
            history_id="post-preview",
            p1_member_lineage=identity_member_lineage(root_state, "p1"),
            p2_member_lineage=identity_member_lineage(root_state, "p2"),
        )
        request = RecoveryRequest(
            authority_root_particles=(root_particle,),
            opening_authorities=(
                RecoveryOpeningAuthority(
                    world_id="download-root",
                    history_id="post-preview",
                    battle_format=CHAMPIONS_FORMAT,
                    p1_team=HUMAN_TEAM,
                    p2_team=AI_TEAM,
                    p1_name="Search P1",
                    p2_name="Search P2",
                    seed=BATTLE_SEED,
                    p1_preview_choice=PREVIEW,
                    p2_preview_choice=PREVIEW,
                    p1_root_to_input=opening["preview_lineage"]["p1"],
                    p2_root_to_input=opening["preview_lineage"]["p2"],
                ),
            ),
            authority_root_public_view=root_view,
            authority_observations=(),
            authority_history_complete=True,
            checkpoint_particles=(root_particle,),
            checkpoint_public_view=root_view,
            observations=(
                RecoveryObservation(
                    ai_choice=QUIET,
                    previous_public_view=root_view,
                    public_view=suffix_view,
                ),
            ),
            ai_side="p2",
            previews=previews,
        )

        proposals = BoundedOpponentStatProposalGenerator(
            max_proposals=128
        ).generate(request)
        attack_proposal = _single_stat_proposal(proposals, stat="atk")
        spd_proposal = _single_stat_proposal(proposals, stat="spd")

        report = validate_stat_recovery_proposals(
            worker,
            request=request,
            proposals=(attack_proposal, spd_proposal),
            authority_rng_seeds_by_observation=(),
            rng_seeds_by_observation=((TURN_SEED,),),
        )

    results = {
        result.candidate.proposal_id: result
        for result in report.candidate_results
    }
    attack = results[attack_proposal.proposal_id]
    spd = results[spd_proposal.proposal_id]

    if attack.status is not RecoveryCandidateStatus.VALIDATED:
        raise SystemExit(
            "ERROR: opening-independent Attack proposal failed validation: "
            f"{attack.status.value}"
        )
    if spd.status is RecoveryCandidateStatus.VALIDATED:
        raise SystemExit(
            "ERROR: recovery preserved impossible old Download boost for 32-SpD proposal"
        )
    if spd.generated_branches != 0 or spd.final_particles:
        raise SystemExit(
            "ERROR: opening-incompatible proposal reached retained-history replay"
        )

    print("Pre-opening static recovery authority")
    print("Base Download boost: SpA +1")
    print("True 32-SpD opening boost: Attack +1")
    print("32-Atk control validates: YES")
    print(f"32-SpD impossible root accepted: NO ({spd.status.value})")
    print("Opening-incompatible proposal reaches history replay: NO")
    print("RESULT: static recovery reruns general opening mechanics before root authority")


if __name__ == "__main__":
    main()
