from copy import deepcopy

import pytest

from champions_practice.competitive_evaluation import canonical_view, summarize


def test_side_mapping_is_involution_and_detached():
    view = {"request": {"side": {"id": "p1", "pokemon": [{"ident": "p1: Name"}]}},
            "public_event_delta": [["move", "p1a", "earthquake"], ["-damage", "p2b", 50]],
            "slots": {"p1a": "Garchomp"}, "player": {"hp": 100},
            "literal": "p1a p2b", "target": "+1", "species": "Porygon2"}
    original = deepcopy(view)
    flipped = canonical_view(view, "p1")
    assert flipped["request"]["side"]["id"] == "p2"
    assert flipped["public_event_delta"][0][1] == "p2a"
    assert flipped["slots"] == {"p2a": "Garchomp"}
    assert flipped["target"] == "+1" and flipped["species"] == "Porygon2"
    assert canonical_view(flipped, "p1") == original
    flipped["player"]["hp"] = 1
    assert view == original


def test_p2_copy_and_invalid_side():
    view = {"request": {"side": {"id": "p2"}}}
    assert canonical_view(view, "p2") == view
    assert canonical_view(view, "p2") is not view
    with pytest.raises(ValueError):
        canonical_view(view, "invalid")


def game(status="complete", winner="P1"):
    return {"status": status, "winner": winner, "category": "heldout-direct", "rows": [],
            "agents": {"p1": "v2", "p2": "production"}}


def test_failures_not_counted_as_losses():
    result = summarize([game(), game("failed", None)])
    assert result["agents"]["v2"]["completed"] == 1
    assert result["agents"]["production"]["losses"] == 1
    assert result["statuses"] == {"complete": 1, "failed": 1}
    assert not result["promotion_ready"]


def test_draws_and_empty_reports():
    result = summarize([game(winner=None)])
    assert result["agents"]["v2"]["draws"] == 1
    assert result["agents"]["v2"]["completed_score_rate"] == .5
    assert result["strata"]["heldout-direct"]["v2_wins"] == 0
    assert summarize([])["agents"]["production"]["completed_score_rate"] is None


def test_wait_denominator_and_latency_timeout():
    item = game()
    item["rows"] = [{"sides": {"p2": {"public_choices": ["wait"],
        "telemetry": {"mode": "forced-wait"}, "budget_overrun": False, "wall_seconds": 0}}},
        {"sides": {"p2": {"public_choices": ["move protect"],
        "telemetry": {"mode": "fallback"}, "budget_overrun": True, "wall_seconds": 8.1}}}]
    result = summarize([item, {**game("failed", None), "error_type": "ShowdownWorkerTimeout"}])
    assert result["agents"]["production"]["actionable_decisions"] == 1
    assert result["agents"]["production"]["fallback_rate"] == 1
    assert result["agents"]["production"]["budget_overruns"] == 1
    assert result["transport_timeouts"] == 1
