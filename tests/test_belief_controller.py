import pytest

from champions_practice.belief_controller import choose_public_fallback


def test_public_fallback_returns_legal_choice_without_friendly_fire() -> None:
    choices = [
        "move psychic -2, move protect",
        "move protect, move wideguard",
        "switch 3, switch 4",
    ]

    chosen = choose_public_fallback(choices)

    assert chosen in choices
    assert chosen != "move psychic -2, move protect"


def test_public_fallback_requires_legal_choices() -> None:
    with pytest.raises(ValueError, match="at least one legal choice"):
        choose_public_fallback([])
