"""Pinned-runtime regression for static recovery prefix authority."""

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
TURN_1_SEED = "11,2,3,4"
TURN_2_SEED = "22,2,3,4"
TURN_3_SEED = "33,2,3,4"

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

Snorlax
Ability: Thick Fat
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
EVs: 16 Spe
Serious Nature
- Sleep Talk

Armarouge
Ability: Flash Fire
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
"""

HUMAN_QUIET = "move sleeptalk, move sleeptalk"
AI_QUIET = "move sleeptalk, move sleeptalk"
AI_SWITCH = "switch 3, move sleeptalk"


def _previews() -> dict[str, list[str]]:
    return {
        "p1": ["Rillaboom", "Shuckle", "Snorlax", "Armarouge"],
        "p2": ["Indeedee-F", "Armarouge", "Shuckle", "Rillaboom"],
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
        raise SystemExit("ERROR: history authority fixture omitted state/view/lineage")
    lineage: dict[str, tuple[int, ...]] = {}
    for side in ("p1", "p2"):
        values = raw_lineage.get(side)
        if not isinstance(values, list) or not all(
            isinstance(value, int) for value in values
        ):
            raise SystemExit("ERROR: history authority fixture returned invalid lineage")
        lineage[side] = tuple(values)
    return next_state, view, lineage


def _compose_lineage(
    parent: dict[str, tuple[int, ...]],
    step: dict[str, tuple[int, ...]],
) -> dict[str, tuple[int, ...]]:
    return {
        side: tuple(parent[side][index] for index in step[side])
        for side in ("p1", "p2")
    }


def _order(view: dict) -> tuple[tuple[str, int], ...]:
    delta = view.get("public_execution_delta")
    actions = delta.get("actions") if isinstance(delta, dict) else None
    if not isinstance(actions, list):
        return ()
    return tuple(
        (str(action.get("side")), int(action.get("slot", 0)))
        for action in actions
        if isinstance(action, dict)
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

        root_lineage = {
            "p1": identity_member_lineage(root_state, "p1"),
            "p2": identity_member_lineage(root_state, "p2"),
        }
        state_1, view_1, step_1_lineage = _branch(
            worker,
            state=root_state,
            p1_choice=HUMAN_QUIET,
            p2_choice=AI_QUIET,
            seed=TURN_1_SEED,
            previews=previews,
        )
        lineage_1 = _compose_lineage(root_lineage, step_1_lineage)
        state_2, view_2, step_2_lineage = _branch(
            worker,
            state=state_1,
            p1_choice=HUMAN_QUIET,
            p2_choice=AI_SWITCH,
            seed=TURN_2_SEED,
            previews=previews,
        )
        lineage_2 = _compose_lineage(lineage_1, step_2_lineage)
        _state_3, view_3, _step_3_lineage = _branch(
            worker,
            state=state_2,
            p1_choice=HUMAN_QUIET,
            p2_choice=AI_QUIET,
            seed=TURN_3_SEED,
            previews=previews,
        )

        actual_order = _order(view_1)
        if len(actual_order) < 2 or actual_order[:2] != (
            ("player", 1),
            ("opponent", 1),
        ):
            raise SystemExit(
                "ERROR: fixture did not produce Indeedee-before-Rillaboom order"
            )

        root_particle = BeliefParticle(
            root_state,
            1.0,
            world_id="slow-rillaboom",
            history_id="post-preview",
            p1_member_lineage=root_lineage["p1"],
            p2_member_lineage=root_lineage["p2"],
        )
        checkpoint_particle = BeliefParticle(
            state_2,
            1.0,
            world_id="slow-rillaboom",
            history_id="through-turn-2",
            p1_member_lineage=lineage_2["p1"],
            p2_member_lineage=lineage_2["p2"],
        )
        request = RecoveryRequest(
            authority_root_particles=(root_particle,),
            opening_authorities=(
                RecoveryOpeningAuthority(
                    world_id="slow-rillaboom",
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
                    previous_public_view=root_view,
                    public_view=view_1,
                ),
                RecoveryObservation(
                    ai_choice=AI_SWITCH,
                    previous_public_view=view_1,
                    public_view=view_2,
                ),
            ),
            authority_history_complete=True,
        checkpoint_particles=(checkpoint_particle,),
            checkpoint_public_view=view_2,
            observations=(
                RecoveryObservation(
                    ai_choice=AI_QUIET,
                    previous_public_view=view_2,
                    public_view=view_3,
                ),
            ),
            ai_side="p2",
            previews=previews,
        )

        proposals = BoundedOpponentStatProposalGenerator(
            max_proposals=64
        ).generate(request)
        speed_proposals = [
            proposal
            for proposal in proposals
            if proposal.species == "Rillaboom"
            and proposal.stat_point_dict["spe"] == 32
            and all(
                proposal.stat_point_dict[stat] == 0
                for stat in ("hp", "atk", "def", "spa", "spd")
            )
        ]
        if len(speed_proposals) != 1:
            raise SystemExit(
                "ERROR: generator did not produce one 32-Speed Rillaboom proposal"
            )

        report = validate_stat_recovery_proposals(
            worker,
            request=request,
            proposals=(speed_proposals[0],),
            authority_rng_seeds_by_observation=(
                (TURN_1_SEED,),
                (TURN_2_SEED,),
            ),
            rng_seeds_by_observation=((TURN_3_SEED,),),
        )

        # Independently materialize the same typed tuple at the real root only for
        # regression diagnostics. This result is not fed into recovery authority.
        materialized = worker.materialize_recovery_stat_proposals(
            state=root_state,
            side="p1",
            proposals=[
                {
                    "proposal_id": "fast-rillaboom-diagnostic",
                    "pokemon_index": 0,
                    "stat_points": speed_proposals[0].stat_point_dict,
                }
            ],
        )[0]
        fast_root = materialized.get("state")
        if not isinstance(fast_root, dict):
            raise SystemExit("ERROR: diagnostic fast root was not materialized")
        _fast_state_1, fast_view_1, _fast_lineage = _branch(
            worker,
            state=fast_root,
            p1_choice=HUMAN_QUIET,
            p2_choice=AI_QUIET,
            seed=TURN_1_SEED,
            previews=previews,
        )
        fast_order = _order(fast_view_1)

    if len(report.candidate_results) != 1:
        raise SystemExit("ERROR: speed proposal did not produce one root candidate")
    result = report.candidate_results[0]
    if result.status is not RecoveryCandidateStatus.SAMPLING_EXHAUSTED:
        raise SystemExit(
            "ERROR: contradicted Speed proposal was not left unresolved: "
            f"{result.status.value}"
        )
    if result.authority_observations_replayed != 0:
        raise SystemExit(
            "ERROR: contradicted Speed proposal replayed past turn-one mismatch"
        )
    if result.final_particles:
        raise SystemExit("ERROR: unresolved contradicted proposal exposed particles")
    if len(fast_order) < 2 or fast_order[:2] != (
        ("opponent", 1),
        ("player", 1),
    ):
        raise SystemExit(
            "ERROR: 32-Speed proposal did not reverse turn-one execution order"
        )

    print("Static recovery prefix authority")
    print(f"Observed turn-one order: {actual_order[:2]}")
    print(f"Proposed fast-world order: {fast_order[:2]}")
    print("Midgame copied-history shortcut accepted: NO")
    print("Contradicted 32-Speed Rillaboom validated: NO")
    print("Finite replay miss reported mechanically impossible: NO")
    print("Prefix observations replayed before sampling exhaustion: 0")
    print("RESULT: contradicted history stays non-validating without false impossibility")


if __name__ == "__main__":
    main()
