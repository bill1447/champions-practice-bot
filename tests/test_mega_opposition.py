"""Mega completion respects the authoritative menu and upstream choices."""

from pathlib import Path

import pytest


@pytest.mark.parametrize(('action', 'menu', 'expected'), [
    ('move hypervoice, move protect', ['move hypervoice, move protect', 'move hypervoice mega, move protect'],
     'move hypervoice mega, move protect'),
    ('move hypervoice, switch 3', ['move hypervoice, switch 3'], 'move hypervoice, switch 3'),
    ('switch 3, pass', ['switch 3, pass'], 'switch 3, pass'),
    ('wait', ['wait'], 'wait'),
    ('move protect, move protect', ['move protect, move protect', 'move hypervoice mega, move protect'],
     'move protect, move protect'),
    ('move protect, move protect', ['move protect, move protect', 'move protect mega, move protect',
                                   'move protect, move protect mega'], 'move protect mega, move protect'),
])
def test_only_legal_same_move_completion(monkeypatch, action, menu, expected):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    from mega_opposition_evaluation import MegaOpponent
    from champions_practice.independent_opponent import IndependentOpponent
    monkeypatch.setattr(IndependentOpponent, 'choose', lambda *_: (action, {'fallback': False}))
    bot = object.__new__(MegaOpponent)
    choice, trace = bot.choose({'private': 'ignored'}, menu)
    assert choice == expected and choice in menu
    assert trace['upstream_action'] == action
    assert trace['mega_augmentation'] == (choice != action)
