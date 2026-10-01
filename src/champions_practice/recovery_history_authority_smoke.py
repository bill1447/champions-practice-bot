"""Pinned-runtime regression for static recovery prefix authority."""

from __future__ import annotations

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import BeliefParticle
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
) -> tuple[dict, dict]:
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
    if not isinstance(next_state, dict) or not isinstance(view, dict):
        raise SystemExit("ERROR: history authority fixture omitted state/view")
    return next_state, view


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

        state_1, view_1 = _branch(
            worker,
            state=root_state,
            p1_choice=HUMAN_QUIET,
            p2_choice=AI_QUIET,
            seed=TURN_1_SEED,
            previews=previews,
        )
        state_2, view_2 = _branch(
            worker,
            state=state_1,
            p1_choice=HUMAN_QUIET,
            p2_choice=AI_SWITCH,
            seed=TURN_2_SEED,
            previews=previews,
        )
        _state_3, view_3 = _branch(
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
        )
        checkpoint_particle = BeliefParticle(
            state_2,
            1.0,
            world_id="slow-rillaboom",
            history_id="through-turn-2",
        )
        request = RecoveryRequest(
            authority_root_particles=(root_particle,),
            opening_authorities=(
                RecoveryOpeningAuthority(
                    particle=BeliefParticle(
                        opening["preopening_state"],
                        1.0,
                        world_id="slow-rillaboom",
                        history_id="post-preview",
                    ),
                    p1_preview_choice=PREVIEW,
                    p2_preview_choice=PREVIEW,
                    p1_root_to_preopening=opening["preview_lineage"]["p1"],
                    p2_root_to_preopening=opening["preview_lineage"]["p2"],
                ),
            ),
            authority_root_public_view=root_view,
            authority_observations=(
                RecoveryObservation(
                    ai_choice=AI_QUIET,
                    resolved_opponent_choice=HUMAN_QUIET,
                    previous_public_view=root_view,
                    public_view=view_1,
                ),
                RecoveryObservation(
                    ai_choice=AI_SWITCH,
                    resolved_opponent_choice=HUMAN_QUIET,
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
                    resolved_opponent_choice=HUMAN_QUIET,
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
        _fast_state_1, fast_view_1 = _branch(
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
    if result.status is not RecoveryCandidateStatus.HISTORY_MISMATCH:
        raise SystemExit(
            "ERROR: historically impossible Speed proposal was not rejected: "
            f"{result.status.value}"
        )
    if result.authority_observations_replayed != 0:
        raise SystemExit(
            "ERROR: impossible Speed proposal replayed past contradicted turn one"
        )
    if result.final_particles:
        raise SystemExit("ERROR: historically impossible proposal exposed particles")
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
    print("Historically impossible 32-Speed Rillaboom validated: NO")
    print("Prefix observations replayed before rejection: 0")
    print("RESULT: static stat recovery cannot resurrect disproved history")


if __name__ == "__main__":
    main()
