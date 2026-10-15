from dataclasses import replace
from time import perf_counter

import pytest

from champions_practice.agent_v2.policy import DecisionInput, OpponentEvidence, PokemonFact, PublicCatalog, decide, decide_baseline, decide_coordination, decide_risk, observe
from champions_practice.agent_v2.joint import Part, Response, assess, candidates, parse, responses, simulate


@pytest.fixture
def catalog():
    def move(power=50, priority=0, category="Physical", target="normal"):
        return {"category": category, "type": "Normal", "power": power,
                "priority": priority, "accuracy": 100, "target": target, "protect": True}
    return PublicCatalog({"moves": {"hit": move(), "protect": move(0, 4, "Status", "self"),
        "tailwind": move(0, 0, "Status", "allySide"), "followme": move(0, 2, "Status", "self"),
        "spread": move(50, 0, target="allAdjacentFoes"), "priority": move(50, 1)},
        "species": {"own": ["Normal"], "foe": ["Normal"], "ghost": ["Ghost"]},
        "base_stats": {"foe": {"hp": 80, "atk": 80, "spa": 80, "def": 80, "spd": 80, "spe": 80}},
        "support": {"foe": ["protect"]}, "types": {"Ghost": {"Normal": 3}}})


@pytest.fixture
def board():
    own = PokemonFact("Own", 100, False, None, ("Hit", "Protect", "Tailwind"), 250,
                      hp=100, maxhp=100, stats=(("atk", 140), ("def", 100), ("spd", 100)))
    foe = PokemonFact("Foe", 15, False, None)
    return DecisionInput(1, "move", (own, own), (own, own), (foe, replace(foe, hp_percent=100)),
                         None, None, (), (), ("move hit +1, move hit +1", "move hit +1, move hit +2",
                         "move hit +1, move tailwind"), perf_counter()+5)


def score(action, board, catalog, reply):
    return assess(action, board, catalog, reply)[0].score


def test_decisive_double_target_when_no_protect(board, catalog):
    reply = (Response("attacks", (Part("move", "hit", 1), Part("move", "hit", 2)), 1),)
    assert score(board.legal_actions[0], board, catalog, reply) > score(board.legal_actions[1], board, catalog, reply)


def test_protect_changes_joint_preference(board, catalog):
    reply = (Response("protect A", (Part("move", "protect"), Part("move", "hit", 1)), 1),)
    assert score(board.legal_actions[1], board, catalog, reply) > score(board.legal_actions[0], board, catalog, reply)


def test_unlikely_protect_does_not_forbid_decisive_focus(board, catalog):
    board = replace(board, opponent_evidence=(OpponentEvidence("Foe", protect_tendency="low"),))
    scenarios = responses(board, catalog)
    assert any("protect" in r.label for r in scenarios)
    assert score(board.legal_actions[0], board, catalog, scenarios) > score(board.legal_actions[1], board, catalog, scenarios)


def test_threatened_ally_prefers_shield_or_switch(board, catalog):
    weak = replace(board.owned_active[0], hp=1, hp_percent=1, speed=20)
    bench = replace(board.owned_active[1], species="Ghost")
    board = replace(board, owned_active=(weak, board.owned_active[1]), owned_team=(weak, board.owned_active[1], bench))
    reply = (Response("focus ally", (Part("move", "hit", 1), Part("move", "hit", 1)), 1),)
    attack = score("move hit +1, move hit +2", board, catalog, reply)
    assert max(score("move protect, move hit +2", board, catalog, reply),
               score("switch 3, move hit +2", board, catalog, reply)) > attack


def test_repeat_protect_retains_failure_continuation(board, catalog):
    reply = Response("attacks", (Part("move", "hit", 1), Part("move", "hit", 1)), 1)
    board = replace(board, recent_own_protect=(0,))
    plan = parse("move protect, move hit +2", board)
    adverse = simulate(plan, reply, board, catalog, adverse=True)
    favorable = simulate(plan, reply, board, catalog, adverse=False)
    assert adverse["own_damage"] > favorable["own_damage"]


def test_redirection_changes_single_target_not_spread(board, catalog):
    reply = Response("redirect", (Part("move", "hit", 1), Part("move", "followme")), 1)
    redirected = simulate(parse("move hit +1, move hit +1", board), reply, board, catalog, adverse=True)
    spread = simulate(parse("move spread, move spread", board), reply, board, catalog, adverse=True)
    assert redirected["opponent_kos"] == 0
    assert spread["opponent_kos"] >= 1


def test_priority_can_act_before_faster_regular_move(board, catalog):
    board = replace(board, owned_active=(replace(board.owned_active[0], hp=1, speed=1), None),
                    opponents=(replace(board.opponents[0], hp_percent=1), None))
    reply = Response("attack", (Part("move", "hit", 1), Part("pass")), 1)
    regular = simulate(parse("move hit +1", board), reply, board, catalog, adverse=True)
    priority = simulate(parse("move priority +1", board), reply, board, catalog, adverse=True)
    assert regular["own_kos"] == 1 and priority["own_kos"] == 0


def test_weights_respond_to_our_focus_plan(board, catalog):
    scenarios = responses(board, catalog)
    double = assess(board.legal_actions[0], board, catalog, scenarios)[1]
    split = assess(board.legal_actions[1], board, catalog, scenarios)[1]
    shield_double = next(r for r in double["responses"] if r["response"] == "protect / generic:Normal:0")
    shield_split = next(r for r in split["responses"] if r["response"] == "protect / generic:Normal:0")
    assert shield_double["priority_weight"] > shield_split["priority_weight"]
    assert not double["weights_are_probabilities"] and not double["guaranteed_ko"]


def test_strategic_families_and_legal_deadline_incumbent(board, catalog):
    board = replace(board, legal_actions=board.legal_actions + ("move protect, move hit +2", "switch 1, move hit +2"))
    assert "move protect, move hit +2" in candidates(board, catalog, limit=1)
    expired = decide_risk(replace(board, deadline=perf_counter()-1), catalog)
    assert expired.action in board.legal_actions and not expired.evaluated_actions
    result = decide_risk(board, catalog)
    assert result.action in board.legal_actions and result.joint_analysis


def test_native_ledger_shape_and_switch_reset():
    mon = {"species": "Own", "hp_percent": 100, "fainted": False, "moves": ["Protect"]}
    view = {"turn": 2, "phase": "move", "player": {"team": [mon], "active_details": [mon]},
            "opponent": {"active": [{"species": "Foe", "hp_percent": 100}], "revealed": []},
            "request": {"side": {"id": "p1", "pokemon": [{"stats": {"atk": 100}}]}},
            "public_event_delta": {"turn": 1, "events": [["-singleturn", "p1a", "protect"], ["-singleturn", "p2a", "protect"]]}}
    result = observe(view, ["move protect"], deadline=perf_counter()+1)
    assert result.recent_own_protect == (0,)
    assert result.opponent_evidence[0].recent_protect
    assert dict(result.owned_active[0].stats)["atk"] == 100
    view["public_event_delta"]["events"].append(["switch", "p1a", "Own"])
    assert not observe(view, ["move protect"], deadline=perf_counter()+1).recent_own_protect


def test_cannot_switch_two_opponents_into_same_reserve(board, catalog):
    board = replace(board, opponent_preview=("Foe", "Bench"))
    assert all(len([p.incoming for p in r.parts if p.kind == "switch"]) <= 1 for r in responses(board, catalog))


def test_attack_plus_tailwind_has_positional_value_against_protect(board, catalog):
    own = tuple(replace(mon, speed=90) for mon in board.owned_active)
    board = replace(board, owned_active=own)
    reply = (Response("protect A", (Part("move", "protect"), Part("move", "hit", 1)), 1),)
    assert score("move hit +1, move tailwind", board, catalog, reply) > score("move hit +1, move hit +1", board, catalog, reply)


def test_unrevealed_protect_remains_hypothesis_without_direct_learnset(board, catalog):
    catalog.support["foe"] = []
    assert any("protect" in r.label for r in responses(board, catalog))


def test_reserves_protect_for_each_slot_and_all_incoming_choices(board, catalog):
    choices = ("move hit +1, move hit +1", "move protect, move hit +1", "move hit +1, move protect",
               "switch 3, move hit +1", "switch 4, move hit +1", "move hit +1, switch 3", "move hit +1, switch 4")
    board = replace(board, legal_actions=choices)
    prepared = candidates(board, catalog, limit=1)
    assert all(a in prepared for a in choices[1:])


def test_normal_attack_retargets_after_selected_foe_faints(board, catalog):
    board = replace(board, opponents=(replace(board.opponents[0], hp_percent=1), board.opponents[1]))
    reply = Response("attacks", (Part("move", "hit", 1), Part("move", "hit", 2)), 1)
    both = simulate(parse("move hit +1, move hit +1", board), reply, board, catalog, adverse=True)
    one = simulate(parse("move hit +1, pass", board), reply, board, catalog, adverse=True)
    assert both["opponent_pressure"] > one["opponent_pressure"]


def test_counterresponse_weights_do_not_see_our_private_stats(board, catalog):
    reply = responses(board, catalog)
    first = assess(board.legal_actions[0], board, catalog, reply)[1]
    private_changed = replace(board, owned_active=tuple(replace(mon, stats=(("atk", 5000),),
        item="secret", ability="secret", speed=5000) for mon in board.owned_active))
    second = assess(board.legal_actions[0], private_changed, catalog, reply)[1]
    assert [r["priority_weight"] for r in first["responses"]] == [r["priority_weight"] for r in second["responses"]]
    assert first["response_forecast_uses_private_owned_stats"] is False


def test_coordination_only_changes_exact_top_ties(board, catalog):
    # Different health creates different baseline utilities; no joint override.
    old = decide_baseline(board, catalog)
    new = decide_coordination(board, catalog)
    assert old.action == new.action and not new.joint_analysis


def test_coordination_protect_counterexample_splits_tied_attacks(board, catalog, monkeypatch):
    tied = replace(board, opponents=(board.opponents[1], board.opponents[1]),
                   legal_actions=board.legal_actions[:2])
    monkeypatch.setattr('champions_practice.agent_v2.joint.responses', lambda *_: (
        Response('shield A', (Part('move', 'protect'), Part('move', 'hit', 1)), 1),))
    assert decide_baseline(tied, catalog).action == tied.legal_actions[0]
    result = decide_coordination(tied, catalog)
    assert result.action == tied.legal_actions[1]
    assert result.alternatives[0].action == result.action
    assert len(result.joint_analysis) == 2
    assert result.elapsed_ms >= 0
    assert decide(tied, catalog).action == result.action


def test_coordination_incomplete_comparison_keeps_incumbent(board, catalog, monkeypatch):
    tied = replace(board, opponents=(board.opponents[1], board.opponents[1]),
                   legal_actions=board.legal_actions[:2])
    monkeypatch.setattr('champions_practice.agent_v2.joint.assess', lambda *_: None)
    assert decide_coordination(tied, catalog).action == tied.legal_actions[0]
    assert not decide_coordination(tied, catalog).joint_analysis


def test_coordination_expired_deadline_keeps_legal_incumbent(board, catalog):
    expired = replace(board, deadline=perf_counter()-1)
    result = decide_coordination(expired, catalog)
    assert result.action == expired.legal_actions[0] and result.deadline_exhausted


def test_coordination_prefers_combined_knockout_without_shield(board, catalog, monkeypatch):
    tied = replace(board, opponents=(board.opponents[0], board.opponents[0]),
                   legal_actions=(board.legal_actions[1], board.legal_actions[0]))
    monkeypatch.setattr('champions_practice.agent_v2.joint.responses', lambda *_: (
        Response('attacks', (Part('move', 'hit', 1), Part('move', 'hit', 2)), 1),))
    assert decide_baseline(tied, catalog).action == tied.legal_actions[0]
    assert decide_coordination(tied, catalog).action == tied.legal_actions[1]


@pytest.mark.parametrize('change', ['charge', 'spread', 'request_spread', 'dynamic'])
def test_coordination_avoids_unsupported_attack_families(board, catalog, change):
    tied = replace(board, opponents=(board.opponents[1], board.opponents[1]),
                   legal_actions=board.legal_actions[:2])
    if change == 'charge':
        catalog.moves['hit']['charge'] = True
    elif change == 'dynamic':
        catalog.moves['hit']['modifiesMove'] = True
    elif change == 'spread':
        catalog.moves['hit']['target'] = 'allAdjacentFoes'
    else:
        tied = replace(tied, owned_active=tuple(replace(m, move_targets=(('hit', 'allAdjacentFoes'),))
                                               for m in tied.owned_active))
    result = decide_coordination(tied, catalog)
    assert result.action == decide_baseline(tied, catalog).action
    assert not result.joint_analysis
