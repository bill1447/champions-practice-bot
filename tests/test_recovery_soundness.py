from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from champions_practice.reachability import (
    ReachabilityCoverage,
    ReachabilityResult,
    ReachabilityStatus,
)
from champions_practice.observation_beliefs import (
    BeliefParticle,
    ParticleUpdate,
)
from champions_practice.recovery_soundness import (
    ConditioningSoundnessReport,
    RecoverySoundnessError,
    RecoverySoundnessReport,
    TrueWorldConditioningCase,
    TrueWorldConditioningOutcome,
    TrueWorldTransition,
    conditioning_false_exclusion_payload,
    evaluate_true_world_conditioning_suite,
    evaluate_true_world_suite,
    false_exclusion_payload,
    generate_true_world_transition,
    write_false_exclusion_regressions,
)


def _coverage(*, exhaustive: bool) -> ReachabilityCoverage:
    return ReachabilityCoverage(
        sequential_context_fingerprint="sha256:test-context",
        transitions_covered=1,
        outcomes_examined=1,
        randomness_domains=() if exhaustive else ("showdown-prng-seed",),
        randomness_exhaustive=exhaustive,
        sequential_context_complete=True,
    )


def _transition(case_id: str) -> TrueWorldTransition:
    return TrueWorldTransition(
        case_id=case_id,
        source="unit-test",
        side="p2",
        pre_state={"case": case_id, "turn": 1},
        p1_choice="move tackle +1",
        p2_choice="move protect",
        actual_public_view={"case": case_id},
        previous_public_view={"case": "before"},
        actual_rng_seed="sodium," + "1" * 64,
        probe_rng_seed="sodium," + "2" * 64,
        actual_rng_draw_count=1,
        previews={"p1": ["A"], "p2": ["B"]},
    )


def _status_evaluator(worker, *, state, side, step, previews):
    del worker, side, step, previews
    case_id = state["case"]
    if case_id == "witness":
        return ReachabilityResult.witnessed(
            coverage=_coverage(exhaustive=False),
            witness_ids=("sha256:witness",),
        )
    if case_id == "unresolved":
        return ReachabilityResult.unresolved(
            reason="sampled RNG miss",
            coverage=ReachabilityCoverage(
                sequential_context_fingerprint="sha256:sampled",
                transitions_covered=1,
                outcomes_examined=1,
                randomness_domains=("showdown-prng-seed",),
                randomness_exhaustive=False,
                sequential_context_complete=True,
            ),
        )
    if case_id == "unsupported":
        return ReachabilityResult.unsupported(
            reason="unsupported mechanics event"
        )
    if case_id == "false-exclusion":
        return ReachabilityResult.exhaustively_disproved(
            coverage=_coverage(exhaustive=True)
        )
    raise AssertionError(f"unexpected case {case_id!r}")


def test_report_counts_only_exhaustive_disproof_as_true_world_exclusion():
    transitions = tuple(
        _transition(case_id)
        for case_id in (
            "witness",
            "unresolved",
            "unsupported",
            "false-exclusion",
        )
    )

    report = evaluate_true_world_suite(
        object(),
        transitions,
        evaluator=_status_evaluator,
    )

    assert report.total == 4
    assert report.survived == 3
    assert report.false_exclusions == 1
    assert report.witnessed == 1
    assert report.unresolved == 1
    assert report.unsupported == 1
    assert report.true_world_survival_rate == 0.75
    assert report.sound is False
    assert report.summary() == {
        "total": 4,
        "survived": 3,
        "false_exclusions": 1,
        "witnessed": 1,
        "unresolved": 1,
        "unsupported": 1,
        "true_world_survival_rate": 0.75,
        "sound": False,
    }


def test_empty_report_is_vacuously_sound_but_exposes_zero_coverage():
    report = RecoverySoundnessReport(outcomes=())

    assert report.total == 0
    assert report.true_world_survival_rate == 1.0
    assert report.sound is True


def test_false_exclusion_payload_is_self_contained():
    report = evaluate_true_world_suite(
        object(),
        (_transition("false-exclusion"),),
        evaluator=_status_evaluator,
    )
    outcome = report.outcomes[0]

    payload = false_exclusion_payload(outcome)

    assert payload["schema"] == "recovery-true-world-regression-v1"
    assert payload["case_id"] == "false-exclusion"
    assert payload["source"] == "unit-test"
    assert payload["pre_state"] == {"case": "false-exclusion", "turn": 1}
    assert payload["p1_choice"] == "move tackle +1"
    assert payload["p2_choice"] == "move protect"
    assert payload["actual_public_view"] == {"case": "false-exclusion"}
    assert payload["previous_public_view"] == {"case": "before"}
    assert payload["actual_rng_seed"] == "sodium," + "1" * 64
    assert payload["probe_rng_seed"] == "sodium," + "2" * 64
    assert payload["actual_rng_draw_count"] == 1
    assert payload["state_fingerprint"].startswith("sha256:")
    assert (
        payload["reachability"]["status"]
        == ReachabilityStatus.EXHAUSTIVELY_DISPROVED.value
    )
    assert payload["reachability"]["coverage"]["randomness_exhaustive"] is True


def test_non_exclusion_cannot_be_serialized_as_failure():
    report = evaluate_true_world_suite(
        object(),
        (_transition("unresolved"),),
        evaluator=_status_evaluator,
    )

    with pytest.raises(ValueError, match="only false exclusions"):
        false_exclusion_payload(report.outcomes[0])


def test_false_exclusion_writer_writes_only_failures(tmp_path: Path):
    transitions = (
        _transition("witness"),
        _transition("false-exclusion"),
        _transition("unsupported"),
    )
    report = evaluate_true_world_suite(
        object(),
        transitions,
        evaluator=_status_evaluator,
    )

    paths = write_false_exclusion_regressions(
        report,
        output_dir=tmp_path / "hard-cases",
    )

    assert len(paths) == 1
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    assert payload["case_id"] == "false-exclusion"
    assert list((tmp_path / "hard-cases").glob("*.part")) == []


def _particle(world_id: str) -> BeliefParticle:
    return BeliefParticle(
        state={"world": world_id},
        weight=0.5,
        world_id=world_id,
        history_id=f"history-{world_id}",
    )


def test_conditioning_report_detects_true_world_drop(monkeypatch):
    true_particle = _particle("true")
    decoy_particle = _particle("decoy")
    case = TrueWorldConditioningCase(
        transition=_transition("conditioning-drop"),
        particles=(true_particle, decoy_particle),
        true_world_id="true",
        rng_seeds=("sodium," + "3" * 64,),
        max_particles=2,
        resample_seed=7,
    )

    def fake_condition(*args, **kwargs):
        del args, kwargs
        return ParticleUpdate(
            particles=(decoy_particle,),
            generated=2,
            matched=1,
            deduplicated=0,
            stochastic_only_mismatches=1,
            structural_mismatches=0,
        )

    monkeypatch.setattr(
        "champions_practice.recovery_soundness.condition_particles",
        fake_condition,
    )

    report = evaluate_true_world_conditioning_suite(object(), (case,))

    assert report.total == 1
    assert report.survived == 0
    assert report.false_exclusions == 1
    assert report.degraded_retentions == 0
    assert report.true_world_survival_rate == 0.0
    assert report.sound is False

    payload = conditioning_false_exclusion_payload(report.outcomes[0])
    assert payload["schema"] == "conditioning-true-world-regression-v1"
    assert payload["true_world_id"] == "true"
    assert payload["conditioning"]["posterior_world_ids"] == ["decoy"]
    assert payload["conditioning"]["stochastic_only_mismatches"] == 1


def test_conditioning_zero_match_retains_last_good_true_world(monkeypatch):
    true_particle = _particle("true")
    decoy_particle = _particle("decoy")
    case = TrueWorldConditioningCase(
        transition=_transition("conditioning-degraded"),
        particles=(true_particle, decoy_particle),
        true_world_id="true",
        rng_seeds=("sodium," + "4" * 64,),
        max_particles=2,
        resample_seed=8,
    )

    def fake_condition(*args, **kwargs):
        del args, kwargs
        return ParticleUpdate(
            particles=(),
            generated=2,
            matched=0,
            deduplicated=0,
            stochastic_only_mismatches=2,
            structural_mismatches=0,
        )

    monkeypatch.setattr(
        "champions_practice.recovery_soundness.condition_particles",
        fake_condition,
    )

    report = evaluate_true_world_conditioning_suite(object(), (case,))

    assert report.total == 1
    assert report.survived == 1
    assert report.false_exclusions == 0
    assert report.degraded_retentions == 1
    assert report.true_world_survival_rate == 1.0
    assert report.sound is True


def test_conditioning_report_empty_suite_is_vacuously_sound():
    report = ConditioningSoundnessReport(outcomes=())

    assert report.total == 0
    assert report.true_world_survival_rate == 1.0
    assert report.sound is True


def test_conditioning_case_requires_true_world_in_starting_particles():
    with pytest.raises(ValueError, match="does not contain"):
        TrueWorldConditioningCase(
            transition=_transition("missing-true-world"),
            particles=(_particle("decoy"),),
            true_world_id="true",
            rng_seeds=(None,),
            max_particles=1,
            resample_seed=1,
        )


class _FakeGenerationWorker:
    def __init__(self, result: dict[str, Any]):
        self.result = result
        self.calls: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []

    def branch_many(self, *, state, branches):
        self.calls.append((state, branches))
        return [self.result]


def test_generate_true_world_transition_preserves_exact_generation_context():
    worker = _FakeGenerationWorker(
        {
            "index": 0,
            "state": {"turn": 2, "truth": "child"},
            "view": {"turn": 2, "phase": "move"},
            "rng_draw_count": 3,
        }
    )
    state = {"turn": 1, "truth": "parent"}
    actual_seed = "sodium," + "a" * 64
    probe_seed = "sodium," + "b" * 64

    transition, child = generate_true_world_transition(
        worker,
        case_id="generated-1",
        source="generated-unit-test",
        state=state,
        side="p2",
        p1_choice="move tackle +1",
        p2_choice="move protect",
        actual_rng_seed=actual_seed,
        probe_rng_seed=probe_seed,
        previews={"p1": ["A"], "p2": ["B"]},
    )

    assert child == {"turn": 2, "truth": "child"}
    assert transition.pre_state is state
    assert transition.actual_public_view == {"turn": 2, "phase": "move"}
    assert transition.actual_rng_draw_count == 3
    assert transition.actual_rng_seed == actual_seed
    assert transition.probe_rng_seed == probe_seed
    assert worker.calls == [
        (
            state,
            [
                {
                    "p1_choice": "move tackle +1",
                    "p2_choice": "move protect",
                    "include_state": True,
                    "view_side": "p2",
                    "include_rng_draw_count": True,
                    "rng_seed": actual_seed,
                    "previews": {"p1": ["A"], "p2": ["B"]},
                }
            ],
        )
    ]


@pytest.mark.parametrize(
    "result,match",
    (
        ([], "invalid branch batch"),
        ([{"index": 1}], "invalid branch batch"),
        (
            [{"index": 0, "view": {}, "rng_draw_count": 0}],
            "omitted the exact child state",
        ),
        (
            [{"index": 0, "state": {"ok": True}, "rng_draw_count": 0}],
            "omitted the public observation",
        ),
        (
            [
                {
                    "index": 0,
                    "state": {"ok": True},
                    "view": {},
                    "rng_draw_count": True,
                }
            ],
            "valid PRNG draw count",
        ),
    ),
)
def test_true_world_generation_fails_closed_on_worker_contract_errors(
    result,
    match,
):
    worker = _FakeGenerationWorker(result[0] if result else {})
    if not result:
        worker.branch_many = lambda **kwargs: []

    with pytest.raises(RecoverySoundnessError, match=match):
        generate_true_world_transition(
            worker,
            case_id="bad",
            source="unit-test",
            state={"turn": 1},
            side="p2",
            p1_choice="move tackle +1",
            p2_choice="move protect",
            actual_rng_seed=None,
            probe_rng_seed=None,
        )


def test_transition_rejects_invalid_draw_count():
    with pytest.raises(ValueError, match="actual_rng_draw_count"):
        TrueWorldTransition(
            case_id="bad",
            source="unit-test",
            side="p2",
            pre_state={"turn": 1},
            p1_choice="move tackle +1",
            p2_choice="move protect",
            actual_public_view={},
            actual_rng_seed=None,
            probe_rng_seed=None,
            actual_rng_draw_count=True,
        )
