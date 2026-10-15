from dataclasses import asdict, replace
from time import perf_counter

import pytest

from champions_practice.agent_v2 import DecisionInput, PokemonFact, PublicCatalog, decide, observe
from champions_practice.agent_v2.policy import rank_action


@pytest.fixture
def catalog():
    return PublicCatalog({"moves": {
        "water": {"category": "Special", "type": "Water", "power": 80, "priority": 0,
                  "accuracy": 100, "target": "normal"},
        "normal": {"category": "Physical", "type": "Normal", "power": 80, "priority": 0,
                   "accuracy": 100, "target": "normal"},
        "tailwind": {"category": "Status", "type": "Flying", "power": 0, "priority": 0,
                     "accuracy": 100, "target": "allySide"}},
        "species": {"fish": ["Water"], "fire": ["Fire"], "ghost": ["Ghost"]},
        "types": {"Fire": {"Water": 1}, "Ghost": {"Normal": 3}}})


@pytest.fixture
def board():
    own = PokemonFact("Fish", 80, False, None, ("Water", "Normal", "Tailwind"), 100)
    return DecisionInput(2, "move", (own,), (own,),
        (PokemonFact("Fire", 100, False, None), PokemonFact("Ghost", 30, False, None)),
        None, None, (), (), ("move water +1", "move normal +2"), perf_counter() + 1)


def test_policy_responds_to_board_typing(board, catalog):
    assert decide(board, catalog).action == "move water +1"
    changed = replace(board, opponents=(board.opponents[1], board.opponents[0]),
                      legal_actions=("move water +2", "move normal +1"))
    assert decide(changed, catalog).action == "move water +2"


def test_expired_deadline_keeps_legal_incumbent(board, catalog):
    result = decide(replace(board, deadline=perf_counter() - 1), catalog)
    assert result.action == board.legal_actions[0]
    assert result.evaluated_actions == 0 and result.deadline_exhausted
    assert result.score_margin is None


@pytest.mark.parametrize("actions", [("wait",), ("switch 1",), ("team 1234",), ("move 1 +1 mega",)])
def test_special_phases_and_numeric_moves_remain_legal(board, catalog, actions):
    assert decide(replace(board, legal_actions=actions), catalog).action in actions


def test_avoid_damage_to_ally(board, catalog):
    result = decide(replace(board, legal_actions=("move water -1", "move water +1")), catalog)
    assert result.action == "move water +1"


def test_tailwind_not_repeated(board, catalog):
    candidate = replace(board, legal_actions=("move tailwind", "move normal +1"))
    assert decide(candidate, catalog).action == "move tailwind"
    assert decide(replace(candidate, own_side_conditions=("tailwind",)), catalog).action == "move normal +1"


def test_reject_private_opponent_fact(board):
    with pytest.raises(ValueError, match="private"):
        replace(board, opponents=(replace(board.opponents[0], ability="flashfire"),))


def test_input_adapter_drops_nonpublic_data(board, catalog):
    own = asdict(board.owned_active[0])
    visible = asdict(board.opponents[0])
    own["boosts"] = {}
    visible["boosts"] = {}
    view = {"turn": 2, "phase": "move", "player": {"active_details": [own], "team": [own]},
            "opponent": {"active": [visible]}, "field": {}}
    first = observe(view, board.legal_actions, deadline=board.deadline)
    visible.update({"item": "secret", "ability": "secret", "moves": ["secret"], "speed": 500,
                    "hp": 123, "maxhp": 200})
    view.update({"prng": "secret", "state": {"secret": True}})
    view["opponent"]["team"] = [{"secret": True}]
    second = observe(view, board.legal_actions, deadline=board.deadline)
    assert first == second
    assert decide(first, catalog).action == decide(second, catalog).action
    assert "secret" not in str(asdict(second))


def test_no_legal_menu_rejected(board):
    with pytest.raises(ValueError, match="legal"):
        replace(board, legal_actions=())


@pytest.mark.parametrize("move_id,move_type", [("earthquake", "Ground"), ("surf", "Water")])
def test_spread_friendly_fire_changes_choice(board, catalog, move_id, move_type):
    catalog.moves[move_id] = {"category": "Physical", "type": move_type, "power": 100,
                              "accuracy": 100, "target": "allAdjacent"}
    partner = PokemonFact("Fish", 25, False, None)
    candidate = replace(board, owned_active=(board.owned_active[0], partner),
                        legal_actions=(f"move {move_id}, wait", "move water +1, wait"))
    assert decide(candidate, catalog).action == "move water +1, wait"
    exposed = rank_action(candidate.legal_actions[0], candidate, catalog)
    empty = replace(candidate, owned_active=(board.owned_active[0], None))
    assert rank_action(candidate.legal_actions[0], empty, catalog).score > exposed.score
    assert any("friendly-fire" in reason for reason in exposed.reasons)


def test_opponent_only_spread_not_penalized(board, catalog):
    catalog.moves["rockslide"] = {"category": "Physical", "type": "Rock", "power": 75,
                                 "accuracy": 90, "target": "allAdjacentFoes"}
    candidate = replace(board, owned_active=(board.owned_active[0], PokemonFact("Fish", 1, False, None)))
    assert rank_action("move rockslide, wait", candidate, catalog).score == rank_action(
        "move rockslide, wait", board, catalog).score


def test_protect_and_switch_do_not_certify_spread_safety(board, catalog):
    catalog.moves["surf"] = {"category": "Special", "type": "Water", "power": 90,
                            "accuracy": 100, "target": "allAdjacent"}
    candidate = replace(board, owned_active=(board.owned_active[0], PokemonFact("Fish", 1, False, None)))
    for action in ("move surf, move protect", "move surf, switch 1"):
        assert any("friendly-fire" in reason for reason in rank_action(action, candidate, catalog).reasons)


@pytest.mark.parametrize("numeric", [False, True])
def test_steel_roller_without_terrain_does_not_receive_attack_credit(board, catalog, numeric):
    catalog.moves["steelroller"] = {"category": "Physical", "type": "Steel", "power": 130,
                                   "accuracy": 100, "target": "normal"}
    own = replace(board.owned_active[0], moves=("Steel Roller", "Water"))
    roller = "move 1 +1" if numeric else "move steelroller +1"
    candidate = replace(board, owned_active=(own,), legal_actions=(roller, "move water +1"))
    assert decide(candidate, catalog).action == "move water +1"
    assert rank_action(roller, candidate, catalog).score == 0
    assert rank_action(roller, replace(candidate, terrain="psychicterrain"), catalog).score > 0


@pytest.mark.parametrize("partner_command,ability,credited", [
    ("move protect", "psychicsurge", False),
    ("switch 2", "psychicsurge", True),
    ("switch 2", "levitate", False),
    ("switch 2", None, True),
    ("move psychicterrain", "levitate", True),
    ("move 1", "levitate", True),
])
def test_steel_roller_keeps_possible_own_terrain_plans(board, catalog, partner_command, ability, credited):
    catalog.moves["steelroller"] = {"category": "Physical", "type": "Steel", "power": 130,
                                   "accuracy": 100, "target": "normal"}
    partner = PokemonFact("Fish", 100, False, None, ("Psychic Terrain",), ability=ability)
    candidate = replace(board, owned_active=(board.owned_active[0], partner),
                        owned_team=(board.owned_active[0], partner))
    score = rank_action("move steelroller +1, " + partner_command, candidate, catalog).score
    # Compare to the same partner command so its switch/status utility cancels.
    without_attack = rank_action("pass, " + partner_command, candidate, catalog).score
    assert (score > without_attack) == credited
