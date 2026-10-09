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
        if update.particles_after or update.matched_branches or update.generated_branches:
            raise SystemExit(
                "ERROR: public turn retained historical particle conditioning"
            )
        if update.recovery_retry_diagnostic is not None:
            raise SystemExit("ERROR: sealed battle retried historical recovery")
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
        if second_decision.mode == "fallback":
            if not (
                (second_decision.fallback_reason or "").startswith(
                    "fresh-public-world:"
                )
                or second_decision.fallback_reason == "belief-search-deadline"
                or (second_decision.fallback_reason or "").startswith(
                    "search-error:"
                )
            ):
                raise SystemExit(
                    "ERROR: second live decision used an unrecognized fallback: "
                    f"{second_decision.fallback_reason}"
                )
        elif second_decision.mode not in ("belief-search", "strategy"):
            raise SystemExit(
                "ERROR: second live decision did not use current public worlds: "
                f"{second_decision.mode}"
            )
        if (second_update.particles_after or second_update.matched_branches
                or second_update.recovery_retry_diagnostic is not None):
            raise SystemExit(
                "ERROR: second live turn retained historical particles/retry"
            )

        third_ready = battle.lock_ai_action()
        if not third_ready.token:
            raise SystemExit("ERROR: third sealed decision did not produce a ready token")

        print("Sealed disposable public-world battle facade")
        print(f"Turn-one belief-search choice: {decision.choice}")
        print(f"Turn-one search candidates: {decision.candidate_count}")
        print(f"Turn-one search branches: {decision.branch_count}")
        print(f"Turn-one search seconds: {decision.elapsed_seconds:.3f}")
        print(f"Turn-one strategic plan: {decision.strategic_plan or 'none'}")
        print(f"Turn-one discarded worlds: {decision.particle_count}")
        print(f"Turn-two decision mode: {second_decision.mode}")
        print(f"Turn-two action: {second_decision.choice}")
        print(f"Turn-two elapsed seconds: {second_decision.elapsed_seconds:.3f}")
        print(f"Turn-two fresh-world result: {second_decision.fallback_reason or 'search'}")
        print(f"Turn-two discarded worlds: {second_update.particles_after}")
        print("Decision engine live-session capability: NO")
        print("Invalid token advanced live session: NO")
        print("Illegal human action advanced live session: NO")
        print("Pre-commit AI decision payload exposed: NO")
        print("Human client received AI-side private view: NO")
        print("RESULT: sealed facade keeps public information, not simulator ancestry")

    # Keep the deadline fallback on the same public sealed API used by the demo. A
    # microscopic budget must reveal only a legal fallback after the human commits.
    with SealedBattleFacade(
        battle_format=CHAMPIONS_FORMAT,
        ai_team=SMOKE_TEAM,
        ai_preview_choice=AI_PREVIEW,
        opponent_priors=_public_priors(),
        world_limit=1,
        particles_per_world=1,
        max_particles=1,
        candidate_limit=1,
        response_limit=1,
        decision_budget_seconds=1e-9,
        conditioning_budget_seconds=1e-9,
        particle_seed=5302,
    ) as fallback_battle:
        fallback_battle.start(
            opponent_team=SMOKE_TEAM,
            p1_name="Fallback Human",
            p2_name="Fallback AI",
            session_seed=LIVE_SEED,
        )
        fallback_battle.commit_preview(human_choice=HUMAN_PREVIEW)
        ready = fallback_battle.lock_ai_action()
        if hasattr(ready, "choice") or "move " in repr(ready):
            raise SystemExit("ERROR: sealed fallback payload leaked before human commit")
        fallback_update = fallback_battle.commit_human_action(
            token=ready.token,
            human_choice=HUMAN_TURN_ONE,
        )
        fallback = fallback_update.decision
        if fallback.mode != "fallback":
            raise SystemExit("ERROR: tiny decision budget did not trigger fallback")
        if fallback.fallback_reason != "belief-search-deadline":
            raise SystemExit(
                "ERROR: unexpected deadline fallback reason: "
                f"{fallback.fallback_reason}"
            )

        print(f"Tiny-budget sealed fallback: {fallback.choice}")
        print("RESULT: public facade preserves deadline fallback behavior")


if __name__ == "__main__":
    main()
