"""Persistent Python bridge to the exact local Showdown simulator."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


class ShowdownSearchWorker:
    """Send JSONL requests to a persistent Node.js Showdown search worker."""

    def __init__(self, project_root: str | Path | None = None):
        if project_root is None:
            project_root = Path(__file__).resolve().parents[2]

        self.project_root = Path(project_root)
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


    def abort(self) -> None:
        """Immediately stop this worker so an over-budget search cannot block play."""
        if self._process.poll() is not None:
            return
        self._process.kill()
        try:
            self._process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self._process.terminate()

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
