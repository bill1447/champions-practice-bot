"""Real-session smoke for the sealed public-belief practice battle facade."""

from champions_practice.belief_controller import SealedBattleFacade
from champions_practice.belief_smoke import _public_priors
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import public_observation_signature
from champions_practice.teams import SMOKE_TEAM

LIVE_SEED = "sodium,12345678000000020000000300000004"
HUMAN_PREVIEW = "team 2615"
AI_PREVIEW = "team 4512"
HUMAN_TURN_ONE = "move protect, move protect"
HUMAN_TURN_TWO = "switch 3, switch 4"


def main() -> None:
    with SealedBattleFacade(
        battle_format=CHAMPIONS_FORMAT,
        ai_team=SMOKE_TEAM,
        ai_preview_choice=AI_PREVIEW,
        opponent_priors=_public_priors(),
        world_limit=6,
        particles_per_world=1,
        max_particles=6,
        candidate_limit=2,
        response_limit=2,
        conditioning_budget_seconds=60.0,
        particle_seed=5301,
    ) as battle:
        battle.start(
            opponent_team=SMOKE_TEAM,
            p1_name="Human",
            p2_name="Belief AI",
            session_seed=LIVE_SEED,
        )
        battle.commit_preview(human_choice=HUMAN_PREVIEW)

        turn_one_before = public_observation_signature(
            battle.public_state()
        )
        ready = battle.lock_ai_action()
        if hasattr(ready, "choice") or "move " in repr(ready):
            raise SystemExit("ERROR: sealed AI payload leaked before human commit")
        if HUMAN_TURN_ONE not in battle.legal_human_choices():
            raise SystemExit("ERROR: controlled human turn-one action is not legal")

        try:
            battle.commit_human_action(
                token="wrong-token",
                human_choice=HUMAN_TURN_ONE,
            )
        except ValueError:
            pass
        else:
            raise SystemExit("ERROR: invalid lock token was accepted")
        if public_observation_signature(battle.public_state()) != turn_one_before:
            raise SystemExit("ERROR: bad token advanced the live battle")

        try:
            battle.commit_human_action(
                token=ready.token,
                human_choice="move definitely-not-legal",
            )
        except ValueError:
            pass
        else:
            raise SystemExit("ERROR: illegal human action was accepted")
        if public_observation_signature(battle.public_state()) != turn_one_before:
            raise SystemExit("ERROR: illegal human action advanced the live battle")

        update = battle.commit_human_action(
            token=ready.token,
            human_choice=HUMAN_TURN_ONE,
        )
        decision = update.decision
        if decision.mode != "belief-search":
            raise SystemExit(
                "ERROR: first live decision did not come from belief search: "
                f"{decision.fallback_reason}"
            )
        if update.degraded:
            raise SystemExit(
                "ERROR: live public observation degraded the persistent posterior"
            )
        if update.matched_branches <= 0:
            raise SystemExit("ERROR: no hypothetical branch matched the live observation")
        if update.public_view.get("player", {}).get("name") != "Human":
            raise SystemExit("ERROR: facade returned the AI-side private player view")

        if HUMAN_TURN_TWO not in battle.legal_human_choices():
            raise SystemExit("ERROR: controlled human turn-two switch is not legal")
        second_ready = battle.lock_ai_action()
        second_update = battle.commit_human_action(
            token=second_ready.token,
            human_choice=HUMAN_TURN_TWO,
        )
        second_decision = second_update.decision
        if second_decision.mode != "belief-search":
            raise SystemExit(
                "ERROR: second decision did not use persistent belief search: "
                f"{second_decision.fallback_reason}"
            )
        if second_update.degraded:
            raise SystemExit(
                "ERROR: second live observation degraded the persistent posterior"
            )
        if second_update.matched_branches <= 0:
            raise SystemExit("ERROR: turn-two observation matched no particle branch")

        third_ready = battle.lock_ai_action()
        if not third_ready.token:
            raise SystemExit("ERROR: third sealed decision did not produce a ready token")

        print("Persistent sealed public-belief battle facade")
        print(f"Turn-one belief-search choice: {decision.choice}")
        print(f"Turn-one search candidates: {decision.candidate_count}")
        print(f"Turn-one search branches: {decision.branch_count}")
        print(f"Turn-one search seconds: {decision.elapsed_seconds:.3f}")
        print(f"Turn-one strategic plan: {decision.strategic_plan or 'none'}")
        print(f"Turn-one conditioning matches: {update.matched_branches}")
        print(f"Turn-one posterior particles: {update.particles_after}")
        print(f"Turn-two belief-search choice: {second_decision.choice}")
        print(f"Turn-two search seconds: {second_decision.elapsed_seconds:.3f}")
        print(f"Turn-two conditioning matches: {second_update.matched_branches}")
        print(f"Turn-two posterior particles: {second_update.particles_after}")
        print("Decision engine live-session capability: NO")
        print("Invalid token advanced live session: NO")
        print("Illegal human action advanced live session: NO")
        print("Pre-commit AI decision payload exposed: NO")
        print("Human client received AI-side private view: NO")
        print("RESULT: sealed facade drives persistent decisions across live turns")


if __name__ == "__main__":
    main()
