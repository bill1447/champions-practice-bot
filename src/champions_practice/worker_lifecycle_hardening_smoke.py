"""Adversarial lifecycle smoke for worker startup and transport hardening."""

from __future__ import annotations

import gc
import os
from pathlib import Path
from threading import Event, Thread, enumerate as enumerate_threads
from time import perf_counter, sleep

import champions_practice.belief_controller as belief_controller
import champions_practice.search_worker as search_worker_module
from champions_practice.belief_controller import (
    BeliefDecisionEngine,
    SealedBattleFacade,
    _BeliefBattleCoordinator,
)
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import (
    ShowdownSearchWorker,
    ShowdownWorkerTimeout,
    active_showdown_worker_pids,
)
from champions_practice.teams import SMOKE_TEAM


def _retained_worker_count() -> int:
    with search_worker_module._ACTIVE_SHOWDOWN_PROCESSES_LOCK:
        return len(search_worker_module._ACTIVE_SHOWDOWN_PROCESSES)


def _self_handle_count() -> int | None:
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        count = ctypes.c_ulong()
        if not kernel32.GetProcessHandleCount(
            kernel32.GetCurrentProcess(),
            ctypes.byref(count),
        ):
            return None
        return int(count.value)

    proc_fd = Path("/proc/self/fd")
    if proc_fd.is_dir():
        return len(tuple(proc_fd.iterdir()))
    return None


def _streams_closed(worker: ShowdownSearchWorker) -> bool:
    return all(
        stream is None or stream.closed
        for stream in (
            worker._process.stdin,
            worker._process.stdout,
            worker._process.stderr,
        )
    )


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


def _write_runtime_script(name: str, source: str) -> Path:
    root = Path(__file__).resolve().parents[2]
    runtime = root / ".runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    script = runtime / name
    script.write_text(source.strip() + "\n", encoding="utf-8")
    return script


def _transport_timeout_probe() -> float:
    root = Path(__file__).resolve().parents[2]
    script = _write_runtime_script(
        "transport-stall-worker.js",
        """
const readline = require("readline");
const rl = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
rl.on("line", () => {
  // Intentionally consume the request without ever emitting a response.
});
""",
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
            if error.phase != "response":
                raise SystemExit(
                    "ERROR: response stall was not classified as response timeout: "
                    f"{error.phase!r}"
                )
            if worker._transport_closed.is_set():
                raise SystemExit(
                    "ERROR: response-only timeout unnecessarily aborted transport"
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


def _blocked_stdin_probe() -> float:
    root = Path(__file__).resolve().parents[2]
    script = _write_runtime_script(
        "transport-no-read-worker.js",
        """
setInterval(() => {}, 1000);
""",
    )
    baseline = active_showdown_worker_pids()
    worker = ShowdownSearchWorker(
        root,
        request_timeout_seconds=0.12,
        worker_script=script,
    )
    try:
        started = perf_counter()
        try:
            worker.request(
                "session_choose",
                timeout_seconds=0.12,
                mutating=True,
                session_id="fake",
                p1_choice="",
                p2_choice="",
                padding="x" * 2_000_000,
            )
        except ShowdownWorkerTimeout as error:
            elapsed = perf_counter() - started
            if not error.mutating:
                raise SystemExit(
                    "ERROR: blocked mutating write lost unknown-outcome metadata"
                )
            if error.phase != "write":
                raise SystemExit(
                    "ERROR: blocked stdin was not classified as write timeout: "
                    f"{error.phase!r}"
                )
            if not worker._transport_closed.is_set():
                raise SystemExit(
                    "ERROR: blocked write timeout did not abort uncertain transport"
                )
        else:
            raise SystemExit("ERROR: worker with unread stdin did not time out")
    finally:
        worker.abort(timeout_seconds=0.10)
        script.unlink(missing_ok=True)

    _wait_for_process_baseline(baseline)
    if elapsed > 0.35:
        raise SystemExit(
            f"ERROR: blocked stdin exceeded absolute request deadline: {elapsed:.3f}s"
        )
    return elapsed


def _write_lock_deadline_probe() -> float:
    baseline = active_showdown_worker_pids()
    worker = ShowdownSearchWorker(".", request_timeout_seconds=1.0)
    entered = Event()
    release = Event()

    def hold_write_lock() -> None:
        with worker._write_lock:
            entered.set()
            release.wait(timeout=1.0)

    holder = Thread(target=hold_write_lock, daemon=True)
    holder.start()
    if not entered.wait(timeout=0.25):
        worker.abort(timeout_seconds=0.10)
        raise SystemExit("ERROR: lock-holder thread did not acquire write lock")

    try:
        started = perf_counter()
        try:
            worker.request("ping", timeout_seconds=0.08)
        except ShowdownWorkerTimeout as error:
            elapsed = perf_counter() - started
            if error.phase != "write-lock":
                raise SystemExit(
                    "ERROR: write-lock stall used wrong timeout phase: "
                    f"{error.phase!r}"
                )
        else:
            raise SystemExit("ERROR: request escaped a blocked write-lock deadline")
    finally:
        release.set()
        holder.join(timeout=0.25)

    try:
        if not worker.ping():
            raise SystemExit("ERROR: write-lock timeout corrupted healthy transport")
    finally:
        worker.close()

    _wait_for_process_baseline(baseline)
    if elapsed > 0.25:
        raise SystemExit(
            f"ERROR: write-lock deadline returned too late: {elapsed:.3f}s"
        )
    return elapsed


def _abort_unblocks_waiter_probe() -> float:
    root = Path(__file__).resolve().parents[2]
    script = _write_runtime_script(
        "transport-abort-waiter-worker.js",
        """
const readline = require("readline");
const rl = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
rl.on("line", () => {
  // Consume input but never answer; abort must wake the pending request.
});
""",
    )
    baseline = active_showdown_worker_pids()
    worker = ShowdownSearchWorker(
        root,
        request_timeout_seconds=5.0,
        worker_script=script,
    )
    errors: list[BaseException] = []
    done = Event()

    def blocked_request() -> None:
        try:
            worker.request(
                "session_choose",
                timeout_seconds=5.0,
                mutating=True,
                session_id="fake",
                p1_choice="",
                p2_choice="",
            )
        except BaseException as error:
            errors.append(error)
        finally:
            done.set()

    request_thread = Thread(target=blocked_request, daemon=True)
    request_thread.start()

    pending_deadline = perf_counter() + 0.50
    while perf_counter() < pending_deadline:
        with worker._pending_lock:
            if worker._pending:
                break
        sleep(0.01)
    else:
        worker.abort(timeout_seconds=0.10)
        script.unlink(missing_ok=True)
        raise SystemExit("ERROR: abort probe never reached pending response wait")

    started = perf_counter()
    worker.abort(timeout_seconds=0.10)
    if not done.wait(timeout=0.30):
        script.unlink(missing_ok=True)
        raise SystemExit("ERROR: abort did not wake pending request")
    elapsed = perf_counter() - started
    request_thread.join(timeout=0.10)
    if not worker._cleanup_done.wait(timeout=0.50):
        script.unlink(missing_ok=True)
        raise SystemExit("ERROR: abort transport cleanup did not finish")
    if not _streams_closed(worker):
        script.unlink(missing_ok=True)
        raise SystemExit("ERROR: abort cleanup left pipe streams open")
    script.unlink(missing_ok=True)

    if len(errors) != 1 or not isinstance(errors[0], ShowdownWorkerTimeout):
        raise SystemExit(
            "ERROR: aborted mutating waiter did not receive timeout semantics: "
            f"{errors!r}"
        )
    error = errors[0]
    if not error.mutating or error.phase != "transport-abort":
        raise SystemExit(
            "ERROR: aborted mutating waiter lost fail-closed metadata: "
            f"mutating={error.mutating}, phase={error.phase!r}"
        )

    _wait_for_process_baseline(baseline)
    if elapsed > 0.30:
        raise SystemExit(
            f"ERROR: abort waiter wakeup returned too late: {elapsed:.3f}s"
        )
    return elapsed


def _close_blocked_stdin_probe() -> float:
    root = Path(__file__).resolve().parents[2]
    script = _write_runtime_script(
        "transport-close-blocked-worker.js",
        """
setInterval(() => {}, 1000);
""",
    )
    baseline = active_showdown_worker_pids()
    worker = ShowdownSearchWorker(
        root,
        request_timeout_seconds=5.0,
        worker_script=script,
    )
    errors: list[BaseException] = []
    done = Event()

    def blocked_write() -> None:
        try:
            worker.request(
                "session_choose",
                timeout_seconds=5.0,
                mutating=True,
                session_id="fake",
                p1_choice="",
                p2_choice="",
                padding="x" * 2_000_000,
            )
        except BaseException as error:
            errors.append(error)
        finally:
            done.set()

    request_thread = Thread(target=blocked_write, daemon=True)
    request_thread.start()

    pending_deadline = perf_counter() + 0.50
    while perf_counter() < pending_deadline:
        with worker._pending_lock:
            pending = bool(worker._pending)
        if pending and worker._write_lock.locked():
            break
        sleep(0.01)
    else:
        worker.abort(timeout_seconds=0.10)
        script.unlink(missing_ok=True)
        raise SystemExit("ERROR: close probe never reached blocked write")

    sleep(0.05)
    started = perf_counter()
    worker.close()
    elapsed = perf_counter() - started

    if not done.wait(timeout=0.30):
        script.unlink(missing_ok=True)
        raise SystemExit("ERROR: close did not unblock blocked stdin writer")
    request_thread.join(timeout=0.10)
    if not worker._cleanup_done.wait(timeout=0.50):
        script.unlink(missing_ok=True)
        raise SystemExit("ERROR: blocked writer transport cleanup did not finish")
    if not _streams_closed(worker):
        script.unlink(missing_ok=True)
        raise SystemExit("ERROR: blocked writer cleanup left pipe streams open")
    script.unlink(missing_ok=True)

    if len(errors) != 1 or not isinstance(errors[0], ShowdownWorkerTimeout):
        raise SystemExit(
            "ERROR: close did not preserve mutating fail-closed semantics: "
            f"{errors!r}"
        )
    if not errors[0].mutating:
        raise SystemExit("ERROR: close lost mutating unknown-outcome metadata")

    _wait_for_process_baseline(baseline)
    if elapsed > 1.00:
        raise SystemExit(
            f"ERROR: close blocked on unread stdin: {elapsed:.3f}s"
        )
    return elapsed


def _resource_lifetime_probe(iterations: int = 12) -> tuple[int | None, int | None]:
    baseline_registry = _retained_worker_count()
    baseline_handles = _self_handle_count()

    for index in range(iterations):
        worker = ShowdownSearchWorker(".", request_timeout_seconds=1.0)
        if not worker.ping():
            worker.close()
            raise SystemExit(
                f"ERROR: resource probe worker {index} did not answer ping"
            )

        worker.close()
        if not worker._cleanup_done.wait(timeout=1.0):
            raise SystemExit(
                f"ERROR: resource probe worker {index} cleanup did not finish"
            )
        if worker._process.poll() is None:
            raise SystemExit(
                f"ERROR: resource probe worker {index} child is still alive"
            )
        if not _streams_closed(worker):
            raise SystemExit(
                f"ERROR: resource probe worker {index} retained an open pipe"
            )

        del worker
        gc.collect()

    final_registry = _retained_worker_count()
    if final_registry != baseline_registry:
        raise SystemExit(
            "ERROR: normally closed workers remain strongly registered: "
            f"baseline={baseline_registry}, final={final_registry}"
        )

    final_handles = _self_handle_count()
    if (
        baseline_handles is not None
        and final_handles is not None
        and final_handles > baseline_handles + 6
    ):
        raise SystemExit(
            "ERROR: repeated normal worker close leaked process handles/fds: "
            f"before={baseline_handles}, after={final_handles}"
        )

    return baseline_handles, final_handles


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
    blocked_write_elapsed = _blocked_stdin_probe()
    lock_elapsed = _write_lock_deadline_probe()
    abort_elapsed = _abort_unblocks_waiter_probe()
    close_elapsed = _close_blocked_stdin_probe()
    handle_before, handle_after = _resource_lifetime_probe()
    _invalid_facade_config_probe()
    _close_failure_probe()

    print("Worker lifecycle hardening")
    print(f"Injected slow startup returned in: {startup_elapsed:.3f}s")
    print(f"Stalled response returned in: {transport_elapsed:.3f}s")
    print(f"Blocked stdin write returned in: {blocked_write_elapsed:.3f}s")
    print(f"Blocked write lock returned in: {lock_elapsed:.3f}s")
    print(f"Abort waiter wakeup returned in: {abort_elapsed:.3f}s")
    print(f"Close with blocked stdin returned in: {close_elapsed:.3f}s")
    print(
        "Repeated close handles/fds: "
        f"{handle_before!r} -> {handle_after!r}"
    )
    print("Normally closed workers retained in registry: NO")
    print("Normally closed worker pipe streams retained: NO")
    print("Invalid facade config spawned worker: NO")
    print("Session-close failure leaked worker: NO")
    print(
        "RESULT: worker timing, process ownership, and transport resources "
        "are bounded and released"
    )


if __name__ == "__main__":
    main()
