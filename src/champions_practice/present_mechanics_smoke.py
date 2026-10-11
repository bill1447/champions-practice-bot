"""Native negative controls for production admission of latent mechanics.

Oracle snapshots are compared offline only. Production receives public views
and its independent ledger; no native counters or hidden sets enter inference.
"""

from copy import deepcopy

from champions_practice.belief_controller import BeliefDecisionEngine
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM
from champions_practice.present_mechanics import opening_terrain_plan, unsupported_present_mechanics


def main():
    with ShowdownSearchWorker() as worker:
        for name, preview, commands, reason in (
            ("terrain", "team 1235", "move followme, move rockslide",
             "unsupported-public-effect-duration"),
            ("terrain-reset", "team 1235", "switch 4, move rockslide",
             "unsupported-public-effect-duration"),
            ("protection", "team 4632", "move protect, move protect",
             "unsupported-public-protection-chain"),
        ):
            start = worker.start_session(
                battle_format=CHAMPIONS_FORMAT,
                p1_team=SMOKE_TEAM, p2_team=SMOKE_TEAM,
                p1_name="Human", p2_name="AI",
                seed="sodium,00000001000000020000000300000004",
            )
            sid = start["session_id"]
            try:
                worker.choose_session(sid, p1_choice=preview, p2_choice=preview)
                opening = worker.session_snapshot(sid)["state"]
                ledger = PublicConstraintLedger.from_public_view(
                    worker.session_view(sid, side="p2")["view"]
                )
                worker.choose_session(sid, p1_choice=commands, p2_choice=commands)
                view = worker.session_view(sid, side="p2")["view"]
                ledger = ledger.advance(view)
                oracle = worker.session_snapshot(sid)["state"]
                probe = worker.materialize_present_hypotheses(
                    state=opening, current_view=view, limit=4,
                )
                assert probe["outcomes"], "negative control must expose the old constructor gap"
                candidate = probe["outcomes"][0]["state"]
                if name.startswith("terrain"):
                    assert oracle["field"]["terrainState"]["duration"] == 4
                    assert candidate["field"]["terrainState"]["duration"] == 5
                    plan = opening_terrain_plan(view, ledger)
                    assert plan is not None
                    repaired = worker.materialize_present_hypotheses(
                        state=opening, current_view=view, limit=4, mechanics_plan=plan,
                    )
                    assert repaired["outcomes"], repaired.get("reason")
                    assert all(
                        entry["state"]["field"]["terrainState"]["duration"] == 4
                        for entry in repaired["outcomes"]
                    )
                    assert unsupported_present_mechanics(view, ledger) != reason
                    assert unsupported_present_mechanics(view) == reason
                    for age in (2, 4, 5):
                        aged_view = deepcopy(view)
                        aged_view["turn"] = age + 1
                        aged_plan = {**plan, "residual_turns": age}
                        aged = worker.materialize_present_hypotheses(
                            state=opening, current_view=aged_view, limit=4,
                            mechanics_plan=aged_plan,
                        )
                        if age == 5:
                            assert not aged["outcomes"]
                            assert aged["reason"] == "opening-terrain-expired"
                        else:
                            assert aged["outcomes"], aged.get("reason")
                            assert all(entry["state"]["field"]["terrainState"]["duration"]
                                       == 5 - age for entry in aged["outcomes"])
                    print("Pinned terrain recovery: public age restores exact native duration")
                    continue
                else:
                    protected = [
                        slot for slot, mon in enumerate(oracle["sides"][1]["pokemon"][:2])
                        if mon["volatiles"].get("stall", {}).get("counter") == 3
                    ]
                    assert protected, "native protection must succeed on at least one own slot"
                    assert all(
                        "stall" not in candidate["sides"][1]["pokemon"][slot]["volatiles"]
                        for slot in protected
                    )

                bot = BeliefDecisionEngine(
                    ".", battle_format=CHAMPIONS_FORMAT, ai_team=SMOKE_TEAM,
                    opponent_priors={},
                )
                bot.last_public_view = view
                bot.public_constraint_ledger = ledger
                bot._public_ai_preview_choice = preview

                def no_worker(*args, **kwargs):
                    raise AssertionError("unsupported current state reached production search")

                bot._run_until_deadline = no_worker
                legal = worker.session_legal_choices(sid, side="p2")
                decision = bot.choose_ai_action(legal_live=legal)
                assert decision.mode == "fallback" and decision.choice in legal
                assert decision.fallback_reason == "fresh-public-world:" + reason
                assert not bot.particles
                print(f"Pinned {name} negative control: production fallback before construction")
            finally:
                worker.close_session(sid)
    print("RESULT: unsupported native counters cannot enter production tactical search")


if __name__ == "__main__":
    main()
