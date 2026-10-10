"""The strength opponent must not reuse the bot's defensive fallback."""

from champions_practice.strength_league import BASELINE_ID, _baseline_choice


def test_attacking_baseline_rejects_protect_spam():
    choices = (
        "move protect, move protect",
        "move psychic, move protect",
        "move psychic, move dazzlinggleam",
    )
    assert _baseline_choice(choices) == "move psychic, move dazzlinggleam"
    assert BASELINE_ID != "public-fallback-v1"


def test_attacking_baseline_prefers_mega_when_attacks_equal():
    choices = (
        "move psychic, move dazzlinggleam",
        "move psychic mega, move dazzlinggleam",
    )
    assert _baseline_choice(choices) == choices[1]


def test_attacking_baseline_always_returns_legal_choice():
    choices = ("switch 3, move protect", "move protect, move protect")
    assert _baseline_choice(choices) in choices


def test_baseline_does_not_attack_own_partner_on_target_tie():
    choices = (
        "move psychic +1, move expandingforce +1",
        "move psychic -2, move expandingforce -1",
    )
    assert _baseline_choice(choices) == choices[0]


def test_baseline_rejects_ally_target_mega_tie_break():
    choices = (
        "move mysticalfire -1 mega, move psychic +1",
        "move mysticalfire +1 mega, move psychic +1",
    )
    assert _baseline_choice(choices) == choices[1]


def test_baseline_prefers_non_ally_target_over_extra_attack():
    choices = (
        "move psychic -2, move expandingforce +1",
        "move protect, move expandingforce +1",
    )
    assert _baseline_choice(choices) == choices[1]
