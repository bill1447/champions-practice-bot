"""Adversarial lifecycle smoke for PR #106 worker hardening."""

from __future__ import annotations

from pathlib import Path
from threading import enumerate as enumerate_threads
from time import perf_counter, sleep

import champions_practice.belief_controller as belief_controller
from champions_practice.belief_controller import (
    BeliefDecisionEngine,
    SealedBattleFacade,
    _BeliefBattleCoordinator,
)
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import (
    HypotheticalSearchWorker,
    ShowdownSearchWorker,
    ShowdownWorkerTimeout,
    active_showdown_worker_pids,
)
from champions_practice.teams import SMOKE_TEAM


def _executor_thread_count() -> int:
    return sum(
        1
        for thread in enumerate_threads()
        if thread.name.startswith("ThreadPoolExecutor")
    )


def _wait_for_process_baseline(
    baseline: tuple[int, ...],
    *,
    timeout_seconds: float = 2.0,
) -> None:
    deadline = perf_counter() + timeout_seconds
    while perf_counter() < deadline:
        if active_showdown_worker_pids() == baseline:
            return
        sleep(0.02)
    raise SystemExit(
        "ERROR: worker process count did not return to baseline: "
        f"expected={baseline}, actual={active_showdown_worker_pids()}"
    )


def _startup_deadline_probe() -> float:
    original = belief_controller.HypotheticalSearchWorker
    baseline_pids = active_showdown_worker_pids()
    baseline_threads = _executor_thread_count()

    class SlowStartupWorker:
        def __init__(self, project_root, **_kwargs):
            sleep(0.30)
            self.inner = original(
                project_root,
                request_timeout_seconds=1.0,
            )

        def abort(self, *, timeout_seconds=0.25):
            self.inner.abort(timeout_seconds=timeout_seconds)

    belief_controller.HypotheticalSearchWorker = SlowStartupWorker
    try:
        engine = BeliefDecisionEngine(
            ".",
            battle_format=CHAMPIONS_FORMAT,
            ai_team=SMOKE_TEAM,
            opponent_priors={},
        )
        started = perf_counter()
        result, timed_out = engine._run_until_deadline(
            lambda _worker: "unexpected",
            deadline=started + 0.08,
            cleanup_reserve_seconds=0.02,
        )
        elapsed = perf_counter() - started
    finally:
        belief_controller.HypotheticalSearchWorker = original

    if not timed_out or result is not None:
        raise SystemExit("ERROR: slow worker construction escaped startup deadline")
    if elapsed > 0.18:
        raise SystemExit(
            f"ERROR: startup deadline returned too late: {elapsed:.3f}s"
        )

    deadline = perf_counter() + 1.0
    while perf_counter() < deadline:
        if (
            active_showdown_worker_pids() == baseline_pids
            and _executor_thread_count() <= baseline_threads
        ):
            break
        sleep(0.02)
    if active_showdown_worker_pids() != baseline_pids:
        raise SystemExit("ERROR: delayed worker construction leaked a Node process")
    if _executor_thread_count() > baseline_threads:
        raise SystemExit("ERROR: delayed startup executor thread did not recover")
    return elapsed


def _transport_timeout_probe() -> float:
    root = Path(__file__).resolve().parents[2]
    runtime = root / ".runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    script = runtime / "transport-stall-worker.js"
    script.write_text(
        """
const readline = require("readline");
const rl = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
rl.on("line", () => {
  // Intentionally consume the request without ever emitting a response.
});
""".strip()
        + "\n",
        encoding="utf-8",
    )

    baseline = active_showdown_worker_pids()
    worker = ShowdownSearchWorker(
        root,
        request_timeout_seconds=0.10,
        worker_script=script,
    )
    try:
        started = perf_counter()
        try:
            worker.request(
                "session_choose",
                mutating=True,
                session_id="fake",
                p1_choice="",
                p2_choice="",
            )
        except ShowdownWorkerTimeout as error:
            elapsed = perf_counter() - started
            if not error.mutating:
                raise SystemExit(
                    "ERROR: mutating transport timeout lost unknown-outcome metadata"
                )
        else:
            raise SystemExit("ERROR: stalled worker request did not time out")
    finally:
        worker.abort(timeout_seconds=0.10)
        script.unlink(missing_ok=True)

    _wait_for_process_baseline(baseline)
    if elapsed > 0.30:
        raise SystemExit(
            f"ERROR: stalled transport exceeded bounded timeout: {elapsed:.3f}s"
        )
    return elapsed


def _invalid_facade_config_probe() -> None:
    baseline = active_showdown_worker_pids()
    try:
        SealedBattleFacade(
            battle_format=CHAMPIONS_FORMAT,
            ai_team=SMOKE_TEAM,
            ai_preview_choice="team 1234",
            opponent_priors={},
            max_particles=0,
        )
    except ValueError:
        pass
    else:
        raise SystemExit("ERROR: invalid facade configuration unexpectedly succeeded")
    if active_showdown_worker_pids() != baseline:
        raise SystemExit("ERROR: invalid facade configuration spawned a worker")


def _close_failure_probe() -> None:
    baseline = active_showdown_worker_pids()
    worker = ShowdownSearchWorker(".", request_timeout_seconds=1.0)
    coordinator = _BeliefBattleCoordinator(
        worker,
        battle_format=CHAMPIONS_FORMAT,
        ai_team=SMOKE_TEAM,
        opponent_priors={},
    )
    coordinator._session_id = "owned-session"
    coordinator._turn_state = belief_controller.SealedTurnState.IDLE

    def fail_close_session(_session_id):
        raise RuntimeError("injected session-close failure")

    worker.close_session = fail_close_session
    try:
        coordinator.close()
    except RuntimeError as error:
        if "injected session-close failure" not in str(error):
            raise
    else:
        raise SystemExit("ERROR: injected session-close failure did not propagate")

    _wait_for_process_baseline(baseline)


def main() -> None:
    # Warm the pinned runtime cache so the startup probe isolates worker construction.
    with ShowdownSearchWorker() as worker:
        if not worker.ping():
            raise SystemExit("ERROR: baseline Showdown worker did not answer ping")

    startup_elapsed = _startup_deadline_probe()
    transport_elapsed = _transport_timeout_probe()
    _invalid_facade_config_probe()
    _close_failure_probe()

    print("Worker lifecycle hardening")
    print(f"Injected slow startup returned in: {startup_elapsed:.3f}s")
    print(f"Stalled live transport returned in: {transport_elapsed:.3f}s")
    print("Invalid facade config spawned worker: NO")
    print("Session-close failure leaked worker: NO")
    print("RESULT: startup, transport, and worker ownership are bounded")


if __name__ == "__main__":
    main()
