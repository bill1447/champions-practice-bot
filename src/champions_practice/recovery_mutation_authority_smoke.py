"""Pinned-runtime regression for typed recovery mutation authority."""

from __future__ import annotations

import copy

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import (
    BeliefParticle,
    identity_member_lineage,
)
from champions_practice.recovery import (
    OpponentStatProposal,
    RecoveryCandidateStatus,
    RecoveryObservation,
    RecoveryOpeningAuthority,
    RecoveryRequest,
    validate_stat_recovery_proposals,
)
from champions_practice.search_worker import HypotheticalSearchWorker

PREVIEW = "team 1234"
BATTLE_SEED = "1,2,3,4"
TURN_SEED = "99,2,3,4"

HUMAN_TEAM = """Annihilape
Ability: Defiant
Level: 50
Serious Nature
- Sleep Talk
- Rage Fist

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
Serious Nature
- Sleep Talk

Armarouge
Ability: Flash Fire
Level: 50
Serious Nature
- Sleep Talk

Rillaboom
Ability: Overgrow
Level: 50
Serious Nature
- Sleep Talk

Shuckle
Ability: Sturdy
Level: 50
Serious Nature
- Sleep Talk
"""

HUMAN_CHOICE = "move sleeptalk, move sleeptalk"
AI_CHOICE = "move sleeptalk, move sleeptalk"


class _HostileMaterializer:
    def __init__(
        self,
        worker: HypotheticalSearchWorker,
        *,
        mutation: str | None,
    ) -> None:
        self.worker = worker
        self.mutation = mutation
        self.branch_calls = 0

    def materialize_recovery_stat_proposals(self, *, state, side, proposals):
        resolved = self.worker.materialize_recovery_stat_proposals(
            state=state,
            side=side,
            proposals=proposals,
        )
        if self.mutation is None:
            return resolved

        tampered = copy.deepcopy(resolved)
        for result in tampered:
            candidate = result.get("state")
            if not isinstance(candidate, dict):
                continue
            target = candidate["sides"][0]["pokemon"][0]
            if self.mutation == "timesAttacked":
                target["timesAttacked"] = 99
            elif self.mutation == "queue":
                candidate["queue"] = [{"choice": "forged"}]
            elif self.mutation == "pp":
                target["moveSlots"][0]["pp"] = 1
            elif self.mutation == "baseStoredStats":
                target["baseStoredStats"]["spa"] = 999
            elif self.mutation == "storedStats":
                target["storedStats"]["spa"] = 999
            elif self.mutation == "speed":
                target["speed"] = 999
            else:
                raise AssertionError(f"unknown hostile mutation: {self.mutation}")
        return tampered

    def validate_recovery_stat_candidate(
        self,
        *,
        state,
        side,
        pokemon_index,
        stat_points,
    ):
        return self.worker.validate_recovery_stat_candidate(
            state=state,
            side=side,
            pokemon_index=pokemon_index,
            stat_points=stat_points,
        )

    def materialize_recovery_opening_stat_proposals(
        self,
        *,
        battle_format,
        p1_team,
        p2_team,
        p1_name,
        p2_name,
        seed,
        side,
        p1_preview,
        p2_preview,
        proposals,
    ):
        resolved = self.worker.materialize_recovery_opening_stat_proposals(
            battle_format=battle_format,
            p1_team=p1_team,
            p2_team=p2_team,
            p1_name=p1_name,
            p2_name=p2_name,
            seed=seed,
            side=side,
            p1_preview=p1_preview,
            p2_preview=p2_preview,
            proposals=proposals,
        )
        if self.mutation is None:
            return resolved

        tampered = copy.deepcopy(resolved)
        for result in tampered:
            candidate = result.get("state")
            if not isinstance(candidate, dict):
                continue
            target = candidate["sides"][0]["pokemon"][0]
            if self.mutation == "timesAttacked":
                target["timesAttacked"] = 99
            elif self.mutation == "queue":
                candidate["queue"] = [{"choice": "forged"}]
            elif self.mutation == "pp":
                target["moveSlots"][0]["pp"] = 1
            elif self.mutation == "baseStoredStats":
                target["baseStoredStats"]["spa"] = 999
            elif self.mutation == "storedStats":
                target["storedStats"]["spa"] = 999
            elif self.mutation == "speed":
                target["speed"] = 999
            else:
                raise AssertionError(f"unknown hostile mutation: {self.mutation}")
        return tampered

    def validate_recovery_opening_authority(
        self,
        *,
        battle_format,
        p1_team,
        p2_team,
        p1_name,
        p2_name,
        seed,
        root_state,
        p1_preview,
        p2_preview,
        p1_root_to_input,
        p2_root_to_input,
    ):
        return self.worker.validate_recovery_opening_authority(
            battle_format=battle_format,
            p1_team=p1_team,
            p2_team=p2_team,
            p1_name=p1_name,
            p2_name=p2_name,
            seed=seed,
            root_state=root_state,
            p1_preview=p1_preview,
            p2_preview=p2_preview,
            p1_root_to_input=p1_root_to_input,
            p2_root_to_input=p2_root_to_input,
        )

    def validate_recovery_opening_stat_candidate(
        self,
        *,
        battle_format,
        p1_team,
        p2_team,
        p1_name,
        p2_name,
        seed,
        candidate_state,
        side,
        pokemon_index,
        stat_points,
        p1_preview,
        p2_preview,
    ):
        return self.worker.validate_recovery_opening_stat_candidate(
            battle_format=battle_format,
            p1_team=p1_team,
            p2_team=p2_team,
            p1_name=p1_name,
            p2_name=p2_name,
            seed=seed,
            candidate_state=candidate_state,
            side=side,
            pokemon_index=pokemon_index,
            stat_points=stat_points,
            p1_preview=p1_preview,
            p2_preview=p2_preview,
        )

    def state_view(self, *, state, side, previews=None):
        return self.worker.state_view(
            state=state,
            side=side,
            previews=previews,
        )

    def validate_choices(self, *, state, side, candidates):
        return self.worker.validate_choices(
            state=state,
            side=side,
            candidates=candidates,
        )

    def legal_choices(self, *, state, side):
        return self.worker.legal_choices(state=state, side=side)

    def branch_many(self, *, state, branches):
        self.branch_calls += 1
        return self.worker.branch_many(state=state, branches=branches)


def _previews() -> dict[str, list[str]]:
    return {
        "p1": ["Annihilape", "Shuckle", "Rillaboom", "Armarouge"],
        "p2": ["Indeedee-F", "Armarouge", "Rillaboom", "Shuckle"],
    }


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
        parent = opening["state"]
        if parent["sides"][0]["pokemon"][0].get("timesAttacked") != 0:
            raise SystemExit("ERROR: fixture Annihilape counter did not start at zero")

        checkpoint = worker.state_view(
            state=parent,
            side="p2",
            previews=previews,
        )
        observed = worker.branch_many(
            state=parent,
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
        observed_view = observed.get("view")
        if not isinstance(observed_view, dict):
            raise SystemExit("ERROR: quiet authority fixture omitted public view")

        request = RecoveryRequest(
            authority_root_particles=(
                BeliefParticle(
                    parent,
                    1.0,
                    world_id="counter-parent",
                    history_id="initial-checkpoint",
                    p1_member_lineage=identity_member_lineage(parent, "p1"),
                    p2_member_lineage=identity_member_lineage(parent, "p2"),
                ),
            ),
            opening_authorities=(
                RecoveryOpeningAuthority(
                    world_id="counter-parent",
                    history_id="initial-checkpoint",
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
            authority_root_public_view=checkpoint,
            authority_observations=(),
            authority_history_complete=True,
        checkpoint_particles=(
                BeliefParticle(
                    parent,
                    1.0,
                    world_id="counter-parent",
                    history_id="initial-checkpoint",
                    p1_member_lineage=identity_member_lineage(parent, "p1"),
                    p2_member_lineage=identity_member_lineage(parent, "p2"),
                ),
            ),
            checkpoint_public_view=checkpoint,
            observations=(
                RecoveryObservation(
                    ai_choice=AI_CHOICE,
                    resolved_opponent_choice=HUMAN_CHOICE,
                    previous_public_view=checkpoint,
                    public_view=observed_view,
                ),
            ),
            ai_side="p2",
            previews=previews,
        )
        proposal = OpponentStatProposal(
            proposal_id="spa16",
            parent_particle_index=0,
            pokemon_index=0,
            root_pokemon_index=0,
            species="Annihilape",
            stat_points=(
                ("hp", 0),
                ("atk", 0),
                ("def", 0),
                ("spa", 16),
                ("spd", 0),
                ("spe", 0),
            ),
            changed_hidden_dimensions=(
                "opponent.member0.annihilape.stat_points.spa",
            ),
        )

        approved = validate_stat_recovery_proposals(
            _HostileMaterializer(worker, mutation=None),
            request=request,
            proposals=(proposal,),
            authority_rng_seeds_by_observation=(),
            rng_seeds_by_observation=((TURN_SEED,),),
        )
        if len(approved.candidate_results) != 1:
            raise SystemExit("ERROR: approved stat proposal did not materialize")
        if (
            approved.candidate_results[0].status
            is not RecoveryCandidateStatus.VALIDATED
        ):
            raise SystemExit("ERROR: approved stat-only proposal failed validation")

        for mutation in (
            "timesAttacked",
            "queue",
            "pp",
            "baseStoredStats",
            "storedStats",
            "speed",
        ):
            hostile = _HostileMaterializer(worker, mutation=mutation)
            report = validate_stat_recovery_proposals(
                hostile,
                request=request,
                proposals=(proposal,),
                authority_rng_seeds_by_observation=(),
                rng_seeds_by_observation=((TURN_SEED,),),
            )
            if len(report.candidate_results) != 1:
                raise SystemExit(
                    f"ERROR: hostile {mutation} proposal did not materialize"
                )
            result = report.candidate_results[0]
            if (
                result.status
                is not RecoveryCandidateStatus.UNAUTHORIZED_STATE_DELTA
            ):
                raise SystemExit(
                    "ERROR: typed recovery accepted unauthorized checkpoint edit "
                    f"{mutation}: {result.status.value}"
                )
            if result.final_particles:
                raise SystemExit(
                    f"ERROR: hostile {mutation} edit exposed validated particles"
                )
            if hostile.branch_calls != 0:
                raise SystemExit(
                    f"ERROR: hostile {mutation} edit reached replay before rejection"
                )

    print("Typed stat recovery mutation authority")
    print("Approved stat-only materialization validates: YES")
    print("Forged timesAttacked accepted: NO")
    print("Forged queue accepted: NO")
    print("Forged PP accepted: NO")
    print("Forged baseStoredStats accepted: NO")
    print("Forged storedStats accepted: NO")
    print("Forged speed accepted: NO")
    print("Unauthorized edits reach mechanics replay: NO")
    print("Caller-supplied serialized candidate authority surface: NO")
    print("RESULT: stat recovery authority is confined to typed simulator deltas")


if __name__ == "__main__":
    main()
