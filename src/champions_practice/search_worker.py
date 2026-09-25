"""Persistent Python bridge to the exact local Showdown simulator."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


_VERIFIED_SHOWDOWN_ROOTS: dict[Path, str] = {}
_ACTIVE_SHOWDOWN_PROCESSES: dict[int, subprocess.Popen[str]] = {}
_BUILD_STAMP_NAME = "showdown-build.json"


def _showdown_source_revision(root: Path) -> tuple[Path, str]:
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
        )
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
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
        )
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


def _showdown_dist_digest(showdown_root: Path) -> str:
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
) -> str:
    """Fail fast unless source and built Showdown runtime match the pinned build."""
    if project_root is None:
        project_root = Path(__file__).resolve().parents[2]
    root = Path(project_root).resolve()
    cached = _VERIFIED_SHOWDOWN_ROOTS.get(root)
    if cached is not None:
        return cached

    showdown_root, actual = _showdown_source_revision(root)
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
    built_digest = _showdown_dist_digest(showdown_root)
    if stamp.get("dist_sha256") != built_digest:
        raise RuntimeError(
            "Pokemon Showdown built runtime hash mismatch. "
            "Rebuild the pinned runtime before running the practice bot."
        )

    _VERIFIED_SHOWDOWN_ROOTS[root] = actual
    return actual


def active_showdown_worker_pids() -> tuple[int, ...]:
    """Return currently live Node worker PIDs, pruning completed processes."""
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

    def __init__(self, project_root: str | Path | None = None):
        self.__worker = ShowdownSearchWorker(project_root)

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
    """Send JSONL requests to a persistent Node.js Showdown search worker."""

    def __init__(self, project_root: str | Path | None = None):
        if project_root is None:
            project_root = Path(__file__).resolve().parents[2]

        self.project_root = Path(project_root)
        self.showdown_revision = verify_showdown_checkout(self.project_root)
        self.script = self.project_root / "tools" / "showdown-search-worker.js"
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

        self._next_id = 1
        self._process = subprocess.Popen(
            ["node", str(self.script)],
            cwd=self.project_root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        _ACTIVE_SHOWDOWN_PROCESSES[self._process.pid] = self._process

    def request(self, op: str, **payload: Any) -> dict[str, Any]:
        if self._process.poll() is not None:
            stderr = self._process.stderr.read() if self._process.stderr else ""
            raise RuntimeError(
                f"Showdown search worker exited unexpectedly: {stderr.strip()}"
            )

        request_id = self._next_id
        self._next_id += 1

        message = {"id": request_id, "op": op, **payload}

        if self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError("Showdown search worker pipes are unavailable")

        self._process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self._process.stdin.flush()

        line = self._process.stdout.readline()
        if not line:
            stderr = self._process.stderr.read() if self._process.stderr else ""
            raise RuntimeError(
                "Showdown search worker closed without a response. "
                f"stderr={stderr.strip()!r}"
            )

        response = json.loads(line)
        if response.get("id") != request_id:
            raise RuntimeError(
                f"Showdown worker response id mismatch: "
                f"expected {request_id}, got {response.get('id')}"
            )
        if not response.get("ok"):
            raise RuntimeError(
                f"Showdown worker {op!r} failed: {response.get('error', 'unknown error')}"
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
        return self.request("session_start", **payload)

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
        )

    def close_session(self, session_id: str) -> None:
        result = self.request("session_close", session_id=session_id)
        if not result.get("closed"):
            raise RuntimeError(f"Showdown session {session_id!r} did not close")


    def abort(self, *, timeout_seconds: float = 0.25) -> None:
        """Stop and reap this worker inside a bounded cleanup allowance."""
        if self._process.poll() is not None:
            return

        allowance = max(0.0, timeout_seconds)
        self._process.terminate()
        try:
            self._process.wait(timeout=allowance)
            return
        except subprocess.TimeoutExpired:
            pass

        self._process.kill()
        try:
            self._process.wait(timeout=allowance)
        except subprocess.TimeoutExpired:
            # The process has been force-killed. Avoid extending a decision deadline;
            # the OS will finish cleanup after this bounded attempt.
            return

    def close(self) -> None:
        if self._process.poll() is not None:
            return

        if self._process.stdin is not None:
            self._process.stdin.close()

        try:
            self._process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)

    def __enter__(self) -> "ShowdownSearchWorker":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
