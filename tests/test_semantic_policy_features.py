from __future__ import annotations

import copy

from champions_practice.semantic_policy_features import (
    action_tokens,
    canonical_action_key,
    normalized_semantic_label,
    rating_weight,
    stable_bucket,
    state_tokens,
)


def _active(species: str, hp: float = 100.0) -> dict:
    return {
        "base_species": species,
        "visible_species": species,
        "hp_percent": hp,
        "status": None,
        "fainted": False,
        "boosts": {},
    }


def _state() -> dict:
    return {
        "schema": "showdown-replay-public-state-v1",
        "turn": 3,
        "gametype": "doubles",
        "field": {
            "weather": "rain",
            "conditions": ["psychicterrain"],
        },
        "sides": {
            "p1": {
                "name": "Alice",
                "preview_species": ["Indeedee-F", "Sneasler", "Rillaboom"],
                "active": [_active("Indeedee-F"), _active("Sneasler", 55.0)],
                "side_conditions": ["reflect"],
                "revealed": [
                    {
                        "species": "Sneasler",
                        "seen": True,
                        "moves": ["direclaw"],
                        "items": [],
                        "abilities": [],
                        "hp_percent": 55.0,
                        "status": None,
                        "fainted": False,
                    }
                ],
            },
            "p2": {
                "name": "Bob",
                "preview_species": ["Pelipper", "Archaludon", "Rillaboom"],
                "active": [_active("Pelipper"), _active("Archaludon", 72.0)],
                "side_conditions": [],
                "revealed": [
                    {
                        "species": "Pelipper",
                        "seen": True,
                        "moves": ["protect"],
                        "items": [],
                        "abilities": ["drizzle"],
                        "hp_percent": 100.0,
                        "status": None,
                        "fainted": False,
                    }
                ],
            },
        },
    }


def test_state_tokens_are_actor_relative():
    original = _state()
    swapped = copy.deepcopy(original)
    swapped["sides"]["p1"], swapped["sides"]["p2"] = (
        swapped["sides"]["p2"],
        swapped["sides"]["p1"],
    )

    assert state_tokens(original, side="p1") == state_tokens(swapped, side="p2")


def test_state_tokens_do_not_include_player_names():
    tokens = state_tokens(_state(), side="p1")

    assert not any("alice" in token or "bob" in token for token in tokens)
    assert "self:active:1:base:indeedeef" in tokens
    assert "opponent:active:1:base:pelipper" in tokens


def test_semantic_action_normalization_collapses_exact_gimmick_variants():
    mega_x = {
        "actions": [
            {
                "slot": 1,
                "kind": "move",
                "move": "psychic",
                "gimmicks": ["megax"],
            },
            {"slot": 2, "kind": "pass"},
        ]
    }
    generic = {
        "actions": [
            {
                "slot": 1,
                "kind": "move",
                "move": "Psychic",
                "gimmicks": ["mega"],
            },
            {"slot": 2, "kind": "pass"},
        ]
    }

    assert normalized_semantic_label(mega_x) == normalized_semantic_label(generic)
    assert canonical_action_key(mega_x) == canonical_action_key(generic)
    assert action_tokens(mega_x) == action_tokens(generic)


def test_stable_bucket_is_repeatable_and_reserves_zero_for_padding():
    first = stable_bucket("self:active:1:base:sneasler", 1024)
    second = stable_bucket("self:active:1:base:sneasler", 1024)

    assert first == second
    assert 1 <= first < 1024


def test_rating_weight_prefers_stronger_ladder_evidence():
    assert rating_weight("1600-1799") > rating_weight("1400-1599")
    assert rating_weight("1400-1599") > rating_weight("1200-1399")
    assert rating_weight("1200-1399") > rating_weight("<1200")
    assert rating_weight("<1200") > rating_weight("unrated")
