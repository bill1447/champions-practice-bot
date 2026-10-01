"""Persistent Python bridge to the exact local Showdown simulator."""

from __future__ import annotations

import hashlib
import json
import queue
import re
import subprocess
from collections import deque
from pathlib import Path
from threading import Event, Lock, Thread, current_thread
from time import perf_counter
from typing import Any


_VERIFIED_SHOWDOWN_ROOTS: dict[Path, str] = {}
_ACTIVE_SHOWDOWN_PROCESSES: dict[int, subprocess.Popen[str]] = {}
_ACTIVE_SHOWDOWN_PROCESSES_LOCK = Lock()
_BUILD_STAMP_NAME = "showdown-build.json"


def _register_showdown_process(process: subprocess.Popen[str]) -> None:
    with _ACTIVE_SHOWDOWN_PROCESSES_LOCK:
        _ACTIVE_SHOWDOWN_PROCESSES[process.pid] = process


def _unregister_showdown_process(process: subprocess.Popen[str]) -> None:
    with _ACTIVE_SHOWDOWN_PROCESSES_LOCK:
        current = _ACTIVE_SHOWDOWN_PROCESSES.get(process.pid)
        if current is process:
            _ACTIVE_SHOWDOWN_PROCESSES.pop(process.pid, None)


class ShowdownRequestError(RuntimeError):
    """The worker completed a request but Showdown rejected it."""

    def __init__(
        self,
        op: str,
        detail: str,
        *,
        mutating: bool = False,
        safe_retry: bool = False,
    ) -> None:
        self.op = op
        self.detail = detail
        self.mutating = mutating
        self.safe_retry = safe_retry
        self.choice_rejected = (
            "[Invalid choice]" in detail
            or "[Unavailable choice]" in detail
        )
        super().__init__(f"Showdown worker {op!r} failed: {detail}")


class ShowdownWorkerTimeout(TimeoutError):
    """A bounded worker operation exceeded its startup or transport deadline."""

    def __init__(
        self,
        op: str,
        *,
        mutating: bool = False,
        phase: str = "transport",
    ) -> None:
        self.op = op
        self.mutating = mutating
        self.phase = phase
        super().__init__(f"Showdown worker {phase} timed out during {op!r}")


def _remaining_timeout(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    remaining = deadline - perf_counter()
    if remaining <= 0:
        raise ShowdownWorkerTimeout("startup", phase="startup")
    return remaining


def _showdown_source_revision(
    root: Path,
    *,
    deadline: float | None = None,
) -> tuple[Path, str]:
    pin_file = root / "showdown-version.txt"
    showdown_root = root / "external" / "pokemon-showdown"

    if not pin_file.is_file():
        raise RuntimeError(f"Pokemon Showdown pin file is missing: {pin_file}")
    expected = pin_file.read_text(encoding="utf-8").strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", expected) is None:
        raise RuntimeError(
            "Pokemon Showdown pin must be a full 40-character git SHA"
        )

    try:
        actual_result = subprocess.run(
            ["git", "-C", str(showdown_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_remaining_timeout(deadline),
        )
    except subprocess.TimeoutExpired as error:
        raise ShowdownWorkerTimeout("git-rev-parse", phase="startup") from error
    except OSError as error:
        raise RuntimeError(
            "Git is required to verify the pinned Pokemon Showdown runtime"
        ) from error

    if actual_result.returncode != 0:
        detail = actual_result.stderr.strip() or actual_result.stdout.strip()
        raise RuntimeError(
            "Pokemon Showdown checkout is unavailable or not a git repository: "
            f"{detail}"
        )
    actual = actual_result.stdout.strip().lower()
    if actual != expected:
        raise RuntimeError(
            "Pokemon Showdown revision mismatch: "
            f"expected {expected}, found {actual}. "
            "Run update-local.ps1 -UpdateShowdown."
        )

    for args in (
        ["git", "-C", str(showdown_root), "diff", "--quiet", "HEAD", "--"],
        ["git", "-C", str(showdown_root), "diff", "--cached", "--quiet", "HEAD", "--"],
    ):
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                check=False,
                timeout=_remaining_timeout(deadline),
            )
        except subprocess.TimeoutExpired as error:
            raise ShowdownWorkerTimeout("git-diff", phase="startup") from error
        if result.returncode == 1:
            raise RuntimeError(
                "Pokemon Showdown checkout has tracked local modifications. "
                "Clean or stash them before running the practice bot."
            )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(
                f"Unable to verify Pokemon Showdown checkout cleanliness: {detail}"
            )
    return showdown_root, actual


def _showdown_dist_digest(
    showdown_root: Path,
    *,
    deadline: float | None = None,
) -> str:
    dist_root = showdown_root / "dist"
    files = sorted(
        path
        for path in dist_root.rglob("*")
        if path.is_file()
    )
    if not files:
        raise RuntimeError(
            "Built Pokemon Showdown dist tree is missing. "
            "Run setup.ps1 or update-local.ps1 -UpdateShowdown first."
        )

    digest = hashlib.sha256()
    for path in files:
        _remaining_timeout(deadline)
        relative = path.relative_to(dist_root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def write_showdown_build_stamp(
    project_root: str | Path | None = None,
) -> dict[str, str]:
    """Record the exact ignored/generated Showdown dist tree built from the pin."""
    if project_root is None:
        project_root = Path(__file__).resolve().parents[2]
    root = Path(project_root).resolve()
    showdown_root, revision = _showdown_source_revision(root)
    stamp = {
        "source_sha": revision,
        "dist_sha256": _showdown_dist_digest(showdown_root),
    }
    runtime_root = root / ".runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    stamp_path = runtime_root / _BUILD_STAMP_NAME
    stamp_path.write_text(
        json.dumps(stamp, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _VERIFIED_SHOWDOWN_ROOTS.pop(root, None)
    return stamp


def verify_showdown_checkout(
    project_root: str | Path | None = None,
    *,
    deadline: float | None = None,
) -> str:
    """Fail fast unless source and built Showdown runtime match the pinned build."""
    if project_root is None:
        project_root = Path(__file__).resolve().parents[2]
    root = Path(project_root).resolve()
    cached = _VERIFIED_SHOWDOWN_ROOTS.get(root)
    if cached is not None:
        return cached

    showdown_root, actual = _showdown_source_revision(root, deadline=deadline)
    stamp_path = root / ".runtime" / _BUILD_STAMP_NAME
    if not stamp_path.is_file():
        raise RuntimeError(
            "Pokemon Showdown build provenance is missing. "
            "Run setup.ps1 or update-local.ps1 -UpdateShowdown."
        )
    try:
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise RuntimeError("Pokemon Showdown build provenance is invalid") from error

    if stamp.get("source_sha") != actual:
        raise RuntimeError(
            "Pokemon Showdown build provenance revision mismatch: "
            f"source is {actual}, build stamp is {stamp.get('source_sha')!r}. "
            "Rebuild the pinned runtime."
        )
    built_digest = _showdown_dist_digest(showdown_root, deadline=deadline)
    if stamp.get("dist_sha256") != built_digest:
        raise RuntimeError(
            "Pokemon Showdown built runtime hash mismatch. "
            "Rebuild the pinned runtime before running the practice bot."
        )

    _VERIFIED_SHOWDOWN_ROOTS[root] = actual
    return actual


def active_showdown_worker_pids() -> tuple[int, ...]:
    """Return currently live Node worker PIDs, pruning stale registry entries."""
    with _ACTIVE_SHOWDOWN_PROCESSES_LOCK:
        finished = [
            pid
            for pid, process in _ACTIVE_SHOWDOWN_PROCESSES.items()
            if process.poll() is not None
        ]
        for pid in finished:
            _ACTIVE_SHOWDOWN_PROCESSES.pop(pid, None)
        return tuple(sorted(_ACTIVE_SHOWDOWN_PROCESSES))


class HypotheticalSearchWorker:
    """Restricted worker surface for exact hypothetical states only.

    This wrapper intentionally exposes no persistent-session operations. Decision code can
    create, inspect, validate, and branch hypothetical states, but cannot open or inspect a
    live battle session through this capability.
    """

    def __init__(
        self,
        project_root: str | Path | None = None,
        *,
        startup_deadline: float | None = None,
        request_timeout_seconds: float = 30.0,
    ):
        self.__worker = ShowdownSearchWorker(
            project_root,
            startup_deadline=startup_deadline,
            request_timeout_seconds=request_timeout_seconds,
        )

    def create_state(
        self,
        *,
        battle_format: str,
        p1_team: str,
        p2_team: str,
        p1_preview: str | None = None,
        p2_preview: str | None = None,
        p1_name: str = "Search P1",
        p2_name: str = "Search P2",
        seed: str | None = None,
    ) -> dict[str, Any]:
        return self.__worker.create_state(
            battle_format=battle_format,
            p1_team=p1_team,
            p2_team=p2_team,
            p1_preview=p1_preview,
            p2_preview=p2_preview,
            p1_name=p1_name,
            p2_name=p2_name,
            seed=seed,
        )

    def branch_many(
        self,
        *,
        state: dict[str, Any],
        branches: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return self.__worker.branch_many(state=state, branches=branches)

    def state_view(
        self,
        *,
        state: dict[str, Any],
        side: str,
        previews: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        return self.__worker.state_view(
            state=state,
            side=side,
            previews=previews,
        )

    def legal_choices(
        self,
        *,
        state: dict[str, Any],
        side: str,
    ) -> list[str]:
        return self.__worker.legal_choices(state=state, side=side)

    def validate_choices(
        self,
        *,
        state: dict[str, Any],
        side: str,
        candidates: list[str],
    ) -> list[str]:
        return self.__worker.validate_choices(
            state=state,
            side=side,
            candidates=candidates,
        )

    def abort(self, *, timeout_seconds: float = 0.25) -> None:
        self.__worker.abort(timeout_seconds=timeout_seconds)

    def close(self) -> None:
        self.__worker.close()

    def __enter__(self) -> "HypotheticalSearchWorker":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class ShowdownSearchWorker:
    """Send bounded JSONL requests to a persistent Node.js Showdown worker."""

    def __init__(
        self,
        project_root: str | Path | None = None,
        *,
        startup_deadline: float | None = None,
        startup_timeout_seconds: float = 10.0,
        request_timeout_seconds: float = 30.0,
        worker_script: str | Path | None = None,
    ):
        if project_root is None:
            project_root = Path(__file__).resolve().parents[2]
        if startup_timeout_seconds <= 0:
            raise ValueError("startup_timeout_seconds must be positive")
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")

        if startup_deadline is None:
            startup_deadline = perf_counter() + startup_timeout_seconds

        self.project_root = Path(project_root)
        self.showdown_revision = verify_showdown_checkout(
            self.project_root,
            deadline=startup_deadline,
        )
        self.script = (
            Path(worker_script)
            if worker_script is not None
            else self.project_root / "tools" / "showdown-search-worker.js"
        )
        self.showdown_battle = (
            self.project_root
            / "external"
            / "pokemon-showdown"
            / "dist"
            / "sim"
            / "battle.js"
        )

        if not self.script.is_file():
            raise RuntimeError(f"Showdown search worker script is missing: {self.script}")
        if not self.showdown_battle.is_file():
            raise RuntimeError(
                "Built Pokemon Showdown simulator is missing. "
                "Run setup.ps1 or update-local.ps1 -UpdateShowdown first."
            )
        _remaining_timeout(startup_deadline)

        self._next_id = 1
        self._request_timeout_seconds = request_timeout_seconds
        self._pending: dict[int, queue.Queue[dict[str, Any] | None]] = {}
        self._pending_lock = Lock()
        self._write_lock = Lock()
        self._transport_closed = Event()
        self._stderr_lines: deque[str] = deque(maxlen=100)
        self._stderr_lock = Lock()
        self._writer_threads: set[Thread] = set()
        self._writer_threads_lock = Lock()
        self._cleanup_started = Event()
        self._cleanup_done = Event()
        self._cleanup_lock = Lock()
        self._cleanup_thread: Thread | None = None

        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                ["node", str(self.script)],
                cwd=self.project_root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
            self._process = process
            _register_showdown_process(process)
            _remaining_timeout(startup_deadline)

            self._stdout_thread = Thread(
                target=self._drain_stdout,
                name=f"showdown-stdout-{process.pid}",
                daemon=True,
            )
            self._stderr_thread = Thread(
                target=self._drain_stderr,
                name=f"showdown-stderr-{process.pid}",
                daemon=True,
            )
            self._stdout_thread.start()
            self._stderr_thread.start()
        except Exception:
            if process is not None:
                self._process = process
                self.abort(timeout_seconds=0.25)
                self._cleanup_done.wait(timeout=0.25)
            raise

    def _stderr_text(self) -> str:
        with self._stderr_lock:
            return "\n".join(self._stderr_lines)

    def _drain_stderr(self) -> None:
        stream = self._process.stderr
        if stream is None:
            return
        for line in stream:
            with self._stderr_lock:
                self._stderr_lines.append(line.rstrip())

    def _signal_transport_closed(self) -> None:
        self._transport_closed.set()
        with self._pending_lock:
            waiters = tuple(self._pending.values())
        for waiter in waiters:
            try:
                waiter.put_nowait(None)
            except queue.Full:
                pass

    def _transport_io_threads(self) -> tuple[Thread, ...]:
        with self._writer_threads_lock:
            writers = tuple(self._writer_threads)
        readers = tuple(
            thread
            for thread in (
                getattr(self, "_stdout_thread", None),
                getattr(self, "_stderr_thread", None),
            )
            if thread is not None
        )
        return readers + writers

    def _close_transport_streams(self) -> None:
        for stream in (
            self._process.stdin,
            self._process.stdout,
            self._process.stderr,
        ):
            if stream is None or stream.closed:
                continue
            try:
                stream.close()
            except (OSError, ValueError):
                pass

    def _finalize_transport(self) -> None:
        process = self._process
        try:
            if process.poll() is None:
                try:
                    process.wait(timeout=0.25)
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                    except OSError:
                        pass
                    # This wait runs only in the daemon finalizer. close()/abort()
                    # remain bounded while cleanup retains ownership until the OS
                    # actually reaps the child and its pipes can be closed safely.
                    process.wait()

            # Wait until the request that owned the write lock has released it.
            # After transport_closed is set, no later request may start another
            # writer, so this establishes a stable set of owned I/O threads.
            with self._write_lock:
                pass

            while True:
                threads = tuple(
                    thread
                    for thread in self._transport_io_threads()
                    if thread is not current_thread() and thread.is_alive()
                )
                if not threads:
                    break
                for thread in threads:
                    thread.join(timeout=0.05)

            self._close_transport_streams()
            _unregister_showdown_process(process)
        finally:
            self._cleanup_done.set()

    def _schedule_transport_cleanup(self) -> None:
        with self._cleanup_lock:
            if self._cleanup_started.is_set():
                return
            self._cleanup_started.set()
            thread = Thread(
                target=self._finalize_transport,
                name=f"showdown-cleanup-{self._process.pid}",
                daemon=True,
            )
            self._cleanup_thread = thread
            thread.start()

    def _drain_stdout(self) -> None:
        stream = self._process.stdout
        if stream is None:
            self._signal_transport_closed()
            return
        try:
            for line in stream:
                try:
                    response = json.loads(line)
                except json.JSONDecodeError:
                    continue
                request_id = response.get("id")
                if not isinstance(request_id, int):
                    continue
                with self._pending_lock:
                    waiter = self._pending.get(request_id)
                if waiter is not None:
                    try:
                        waiter.put_nowait(response)
                    except queue.Full:
                        # An abort/close may already have woken this request.
                        pass
        finally:
            self._signal_transport_closed()
            self._schedule_transport_cleanup()

    def _raise_transport_closed(
        self,
        op: str,
        *,
        mutating: bool,
    ) -> None:
        if mutating:
            raise ShowdownWorkerTimeout(
                op,
                mutating=True,
                phase="transport-abort",
            )
        raise RuntimeError(
            "Showdown search worker transport is closed. "
            f"stderr={self._stderr_text().strip()!r}"
        )

    def request(
        self,
        op: str,
        *,
        timeout_seconds: float | None = None,
        mutating: bool = False,
        **payload: Any,
    ) -> dict[str, Any]:
        if self._process.poll() is not None:
            raise RuntimeError(
                "Showdown search worker exited unexpectedly: "
                f"{self._stderr_text().strip()}"
            )
        if self._transport_closed.is_set():
            self._raise_transport_closed(op, mutating=mutating)

        timeout = (
            self._request_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        if timeout <= 0:
            raise ShowdownWorkerTimeout(op, mutating=mutating)

        deadline = perf_counter() + timeout
        waiter: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=1)
        request_id: int | None = None

        acquired_write_lock = False
        while not acquired_write_lock:
            if self._transport_closed.is_set():
                self._raise_transport_closed(op, mutating=mutating)
            remaining = deadline - perf_counter()
            if remaining <= 0:
                raise ShowdownWorkerTimeout(
                    op,
                    mutating=mutating,
                    phase="write-lock",
                )
            acquired_write_lock = self._write_lock.acquire(
                timeout=min(remaining, 0.05)
            )

        try:
            if self._transport_closed.is_set():
                self._raise_transport_closed(op, mutating=mutating)
            if self._process.poll() is not None:
                raise RuntimeError(
                    "Showdown search worker exited unexpectedly: "
                    f"{self._stderr_text().strip()}"
                )

            request_id = self._next_id
            self._next_id += 1
            message = {"id": request_id, "op": op, **payload}
            if deadline - perf_counter() <= 0:
                raise ShowdownWorkerTimeout(
                    op,
                    mutating=mutating,
                    phase="write",
                )
            if self._process.stdin is None:
                raise RuntimeError("Showdown search worker stdin is unavailable")

            with self._pending_lock:
                self._pending[request_id] = waiter

            write_result: queue.Queue[BaseException | None] = queue.Queue(
                maxsize=1
            )

            def write_message() -> None:
                try:
                    encoded = json.dumps(message, separators=(",", ":")) + "\n"
                    self._process.stdin.write(encoded)
                    self._process.stdin.flush()
                except BaseException as error:
                    write_result.put(error)
                else:
                    write_result.put(None)
                finally:
                    with self._writer_threads_lock:
                        self._writer_threads.discard(current_thread())

            writer = Thread(
                target=write_message,
                name=f"showdown-write-{self._process.pid}-{request_id}",
                daemon=True,
            )
            with self._writer_threads_lock:
                self._writer_threads.add(writer)
            try:
                writer.start()
            except BaseException:
                with self._writer_threads_lock:
                    self._writer_threads.discard(writer)
                raise

            while True:
                if self._transport_closed.is_set():
                    with self._pending_lock:
                        self._pending.pop(request_id, None)
                    self._raise_transport_closed(op, mutating=mutating)

                remaining = deadline - perf_counter()
                if remaining <= 0:
                    with self._pending_lock:
                        self._pending.pop(request_id, None)
                    # A timed-out write may have partially submitted a JSONL
                    # request. Abort this transport so no later request can be
                    # framed behind an unknown partial/mutating submission.
                    self.abort(timeout_seconds=0.0)
                    raise ShowdownWorkerTimeout(
                        op,
                        mutating=mutating,
                        phase="write",
                    )

                try:
                    write_error = write_result.get(
                        timeout=min(remaining, 0.05)
                    )
                    break
                except queue.Empty:
                    continue

            if write_error is not None:
                with self._pending_lock:
                    self._pending.pop(request_id, None)
                self.abort(timeout_seconds=0.0)
                if mutating:
                    raise ShowdownWorkerTimeout(
                        op,
                        mutating=True,
                        phase="write",
                    ) from write_error
                raise RuntimeError(
                    f"Showdown worker write failed during {op!r}"
                ) from write_error
        finally:
            self._write_lock.release()

        assert request_id is not None
        remaining = deadline - perf_counter()
        if remaining <= 0:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise ShowdownWorkerTimeout(
                op,
                mutating=mutating,
                phase="response",
            )

        try:
            response = waiter.get(timeout=remaining)
        except queue.Empty as error:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise ShowdownWorkerTimeout(
                op,
                mutating=mutating,
                phase="response",
            ) from error

        with self._pending_lock:
            self._pending.pop(request_id, None)

        if response is None:
            self._raise_transport_closed(op, mutating=mutating)
        if response.get("id") != request_id:
            raise RuntimeError(
                f"Showdown worker response id mismatch: "
                f"expected {request_id}, got {response.get('id')}"
            )
        if not response.get("ok"):
            detail = str(response.get("error", "unknown error"))
            raise ShowdownRequestError(
                op,
                detail,
                mutating=mutating,
                safe_retry=response.get("safe_retry") is True,
            )

        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Showdown worker returned a non-object result")
        return result

    def ping(self) -> bool:
        return bool(self.request("ping").get("pong"))

    def create_state(
        self,
        *,
        battle_format: str,
        p1_team: str,
        p2_team: str,
        p1_preview: str | None = None,
        p2_preview: str | None = None,
        p1_name: str = "Search P1",
        p2_name: str = "Search P2",
        seed: str | None = None,
    ) -> dict[str, Any]:
        """Create one exact Showdown state without opening a persistent session."""
        payload: dict[str, Any] = {
            "format": battle_format,
            "p1_team": p1_team,
            "p2_team": p2_team,
            "p1_name": p1_name,
            "p2_name": p2_name,
        }
        if p1_preview is not None or p2_preview is not None:
            if p1_preview is None or p2_preview is None:
                raise ValueError("both preview choices are required")
            payload["p1_preview"] = p1_preview
            payload["p2_preview"] = p2_preview
        if seed is not None:
            payload["seed"] = seed
        result = self.request("create", **payload)
        state = result.get("state")
        if not isinstance(state, dict):
            raise RuntimeError("Showdown worker returned an invalid created state")
        return state

    def start_session(
        self,
        *,
        battle_format: str,
        p1_team: str,
        p2_team: str,
        p1_name: str = "Practice Player",
        p2_name: str = "Practice AI",
        seed: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "format": battle_format,
            "p1_team": p1_team,
            "p2_team": p2_team,
            "p1_name": p1_name,
            "p2_name": p2_name,
        }
        if seed is not None:
            payload["seed"] = seed
        return self.request("session_start", mutating=True, **payload)

    def session_view(
        self,
        session_id: str,
        *,
        side: str = "p1",
    ) -> dict[str, Any]:
        return self.request("session_view", session_id=session_id, side=side)

    def branch_many(
        self,
        *,
        state: dict[str, Any],
        branches: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Resolve many independent action pairs from one exact snapshot."""
        result = self.request("branch_many", state=state, branches=branches)
        resolved = result.get("branches")
        if not isinstance(resolved, list):
            raise RuntimeError("Showdown worker returned invalid branch_many results")
        return resolved

    def state_view(
        self,
        *,
        state: dict[str, Any],
        side: str,
        previews: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        """Return the sanitized player view for any exact Showdown snapshot."""
        payload: dict[str, Any] = {"state": state, "side": side}
        if previews is not None:
            payload["previews"] = previews
        result = self.request("state_view", **payload)
        view = result.get("view")
        if not isinstance(view, dict):
            raise RuntimeError("Showdown worker returned an invalid state view")
        return view

    def legal_choices(
        self,
        *,
        state: dict[str, Any],
        side: str,
    ) -> list[str]:
        """Enumerate simulator-validated choices from an exact snapshot."""
        result = self.request("legal_choices", state=state, side=side)
        choices = result.get("choices")
        if not isinstance(choices, list) or not all(
            isinstance(choice, str) for choice in choices
        ):
            raise RuntimeError("Showdown worker returned invalid legal choices")
        return choices

    def validate_choices(
        self,
        *,
        state: dict[str, Any],
        side: str,
        candidates: list[str],
    ) -> list[str]:
        """Validate a bounded candidate set without enumerating the full action space."""
        if not candidates:
            return []
        result = self.request(
            "validate_choices",
            state=state,
            side=side,
            candidates=candidates,
        )
        choices = result.get("choices")
        if not isinstance(choices, list) or not all(
            isinstance(choice, str) for choice in choices
        ):
            raise RuntimeError("Showdown worker returned invalid validated choices")
        return choices

    def session_public_choices(self, session_id: str, *, side: str) -> list[str]:
        """Enumerate choices using only the side's public request information."""
        result = self.request(
            "session_public_choices",
            session_id=session_id,
            side=side,
        )
        choices = result.get("choices")
        if not isinstance(choices, list) or not all(
            isinstance(choice, str) for choice in choices
        ):
            raise RuntimeError("Showdown worker returned invalid public session choices")
        return choices

    def session_legal_choices(self, session_id: str, *, side: str) -> list[str]:
        """Enumerate simulator-validated choices for one live session side."""
        result = self.request(
            "session_legal_choices",
            session_id=session_id,
            side=side,
        )
        choices = result.get("choices")
        if not isinstance(choices, list) or not all(
            isinstance(choice, str) for choice in choices
        ):
            raise RuntimeError("Showdown worker returned invalid session choices")
        return choices

    def session_snapshot(self, session_id: str) -> dict[str, Any]:
        return self.request("session_snapshot", session_id=session_id)

    def choose_session(
        self,
        session_id: str,
        *,
        p1_choice: str,
        p2_choice: str,
    ) -> dict[str, Any]:
        return self.request(
            "session_choose",
            session_id=session_id,
            p1_choice=p1_choice,
            p2_choice=p2_choice,
            mutating=True,
        )

    def close_session(self, session_id: str) -> None:
        result = self.request(
            "session_close",
            session_id=session_id,
            mutating=True,
        )
        if not result.get("closed"):
            raise RuntimeError(f"Showdown session {session_id!r} did not close")


    def abort(self, *, timeout_seconds: float = 0.25) -> None:
        """Stop/reap promptly and schedule complete owned transport cleanup."""
        allowance = max(0.0, timeout_seconds)
        deadline = perf_counter() + allowance
        self._signal_transport_closed()

        if self._process.poll() is None:
            try:
                self._process.terminate()
            except OSError:
                pass

            if allowance > 0:
                terminate_wait = min(
                    allowance / 2,
                    max(0.0, deadline - perf_counter()),
                )
                if terminate_wait > 0:
                    try:
                        self._process.wait(timeout=terminate_wait)
                    except subprocess.TimeoutExpired:
                        pass

            if self._process.poll() is None:
                try:
                    self._process.kill()
                except OSError:
                    pass

            remaining = max(0.0, deadline - perf_counter())
            if remaining > 0 and self._process.poll() is None:
                try:
                    self._process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    pass

        # Stream close is deliberately deferred until all owned readers/writers
        # have exited. This keeps abort bounded and avoids reintroducing a block
        # on TextIOWrapper locks held by a stalled stdin writer.
        self._schedule_transport_cleanup()

    def close(self) -> None:
        # Never politely close/flush stdin before terminating the child: another
        # thread may be blocked writing to a full pipe. Abort first, then allow
        # the finalizer a bounded fast-path window. If owned I/O is still
        # unwinding, daemon cleanup continues after close() returns.
        self.abort(timeout_seconds=0.50)
        self._cleanup_done.wait(timeout=0.25)

    def __enter__(self) -> "ShowdownSearchWorker":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
