from copy import deepcopy

import pytest

from champions_practice.beliefs import (
    PublicInformationLeak,
    build_public_opponent_belief,
    public_response_hypotheses,
)


def _view() -> dict:
    species = [
        "Indeedee-F",
        "Sneasler",
        "Gardevoir",
        "Armarouge",
        "Rillaboom",
        "Metagross",
    ]
    return {
        "turn": 1,
        "phase": "move",
        "opponent": {
            "name": "Opponent",
            "preview_species": species,
            "active": [
                {
                    "species": "Gardevoir",
                    "base_species": "Gardevoir",
                    "hp_percent": 100,
                    "fainted": False,
                    "status": None,
                    "boosts": {"spa": 0, "spe": 0},
                },
                {
                    "species": "Indeedee-F",
                    "base_species": "Indeedee-F",
                    "hp_percent": 82.4,
                    "fainted": False,
                    "status": None,
                    "boosts": {"spd": 1},
                },
            ],
            "revealed": [
                {
                    "species": species_name,
                    "moves": ["hypervoice"] if species_name == "Gardevoir" else [],
                    "items": ["gardevoirite"] if species_name == "Gardevoir" else [],
                    "abilities": ["trace"] if species_name == "Gardevoir" else [],
                    "fainted": False,
                }
                for species_name in species
            ],
        },
    }


def test_public_belief_contains_only_observed_information() -> None:
    belief = build_public_opponent_belief(_view())

    assert len(belief.pokemon) == 6
    assert [pokemon.species for pokemon in belief.active] == [
        "Gardevoir",
        "Indeedee-F",
    ]
    assert belief.possible_bench_species == (
        "Sneasler",
        "Armarouge",
        "Rillaboom",
        "Metagross",
    )
    assert belief.active[0].revealed_moves == ("hypervoice",)
    assert belief.active[0].revealed_items == ("gardevoirite",)
    assert belief.active[0].revealed_abilities == ("trace",)


def test_public_belief_rejects_private_fields() -> None:
    view = _view()
    view["opponent"]["active"][0]["moves"] = ["mysticalfire"]

    with pytest.raises(PublicInformationLeak, match="non-public fields"):
        build_public_opponent_belief(view)


def test_response_hypotheses_are_bounded_and_avoid_duplicate_switches() -> None:
    belief = build_public_opponent_belief(_view())

    hypotheses = public_response_hypotheses(belief, limit=32)

    assert len(hypotheses) == 26
    assert len(hypotheses) <= 32
    assert any(
        action.kind == "revealed_move"
        for hypothesis in hypotheses
        for action in hypothesis.actions
    )
    assert any(
        action.kind == "unknown_move"
        for hypothesis in hypotheses
        for action in hypothesis.actions
    )
    for hypothesis in hypotheses:
        switches = [
            action.detail for action in hypothesis.actions if action.kind == "switch"
        ]
        assert len(switches) == len(set(switches))


def test_unrelated_player_private_data_cannot_change_opponent_hypotheses() -> None:
    first_view = _view()
    second_view = deepcopy(first_view)
    first_view["player"] = {"team": [{"moves": ["psychic"]}]}
    second_view["player"] = {"team": [{"moves": ["steelroller"]}]}

    first = public_response_hypotheses(build_public_opponent_belief(first_view))
    second = public_response_hypotheses(build_public_opponent_belief(second_view))

    assert first == second
