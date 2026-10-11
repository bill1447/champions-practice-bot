import pytest

from champions_practice.diversity_league import POLICIES, ROSTERS, audit_report, catalog, policy_selector


@pytest.mark.parametrize("policy", POLICIES)
def test_policies_are_deterministic_legal_and_avoid_ally_attacks(policy):
    choices = ("move psychic -1, move protect", "move psychic +1, move protect",
               "move psychic +2, switch 3", "move psychic +2, move tailwind")
    left, right = policy_selector(policy, 7), policy_selector(policy, 7)
    selected = [left(choices) for _ in range(12)]
    assert selected == [right(choices) for _ in range(12)]
    assert set(selected) <= set(choices[1:])


def test_pool_covers_diverse_rosters_without_truth_selection():
    pool = catalog()
    assert len({species for roster in ROSTERS.values() for species in roster}) == 13
    assert all(species in pool for roster in ROSTERS.values() for species in roster)
    assert catalog() == pool


def test_audit_does_not_invent_missing_telemetry_and_detects_illegal_action():
    trace = {"complete": True, "mode": "belief-search", "chosen_action": "bad",
             "ai_public_choices_before": ["move protect"], "particle_count": 2, "branch_count": 10}
    report = {"run_id": "test", "games": [{"decision_trace": [trace]}],
              "summary": {"decisions": {"total": 1, "search": 1, "forced_wait": 0, "fallback": 0, "branches": 10}}}
    audit = audit_report(report)
    assert audit["native_admission"] == {"not-recorded": 1}
    assert audit["errors"] == ["chosen-action-not-publicly-legal"]
    trace.update(chosen_action="move protect", native_admission={"path": "present-public", "status": "admitted", "positive_matches": 0})
    assert audit_report(report)["errors"] == ["admitted-without-positive-match"]
