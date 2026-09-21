from copy import deepcopy

import pytest

from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.belief_worlds import (
    MissingPublicSetPrior,
    PublicSetCandidate,
    materialize_public_belief_worlds,
)


SPECIES = (
    "Indeedee-F",
    "Sneasler",
    "Gardevoir",
    "Armarouge",
    "Rillaboom",
    "Metagross",
)


def _view(
    *,
    active: tuple[str, str] = ("Gardevoir", "Indeedee-F"),
) -> dict:
    return {
        "turn": 1,
        "phase": "move",
        "opponent": {
            "name": "Opponent",
            "preview_species": list(SPECIES),
            "active": [
                {
                    "species": species,
                    "base_species": species,
                    "hp_percent": 100,
                    "fainted": False,
                    "status": None,
                    "boosts": {},
                }
                for species in active
            ],
            "revealed": [
                {
                    "species": species,
                    "moves": [],
                    "items": [],
                    "abilities": [],
                    "fainted": False,
                    "seen": species in active,
                }
                for species in SPECIES
            ],
        },
    }


def _candidate(
    species: str,
    *,
    item: str = "Sitrus Berry",
    ability: str = "Pressure",
    moves: tuple[str, ...] = ("Protect", "Tackle"),
    label: str = "standard",
    weight: float = 1.0,
) -> PublicSetCandidate:
    return PublicSetCandidate(
        species=species,
        item=item,
        ability=ability,
        nature="Hardy",
        stat_points=(("hp", 32), ("atk", 32), ("spe", 2)),
        moves=moves,
        label=label,
        weight=weight,
    )


def _priors() -> dict[str, tuple[PublicSetCandidate, ...]]:
    priors = {species: (_candidate(species),) for species in SPECIES}
    priors["Metagross"] = (
        _candidate(
            "Metagross",
            item="Metagrossite",
            ability="Clear Body",
            moves=("Psychic Fangs", "Steel Roller", "Stomping Tantrum", "Protect"),
            label="mega",
            weight=2.0,
        ),
        _candidate(
            "Metagross",
            item="Leftovers",
            ability="Light Metal",
            moves=("Bullet Punch", "Zen Headbutt", "Ice Punch", "Protect"),
            label="bulky",
            weight=1.0,
        ),
    )
    return priors


def test_materializer_explores_selected_four_and_set_uncertainty() -> None:
    belief = build_public_opponent_belief(_view())

    worlds = materialize_public_belief_worlds(belief, _priors(), limit=32)

    # Two active Pokemon are known selected. Choosing two of four unseen species gives
    # six bring-four hypotheses. Metagross is selected in three of those and has two
    # compatible set priors, so the bounded materializer produces nine worlds.
    assert len(worlds) == 9
    assert all("Gardevoir" in world.selected_species for world in worlds)
    assert all("Indeedee-F" in world.selected_species for world in worlds)
    assert {world.set_for_species("Metagross").label for world in worlds} == {
        "mega",
        "bulky",
    }


def test_reveals_filter_incompatible_public_set_priors() -> None:
    view = _view(active=("Metagross", "Armarouge"))
    metagross = next(
        observation
        for observation in view["opponent"]["revealed"]
        if observation["species"] == "Metagross"
    )
    metagross["moves"] = ["psychicfangs"]
    metagross["items"] = ["metagrossite"]
    metagross["abilities"] = ["clearbody"]

    worlds = materialize_public_belief_worlds(
        build_public_opponent_belief(view),
        _priors(),
        limit=32,
    )

    assert len(worlds) == 6
    assert {
        world.set_for_species("Metagross").label for world in worlds
    } == {"mega"}


def test_seen_bench_species_must_remain_in_every_selected_four() -> None:
    view = _view()
    rillaboom = next(
        observation
        for observation in view["opponent"]["revealed"]
        if observation["species"] == "Rillaboom"
    )
    rillaboom["seen"] = True

    worlds = materialize_public_belief_worlds(
        build_public_opponent_belief(view),
        _priors(),
        limit=32,
    )

    assert worlds
    assert all("Rillaboom" in world.selected_species for world in worlds)


def test_hidden_state_outside_public_view_cannot_change_materialized_worlds() -> None:
    first = _view()
    second = deepcopy(first)
    first["hidden_exact_state"] = {"Metagross": {"moves": ["Psychic Fangs"]}}
    second["hidden_exact_state"] = {"Metagross": {"moves": ["Bullet Punch"]}}

    first_worlds = materialize_public_belief_worlds(
        build_public_opponent_belief(first),
        _priors(),
        limit=32,
    )
    second_worlds = materialize_public_belief_worlds(
        build_public_opponent_belief(second),
        _priors(),
        limit=32,
    )

    assert first_worlds == second_worlds


def test_missing_matching_prior_fails_closed() -> None:
    view = _view(active=("Metagross", "Armarouge"))
    metagross = next(
        observation
        for observation in view["opponent"]["revealed"]
        if observation["species"] == "Metagross"
    )
    metagross["moves"] = ["explosion"]

    with pytest.raises(MissingPublicSetPrior, match="Metagross"):
        materialize_public_belief_worlds(
            build_public_opponent_belief(view),
            _priors(),
        )


def test_world_team_text_contains_all_preview_species() -> None:
    world = materialize_public_belief_worlds(
        build_public_opponent_belief(_view()),
        _priors(),
        limit=1,
    )[0]

    assert world.team_text.count("Ability:") == 6
    for species in SPECIES:
        assert species in world.team_text
