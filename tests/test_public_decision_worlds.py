"""PR #197: decision worlds are disposable; public knowledge persists."""

from __future__ import annotations

from types import SimpleNamespace

from champions_practice.belief_controller import BeliefDecisionEngine


def engine():
    result = BeliefDecisionEngine(
        ".", battle_format="test", ai_team="own",
        opponent_priors={},
    )
    result._public_ai_preview_choice = "team 12"
    return result


def test_healthy_old_particles_never_block_new_current_worlds():
    bot = engine()
    bot.last_public_view = {"turn": 8}
    bot.particles = (SimpleNamespace(world_id="old"),)
    bot.degraded = False
    attempts = []

    def fresh(*, deadline, legal_live):
        attempts.append((bot.last_public_view["turn"], bot.particles))
        return False

    bot._try_present_public_rebase = fresh
    bot._try_first_turn_public_rebase = lambda **_kw: (_ for _ in ()).throw(
        AssertionError("historical witness must not enter live decision")
    )
    first = bot.choose_ai_action(legal_live=["move protect"])
    assert first.mode == "fallback"
    assert first.choice == "move protect"
    assert first.fallback_reason.startswith("fresh-public-world:")
    assert attempts == [(8, ())]
    assert bot.particles == ()
    assert bot.pending_observations == []

    bot.last_public_view = {"turn": 9}
    bot.degraded = False
    bot.particles = (SimpleNamespace(world_id="stale-again"),)
    second = bot.choose_ai_action(legal_live=["move protect"])
    assert second.mode == "fallback"
    assert attempts == [(8, ()), (9, ())]
    assert bot.particles == ()


def test_observation_discards_successful_world_without_conditioning():
    bot = engine()
    bot.particles = (SimpleNamespace(world_id="one-turn-only"),)
    bot.pending_observations = [("move a", {"turn": 1}, {"turn": 2})]
    bot.recovery_authority_history_complete = True
    public_ledger = object()
    bot.public_constraint_ledger = public_ledger
    bot._record_public_constraints = lambda view, *, initialize: None
    bot._run_until_deadline = lambda *_a, **_kw: (_ for _ in ()).throw(
        AssertionError("no RNG conditioning or historical catch-up")
    )

    view = {"turn": 8, "phase": "move"}
    decision = SimpleNamespace(choice="move protect", mode="search")
    update = bot.observe_public_turn(decision=decision, view=view)
    assert update.particles_before == 1
    assert update.particles_after == 0
    assert update.generated_branches == 0
    assert update.conditioning_over_budget is False
    assert update.degraded is False
    assert bot.public_constraint_ledger is public_ledger
    assert bot.last_public_view is view
    assert bot.particles == ()
    assert bot.pending_observations == []
    assert bot.recovery_authority_history_complete is False


def test_public_world_failure_is_reported_without_resurrecting_old_world():
    bot = engine()
    bot.last_public_view = {"turn": 8}
    bot._try_present_public_rebase = lambda **_kw: False
    bot.last_public_world_failure_reason = "unsupported-native-active-position"
    outcome = bot.choose_ai_action(legal_live=["move protect"])
    assert outcome.fallback_reason == (
        "fresh-public-world:unsupported-native-active-position"
    )
    assert bot.degraded
    assert bot.particles == ()
