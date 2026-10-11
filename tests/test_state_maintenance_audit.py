"""Unresolved history witnesses must not become current-state coverage."""

from types import SimpleNamespace

from champions_practice.state_maintenance_audit import queued_alternatives, transition_failure


def update(**kwargs):
    defaults = dict(
        particles=(),
        unsupported_public_evidence=(),
        matched_world_ids=(),
        exhaustively_excluded_world_ids=(),
        sampled_unresolved_world_ids=("true",),
    )
    return SimpleNamespace(**(defaults | kwargs))


def test_partial_witness_is_unresolved_even_with_positive_children():
    assert (
        transition_failure(update(matched_world_ids=("lucky",)), False) == "partial-world-witness"
    )


def test_native_complete_posterior_advances():
    assert transition_failure(update(particles=(object(),)), False) is None


def test_timed_out_positive_result_does_not_advance():
    assert transition_failure(update(particles=(object(),)), True) == "conditioning-timeout"


def test_sample_miss_is_not_exhaustive_disproof():
    assert transition_failure(update(), False) == "no-complete-witness"
    assert (
        transition_failure(update(exhaustively_excluded_world_ids=("wrong",)), False)
        == "no-complete-witness"
    )
    assert (
        transition_failure(
            update(exhaustively_excluded_world_ids=("wrong",), sampled_unresolved_world_ids=()),
            False,
        )
        == "all-catalog-worlds-disproved"
    )


def test_unsupported_evidence_remains_explicit():
    assert (
        transition_failure(update(unsupported_public_evidence=("cant",)), False)
        == "unsupported-public-evidence"
    )


def test_hidden_queued_commands_remain_distinct_under_same_world():
    def particle(move, target):
        return SimpleNamespace(
            world_id="same-set",
            state={
                "queue": [
                    {
                        "choice": "move",
                        "pokemon": "[Pokemon:p1b]",
                        "moveid": move,
                        "targetLoc": target,
                    },
                    {"choice": "residual"},
                ]
            },
        )

    alternatives = queued_alternatives(
        (particle("partingshot", 1), particle("darkestlariat", 1), particle("partingshot", 2))
    )
    assert len(alternatives["same-set"]) == 3
