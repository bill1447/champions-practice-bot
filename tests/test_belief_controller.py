import pytest

from champions_practice.belief_controller import _pin_known_team_genders, choose_public_fallback


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


def test_pin_known_team_genders_uses_own_public_request() -> None:
    team = """Armarouge @ Life Orb
Ability: Flash Fire
Level: 50
- Protect

Sneasler @ Psychic Seed
Ability: Unburden
Level: 50
- Protect
"""
    request = {
        "side": {
            "pokemon": [
                {"details": "Armarouge, L50, F"},
                {"details": "Sneasler, L50, M"},
            ]
        }
    }

    pinned = _pin_known_team_genders(team, request)

    assert "Gender: F" in pinned
    assert "Gender: M" in pinned
