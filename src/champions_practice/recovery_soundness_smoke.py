"""Pinned-Showdown smoke for offline true-world survival accounting."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import public_observation_signature
from champions_practice.reachability import ReachabilityStatus
from champions_practice.recovery_soundness import (
    evaluate_true_world_suite,
    generate_true_world_transition,
    write_false_exclusion_regressions,
)
from champions_practice.search_worker import HypotheticalSearchWorker
from champions_practice.teams import SMOKE_TEAM


P1_PREVIEW = "team 1256"
P2_PREVIEW = "team 4512"
P1_CHOICE = "move psychic +1, move protect"
P2_CHOICE = "move expandingforce +1, move protect"
INITIAL_SEED = "sodium,87654321000000020000000300000004"
ACTUAL_SEED = "sodium," + "1" * 64
ALT_SEEDS = tuple(
    "sodium," + digit * 64
    for digit in "23456789abcdef"
)
SEQUENCE_SEEDS = (
    "sodium," + "a" * 64,
    "sodium," + "b" * 64,
    "sodium," + "c" * 64,
)


def _find_mismatch_seed(
    worker: HypotheticalSearchWorker,
    *,
    state: dict,
    expected_view: dict,
) -> str:
    branches = worker.branch_many(
        state=state,
        branches=[
            {
                "p1_choice": P1_CHOICE,
                "p2_choice": P2_CHOICE,
                "rng_seed": seed,
                "include_state": True,
                "view_side": "p2",
            }
            for seed in ALT_SEEDS
        ],
    )
    wanted = public_observation_signature(expected_view)
    for seed, branch in zip(ALT_SEEDS, branches, strict=True):
        view = branch.get("view")
        if (
            isinstance(view, dict)
            and public_observation_signature(view) != wanted
        ):
            return seed
    raise SystemExit(
        "ERROR: true-world soundness smoke found no alternate stochastic outcome"
    )


def _first_legal_choice(
    worker: HypotheticalSearchWorker,
    *,
    state: dict,
    side: str,
) -> str | None:
    choices = worker.legal_choices(state=state, side=side)
    if not choices:
        return None
    return choices[0]


def main() -> None:
    runtime_dir = Path(".runtime") / "recovery-hard-cases"

    with HypotheticalSearchWorker() as worker:
        state = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=SMOKE_TEAM,
            p2_team=SMOKE_TEAM,
            p1_preview=P1_PREVIEW,
            p2_preview=P2_PREVIEW,
            seed=INITIAL_SEED,
        )

        first, child = generate_true_world_transition(
            worker,
            case_id="smoke-turn-1-witness",
            source="pinned-showdown-fixed-smoke",
            state=state,
            side="p2",
            p1_choice=P1_CHOICE,
            p2_choice=P2_CHOICE,
            actual_rng_seed=ACTUAL_SEED,
            probe_rng_seed=ACTUAL_SEED,
        )
        miss_seed = _find_mismatch_seed(
            worker,
            state=state,
            expected_view=first.actual_public_view,
        )
        sampled_miss = replace(
            first,
            case_id="smoke-turn-1-sampled-miss",
            probe_rng_seed=miss_seed,
        )

        transitions = [first, sampled_miss]
        current = child
        for index, seed in enumerate(SEQUENCE_SEEDS, start=2):
            p1_choice = _first_legal_choice(
                worker,
                state=current,
                side="p1",
            )
            p2_choice = _first_legal_choice(
                worker,
                state=current,
                side="p2",
            )
            if p1_choice is None or p2_choice is None:
                break
            transition, current = generate_true_world_transition(
                worker,
                case_id=f"smoke-turn-{index}-witness",
                source="pinned-showdown-fixed-smoke",
                state=current,
                side="p2",
                p1_choice=p1_choice,
                p2_choice=p2_choice,
                actual_rng_seed=seed,
                probe_rng_seed=seed,
            )
            transitions.append(transition)

        report = evaluate_true_world_suite(worker, transitions)

    if report.false_exclusions:
        paths = write_false_exclusion_regressions(
            report,
            output_dir=runtime_dir,
        )
        raise SystemExit(
            "ERROR: known-real hidden world was exhaustively disproved; "
            f"saved {len(paths)} hard case(s) under {runtime_dir}"
        )

    first_outcome = report.outcomes[0]
    miss_outcome = report.outcomes[1]
    if first_outcome.result.status is not ReachabilityStatus.WITNESSED:
        raise SystemExit(
            "ERROR: exact true RNG continuation was not witnessed: "
            f"{first_outcome.result}"
        )
    if miss_outcome.result.status is not ReachabilityStatus.UNRESOLVED:
        raise SystemExit(
            "ERROR: sampled stochastic miss did not remain unresolved: "
            f"{miss_outcome.result}"
        )
    if not miss_outcome.survived:
        raise SystemExit(
            "ERROR: sampled stochastic miss excluded the known true world"
        )

    print("Offline true-world recovery soundness harness")
    print(f"Transitions evaluated: {report.total}")
    print(f"Witnessed:             {report.witnessed}")
    print(f"Unresolved:            {report.unresolved}")
    print(f"Unsupported:           {report.unsupported}")
    print(f"False exclusions:      {report.false_exclusions}")
    print(
        "True-world survival:  "
        f"{report.true_world_survival_rate:.6f}"
    )
    print(f"Sampled miss seed:     {miss_seed}")
    print("RESULT: known true world survived every tested boundary")


if __name__ == "__main__":
    main()
