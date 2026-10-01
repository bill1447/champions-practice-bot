"""Pinned-runtime regression for stable recovery roster-member lineage."""

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
TURN_1_SEED = "41,2,3,4"
TURN_2_SEED = "42,2,3,4"

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

Metagross
Ability: Clear Body
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

HUMAN_SWITCH_OUT = "switch 3, move sleeptalk"
HUMAN_SWITCH_BACK = "switch 3, move sleeptalk"
AI_QUIET = "move sleeptalk, move sleeptalk"


def _previews() -> dict[str, list[str]]:
    return {
        "p1": ["Rillaboom", "Shuckle", "Metagross", "Armarouge"],
        "p2": ["Indeedee-F", "Shuckle", "Rillaboom", "Armarouge"],
    }


def _branch(
    worker: HypotheticalSearchWorker,
    *,
    state: dict,
    p1_choice: str,
    p2_choice: str,
    seed: str,
    previews: dict[str, list[str]],
) -> tuple[dict, dict, dict[str, tuple[int, ...]]]:
    result = worker.branch_many(
        state=state,
        branches=[
            {
                "p1_choice": p1_choice,
                "p2_choice": p2_choice,
                "include_state": True,
                "view_side": "p2",
                "previews": previews,
                "rng_seed": seed,
            }
        ],
    )[0]
    next_state = result.get("state")
    view = result.get("view")
    raw_lineage = result.get("member_lineage")
    if (
        not isinstance(next_state, dict)
        or not isinstance(view, dict)
        or not isinstance(raw_lineage, dict)
    ):
        raise SystemExit("ERROR: member-lineage fixture omitted state/view/lineage")
    lineage: dict[str, tuple[int, ...]] = {}
    for side in ("p1", "p2"):
        values = raw_lineage.get(side)
        if not isinstance(values, list) or not all(
            isinstance(value, int) for value in values
        ):
            raise SystemExit("ERROR: branch returned malformed member lineage")
        lineage[side] = tuple(values)
    return next_state, view, lineage


def _compose(
    parent: tuple[int, ...],
    child_to_parent: tuple[int, ...],
) -> tuple[int, ...]:
    return tuple(parent[index] for index in child_to_parent)


def _species_order(state: dict, side_index: int) -> tuple[str, ...]:
    return tuple(
        str(mon["set"]["species"])
        for mon in state["sides"][side_index]["pokemon"]
    )


def _pick_attack_proposal(
    proposals,
    *,
    species: str,
    checkpoint_index: int,
    root_index: int,
):
    for proposal in proposals:
        if (
            proposal.species == species
            and proposal.pokemon_index == checkpoint_index
            and proposal.root_pokemon_index == root_index
            and proposal.stat_point_dict
            == {
                "hp": 0,
                "atk": 32,
                "def": 0,
                "spa": 0,
                "spd": 0,
                "spe": 0,
            }
        ):
            return proposal
    raise SystemExit(
        "ERROR: generator omitted expected stable-member proposal for "
        f"{species} checkpoint={checkpoint_index} root={root_index}"
    )


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
        root_view = worker.state_view(
            state=root_state,
            side="p2",
            previews=previews,
        )
        root_p1_lineage = identity_member_lineage(root_state, "p1")
        root_p2_lineage = identity_member_lineage(root_state, "p2")

        state_1, view_1, step_1 = _branch(
            worker,
            state=root_state,
            p1_choice=HUMAN_SWITCH_OUT,
            p2_choice=AI_QUIET,
            seed=TURN_1_SEED,
            previews=previews,
        )
        checkpoint_p1_lineage = _compose(root_p1_lineage, step_1["p1"])
        checkpoint_p2_lineage = _compose(root_p2_lineage, step_1["p2"])

        if _species_order(state_1, 0) != (
            "Metagross",
            "Shuckle",
            "Rillaboom",
            "Armarouge",
        ):
            raise SystemExit(
                "ERROR: fixture did not reproduce Showdown switch reordering: "
                f"{_species_order(state_1, 0)!r}"
            )
        if checkpoint_p1_lineage != (2, 1, 0, 3):
            raise SystemExit(
                "ERROR: switch lineage did not map checkpoint positions to roots: "
                f"{checkpoint_p1_lineage!r}"
            )

        state_2, view_2, step_2 = _branch(
            worker,
            state=state_1,
            p1_choice=HUMAN_SWITCH_BACK,
            p2_choice=AI_QUIET,
            seed=TURN_2_SEED,
            previews=previews,
        )
        final_p1_lineage = _compose(checkpoint_p1_lineage, step_2["p1"])
        if final_p1_lineage != root_p1_lineage:
            raise SystemExit(
                "ERROR: switching the original member back did not restore lineage: "
                f"{final_p1_lineage!r}"
            )
        if _species_order(state_2, 0) != (
            "Rillaboom",
            "Shuckle",
            "Metagross",
            "Armarouge",
        ):
            raise SystemExit("ERROR: switch-back fixture did not restore party ordering")

        root_particle = BeliefParticle(
            root_state,
            1.0,
            world_id="switch-lineage",
            history_id="post-preview",
            p1_member_lineage=root_p1_lineage,
            p2_member_lineage=root_p2_lineage,
        )
        checkpoint_particle = BeliefParticle(
            state_1,
            1.0,
            world_id="switch-lineage",
            history_id="after-switch-out",
            p1_member_lineage=checkpoint_p1_lineage,
            p2_member_lineage=checkpoint_p2_lineage,
        )
        request = RecoveryRequest(
            authority_root_particles=(root_particle,),
            opening_authorities=(
                RecoveryOpeningAuthority(
                    world_id="switch-lineage",
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
            authority_observations=(
                RecoveryObservation(
                    ai_choice=AI_QUIET,
                    resolved_opponent_choice=HUMAN_SWITCH_OUT,
                    previous_public_view=root_view,
                    public_view=view_1,
                ),
            ),
            authority_history_complete=True,
            checkpoint_particles=(checkpoint_particle,),
            checkpoint_public_view=view_1,
            observations=(
                RecoveryObservation(
                    ai_choice=AI_QUIET,
                    resolved_opponent_choice=HUMAN_SWITCH_BACK,
                    previous_public_view=view_1,
                    public_view=view_2,
                ),
            ),
            ai_side="p2",
            previews=previews,
        )

        proposals = BoundedOpponentStatProposalGenerator(
            max_proposals=256
        ).generate(request)
        metagross = _pick_attack_proposal(
            proposals,
            species="Metagross",
            checkpoint_index=0,
            root_index=2,
        )
        rillaboom = _pick_attack_proposal(
            proposals,
            species="Rillaboom",
            checkpoint_index=2,
            root_index=0,
        )

        report = validate_stat_recovery_proposals(
            worker,
            request=request,
            proposals=(metagross, rillaboom),
            authority_rng_seeds_by_observation=((TURN_1_SEED,),),
            rng_seeds_by_observation=((TURN_2_SEED,),),
        )

    if len(report.candidate_results) != 2:
        raise SystemExit("ERROR: stable-member proposals did not both materialize")
    by_species = {
        result.candidate.proposal_id.split("-r", 1)[0]: result
        for result in report.candidate_results
    }
    if any(
        result.status is not RecoveryCandidateStatus.VALIDATED
        for result in report.candidate_results
    ):
        raise SystemExit(
            "ERROR: stable roster-member recovery failed validation: "
            + ", ".join(
                f"{result.candidate.proposal_id}={result.status.value}"
                for result in report.candidate_results
            )
        )
    if any(not result.final_particles for result in report.candidate_results):
        raise SystemExit("ERROR: validated member-lineage candidate exposed no particles")

    roots = {
        result.candidate.root_pokemon_index
        for result in report.candidate_results
    }
    if roots != {0, 2}:
        raise SystemExit(f"ERROR: wrong root members were materialized: {roots!r}")

    print("Stable recovery roster-member lineage")
    print(f"Root p1 order: {_species_order(root_state, 0)}")
    print(f"Checkpoint p1 order: {_species_order(state_1, 0)}")
    print(f"Checkpoint -> root lineage: {checkpoint_p1_lineage}")
    print("Metagross checkpoint 0 -> root 2 validated: YES")
    print("Rillaboom checkpoint 2 -> root 0 validated: YES")
    print("Switch out and back preserved roster identity: YES")
    print("Species used as identity key: NO")
    print("RESULT: recovery follows stable members, not mutable party positions")


if __name__ == "__main__":
    main()
