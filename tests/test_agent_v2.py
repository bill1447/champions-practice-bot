from dataclasses import asdict, replace
from time import perf_counter

import pytest

from champions_practice.agent_v2 import DecisionInput, PokemonFact, PublicCatalog, decide, observe


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
