"""Tests for the explicit synthetic hidden-spread regression fixture."""

from __future__ import annotations

import pytest

from champions_practice.strength_league import (
    FIXTURE_ID as MIRROR_FIXTURE_ID,
    LeagueConfig,
    _run_id,
    _run_identity_payload,
)
from champions_practice.uncertain_fixture import (
    FIXTURE_ID,
    SOURCE_LABEL,
    opponent_selection,
    opponent_team,
    public_priors,
)


def test_three_distinct_valid_shape_spreads_for_every_species() -> None:
    priors = public_priors()
    assert len(priors) == 6
    assert SOURCE_LABEL == "synthetic-in-repository-not-vgcpastes"
    for species, candidates in priors.items():
        assert len(candidates) == 3, species
        assert len({candidate.team_text for candidate in candidates}) == 3
        assert len({candidate.label for candidate in candidates}) == 3
        for candidate in candidates:
            stat_values = dict(candidate.stat_points)
            assert sum(stat_values.values()) == 66
            assert all(0 <= value <= 32 for value in stat_values.values())
            assert candidate.species == species


def test_opponent_truth_varies_without_changing_public_prior() -> None:
    baseline_public_pool = public_priors()
    seen = set()
    for game in range(8):
        chosen = opponent_selection(15601, game)
        assert len(chosen) == 6
        assert all(choice in (0, 1, 2) for choice in chosen)
        seen.add(opponent_team(15601, game))
        assert public_priors() == baseline_public_pool
    assert len(seen) > 3
    for slot in range(6):
        assert {opponent_selection(15601, game)[slot] for game in range(8)} == {
            0, 1, 2
        }


def test_fixture_selection_keeps_frozen_mirror_run_identity_shape() -> None:
    mirror = LeagueConfig()
    uncertain = LeagueConfig(fixture=FIXTURE_ID)
    params = {"git_commit": "a" * 40, "showdown_revision": "b" * 40}
    mirror_payload = _run_identity_payload(mirror, **params)
    uncertain_payload = _run_identity_payload(uncertain, **params)

    assert mirror_payload["fixture_id"] == MIRROR_FIXTURE_ID
    assert mirror_payload["config"] == {
        key: value for key, value in vars(mirror).items() if key != "fixture"
    }
    assert uncertain_payload["fixture_id"] == FIXTURE_ID
    assert uncertain_payload["config"]["fixture"] == FIXTURE_ID
    assert uncertain_payload["opponent_team_sha256"] != mirror_payload[
        "opponent_team_sha256"
    ]
    assert _run_id(mirror, **params) != _run_id(uncertain, **params)
    with pytest.raises(ValueError, match="unsupported"):
        LeagueConfig(fixture="unvalidated-external-corpus")
