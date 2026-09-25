"""Real timeout cleanup smoke for one absolute hypothetical-search deadline."""

from threading import enumerate as enumerate_threads
from time import perf_counter, sleep

from champions_practice.belief_controller import BeliefDecisionEngine
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import (
    ShowdownSearchWorker,
    active_showdown_worker_pids,
)
from champions_practice.teams import SMOKE_TEAM

HUMAN_PREVIEW = "team 2615"
AI_PREVIEW = "team 4512"


def _executor_thread_count() -> int:
    return sum(
        1
        for thread in enumerate_threads()
        if thread.name.startswith("ThreadPoolExecutor")
    )


def main() -> None:
    with ShowdownSearchWorker() as setup_worker:
        state = setup_worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=SMOKE_TEAM,
            p2_team=SMOKE_TEAM,
            p1_preview=HUMAN_PREVIEW,
            p2_preview=AI_PREVIEW,
        )
        p1_choice = setup_worker.legal_choices(state=state, side="p1")[0]
        p2_choice = setup_worker.legal_choices(state=state, side="p2")[0]

    baseline_pids = active_showdown_worker_pids()
    baseline_threads = _executor_thread_count()
    branches = [
        {
            "p1_choice": p1_choice,
            "p2_choice": p2_choice,
        }
        for _ in range(10000)
    ]
    engine = BeliefDecisionEngine(
        ".",
        battle_format=CHAMPIONS_FORMAT,
        ai_team=SMOKE_TEAM,
        opponent_priors={},
    )

    started = perf_counter()
    result, timed_out = engine._run_until_deadline(
        lambda worker: worker.branch_many(
            state=state,
            branches=branches,
        ),
        deadline=started + 0.20,
        cleanup_reserve_seconds=0.05,
    )
    elapsed = perf_counter() - started

    if not timed_out or result is not None:
        raise SystemExit("ERROR: oversized real Node branch batch did not time out")
    if elapsed > 0.45:
        raise SystemExit(
            f"ERROR: absolute timeout returned too late: {elapsed:.3f}s"
        )

    cleanup_deadline = perf_counter() + 2.0
    while perf_counter() < cleanup_deadline:
        if (
            active_showdown_worker_pids() == baseline_pids
            and _executor_thread_count() <= baseline_threads
        ):
            break
        sleep(0.02)

    if active_showdown_worker_pids() != baseline_pids:
        raise SystemExit("ERROR: timed-out hypothetical Node worker was not reaped")
    if _executor_thread_count() > baseline_threads:
        raise SystemExit("ERROR: timed-out executor thread did not recover")

    print("Absolute deadline lifecycle smoke")
    print(f"Timeout return seconds: {elapsed:.3f}")
    print("Node worker process recovered: YES")
    print("Executor thread recovered: YES")
    print("RESULT: timed-out hypothetical work cleans up within bounded lifecycle")


if __name__ == "__main__":
    main()
