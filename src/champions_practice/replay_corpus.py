"""Resumable archive of public Pokémon Showdown replay JSON.

The corpus is intentionally external to the source repository. Raw replay
responses are preserved byte-for-byte; SQLite stores only metadata, hashes,
and resume checkpoints.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SHOWDOWN_REPLAY_BASE_URL = "https://replay.pokemonshowdown.com"
DEFAULT_FORMAT = "gen9championsvgc2026regmc"
DATA_ROOT_ENV = "CHAMPIONS_REPLAY_DATA_ROOT"
SEARCH_PAGE_LIMIT = 51
DEFAULT_MAX_REPLAYS = 5000
DEFAULT_REQUEST_DELAY_SECONDS = 0.25
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_RETRIES = 4
PROGRESS_EVERY_DOWNLOADS = 100
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class ReplayCorpusError(RuntimeError):
    """Replay corpus operation could not continue safely."""


class ReplaySource(Protocol):
    def search(
        self,
        *,
        format_id: str,
        before: int | None,
    ) -> list[dict[str, Any]]: ...

    def fetch_replay(self, replay_id: str) -> bytes: ...


@dataclass(frozen=True)
class CorpusLayout:
    root: Path
    raw: Path
    manifests: Path
    processed: Path
    trajectories: Path
    teams: Path
    models: Path
    cache: Path
    database: Path


@dataclass(frozen=True)
class DownloadStats:
    format_id: str
    pages_completed: int
    search_rows_seen: int
    downloaded: int
    already_present: int
    failed: int
    exhausted: bool
    next_before: int | None
    elapsed_seconds: float
    replay_rate_per_minute: float


@dataclass(frozen=True)
class DownloadConfig:
    data_root: Path
    format_id: str = DEFAULT_FORMAT
    max_replays: int = DEFAULT_MAX_REPLAYS
    restart_search: bool = False
    strict: bool = False

    def __post_init__(self) -> None:
        _validate_public_id(self.format_id, label="format")
        if (
            isinstance(self.max_replays, bool)
            or not isinstance(self.max_replays, int)
            or self.max_replays < 0
        ):
            raise ValueError("max_replays must be a non-negative integer")


def _format_duration(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _timing_snapshot(
    *,
    started_at: float,
    now: float,
    downloaded: int,
    target: int,
) -> tuple[float, float, float | None]:
    elapsed = max(0.0, now - started_at)
    rate_per_minute = 0.0
    eta_seconds: float | None = None
    if downloaded > 0 and elapsed > 0:
        rate_per_minute = downloaded * 60.0 / elapsed
        if target > 0:
            remaining = max(0, target - downloaded)
            eta_seconds = remaining * elapsed / downloaded
    return elapsed, rate_per_minute, eta_seconds


def _progress_message(
    *,
    downloaded: int,
    replay_total: int,
    target: int,
    started_at: float,
    now: float,
) -> str:
    elapsed, rate_per_minute, eta_seconds = _timing_snapshot(
        started_at=started_at,
        now=now,
        downloaded=downloaded,
        target=target,
    )
    target_text = f"/{target}" if target > 0 else ""
    eta_text = (
        _format_duration(eta_seconds)
        if eta_seconds is not None
        else "n/a (unlimited)" if target == 0 else "calculating"
    )
    return (
        f"Downloaded {downloaded}{target_text} this run "
        f"({replay_total} total indexed) | "
        f"elapsed {_format_duration(elapsed)} | "
        f"{rate_per_minute:.1f} replays/min | ETA {eta_text}"
    )


def _download_stats(
    *,
    format_id: str,
    pages_completed: int,
    search_rows_seen: int,
    downloaded: int,
    already_present: int,
    failed: int,
    exhausted: bool,
    next_before: int | None,
    started_at: float,
    now: float,
) -> DownloadStats:
    elapsed, rate_per_minute, _ = _timing_snapshot(
        started_at=started_at,
        now=now,
        downloaded=downloaded,
        target=0,
    )
    return DownloadStats(
        format_id=format_id,
        pages_completed=pages_completed,
        search_rows_seen=search_rows_seen,
        downloaded=downloaded,
        already_present=already_present,
        failed=failed,
        exhausted=exhausted,
        next_before=next_before,
        elapsed_seconds=round(elapsed, 3),
        replay_rate_per_minute=round(rate_per_minute, 3),
    )


def _validate_public_id(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"{label} must contain only lowercase letters, digits, and hyphens")
    return value


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def ensure_external_data_root(
    data_root: str | Path,
    *,
    project_root: str | Path | None = None,
) -> Path:
    """Resolve and reject corpus roots inside the source repository."""

    root = Path(data_root).expanduser().resolve()
    repo = (
        Path(project_root).expanduser().resolve()
        if project_root is not None
        else _project_root()
    )
    if root == repo or _is_within(root, repo):
        raise ReplayCorpusError(
            "Replay corpus data must live outside the source repository. "
            f"Choose an external data root instead of {root}"
        )
    return root


def initialize_layout(
    data_root: str | Path,
    *,
    project_root: str | Path | None = None,
) -> CorpusLayout:
    root = ensure_external_data_root(data_root, project_root=project_root)
    layout = CorpusLayout(
        root=root,
        raw=root / "raw",
        manifests=root / "manifests",
        processed=root / "processed",
        trajectories=root / "trajectories",
        teams=root / "teams",
        models=root / "models",
        cache=root / "cache",
        database=root / "manifests" / "replays.sqlite3",
    )
    for directory in (
        layout.raw,
        layout.manifests,
        layout.processed,
        layout.trajectories,
        layout.teams,
        layout.models,
        layout.cache,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return layout


def _connect_manifest(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS replays (
            replay_id TEXT PRIMARY KEY,
            format_id TEXT NOT NULL,
            uploadtime INTEGER,
            rating INTEGER,
            players_json TEXT NOT NULL,
            raw_relative_path TEXT NOT NULL,
            raw_sha256 TEXT NOT NULL,
            raw_bytes INTEGER NOT NULL,
            search_metadata_json TEXT NOT NULL,
            detail_metadata_json TEXT NOT NULL,
            downloaded_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_replays_format_uploadtime
            ON replays(format_id, uploadtime DESC);

        CREATE TABLE IF NOT EXISTS checkpoints (
            format_id TEXT PRIMARY KEY,
            before_uploadtime INTEGER,
            exhausted INTEGER NOT NULL DEFAULT 0,
            pages_completed INTEGER NOT NULL DEFAULT 0,
            search_rows_seen INTEGER NOT NULL DEFAULT 0,
            replays_downloaded INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS failures (
            replay_id TEXT PRIMARY KEY,
            format_id TEXT NOT NULL,
            attempts INTEGER NOT NULL,
            last_error TEXT NOT NULL,
            search_metadata_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        );
        """
    )
    failure_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(failures)").fetchall()
    }
    if "search_metadata_json" not in failure_columns:
        connection.execute(
            "ALTER TABLE failures "
            "ADD COLUMN search_metadata_json TEXT NOT NULL DEFAULT '{}'"
        )
        connection.commit()
    return connection


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _checkpoint(
    connection: sqlite3.Connection,
    *,
    format_id: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT before_uploadtime, exhausted, pages_completed,
               search_rows_seen, replays_downloaded
        FROM checkpoints
        WHERE format_id = ?
        """,
        (format_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "before_uploadtime": row[0],
        "exhausted": bool(row[1]),
        "pages_completed": row[2],
        "search_rows_seen": row[3],
        "replays_downloaded": row[4],
    }


def _write_checkpoint(
    connection: sqlite3.Connection,
    *,
    format_id: str,
    before_uploadtime: int | None,
    exhausted: bool,
    pages_completed: int,
    search_rows_seen: int,
    replays_downloaded: int,
) -> None:
    connection.execute(
        """
        INSERT INTO checkpoints (
            format_id, before_uploadtime, exhausted, pages_completed,
            search_rows_seen, replays_downloaded, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(format_id) DO UPDATE SET
            before_uploadtime = excluded.before_uploadtime,
            exhausted = excluded.exhausted,
            pages_completed = excluded.pages_completed,
            search_rows_seen = excluded.search_rows_seen,
            replays_downloaded = excluded.replays_downloaded,
            updated_at = excluded.updated_at
        """,
        (
            format_id,
            before_uploadtime,
            int(exhausted),
            pages_completed,
            search_rows_seen,
            replays_downloaded,
            _utc_now(),
        ),
    )
    connection.commit()


def _reset_checkpoint(connection: sqlite3.Connection, *, format_id: str) -> None:
    connection.execute("DELETE FROM checkpoints WHERE format_id = ?", (format_id,))
    connection.commit()


def _parse_search_payload(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ReplayCorpusError("Showdown replay search returned a non-list payload")
    if len(payload) > SEARCH_PAGE_LIMIT:
        raise ReplayCorpusError(
            f"Showdown replay search returned more than {SEARCH_PAGE_LIMIT} rows"
        )

    rows: list[dict[str, Any]] = []
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise ReplayCorpusError(f"search row {index} is not an object")
        replay_id = row.get("id")
        uploadtime = row.get("uploadtime")
        try:
            _validate_public_id(replay_id, label=f"search row {index} replay id")
        except ValueError as error:
            raise ReplayCorpusError(str(error)) from error
        if (
            isinstance(uploadtime, bool)
            or not isinstance(uploadtime, int)
            or uploadtime <= 0
        ):
            raise ReplayCorpusError(
                f"search row {index} has an invalid uploadtime"
            )
        rows.append(row)
    return rows


class ShowdownReplaySource:
    """Small, polite client for the documented public Showdown replay API."""

    def __init__(
        self,
        *,
        request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        retries: int = DEFAULT_RETRIES,
        sleep: Callable[[float], None] = time.sleep,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        if request_delay_seconds < 0:
            raise ValueError("request_delay_seconds cannot be negative")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if retries < 1:
            raise ValueError("retries must be at least 1")
        self.request_delay_seconds = request_delay_seconds
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self._sleep = sleep
        self._opener = opener
        self._last_request_finished: float | None = None

    def _throttle(self) -> None:
        if self.request_delay_seconds <= 0 or self._last_request_finished is None:
            return
        elapsed = time.monotonic() - self._last_request_finished
        remaining = self.request_delay_seconds - elapsed
        if remaining > 0:
            self._sleep(remaining)

    def _get_bytes(self, url: str) -> bytes:
        request = Request(
            url,
            headers={
                "User-Agent": (
                    "champions-practice-bot replay-corpus/1 "
                    "(public research archive)"
                ),
                "Accept": "application/json",
            },
        )
        last_error: BaseException | None = None
        for attempt in range(1, self.retries + 1):
            self._throttle()
            try:
                with self._opener(request, timeout=self.timeout_seconds) as response:
                    payload = response.read()
                self._last_request_finished = time.monotonic()
                return payload
            except (HTTPError, URLError, TimeoutError, OSError) as error:
                self._last_request_finished = time.monotonic()
                last_error = error
                if attempt >= self.retries:
                    break
                self._sleep(min(2 ** (attempt - 1), 8))
        raise ReplayCorpusError(f"GET failed after {self.retries} attempts: {url}") from last_error

    def search(
        self,
        *,
        format_id: str,
        before: int | None,
    ) -> list[dict[str, Any]]:
        _validate_public_id(format_id, label="format")
        query: dict[str, str | int] = {"format": format_id}
        if before is not None:
            if isinstance(before, bool) or not isinstance(before, int) or before <= 0:
                raise ValueError("before must be a positive Unix timestamp")
            query["before"] = before
        url = f"{SHOWDOWN_REPLAY_BASE_URL}/search.json?{urlencode(query)}"
        raw = self._get_bytes(url)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ReplayCorpusError("Showdown replay search returned invalid JSON") from error
        return _parse_search_payload(payload)

    def fetch_replay(self, replay_id: str) -> bytes:
        _validate_public_id(replay_id, label="replay id")
        return self._get_bytes(f"{SHOWDOWN_REPLAY_BASE_URL}/{replay_id}.json")


def _raw_path(layout: CorpusLayout, *, format_id: str, replay_id: str) -> Path:
    return layout.raw / format_id / f"{replay_id}.json"


def _relative_path(path: Path, *, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _validated_detail(raw: bytes, *, replay_id: str) -> dict[str, Any]:
    try:
        detail = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ReplayCorpusError(f"replay {replay_id} returned invalid JSON") from error
    if not isinstance(detail, dict):
        raise ReplayCorpusError(f"replay {replay_id} returned a non-object JSON payload")
    returned_id = detail.get("id")
    if returned_id is not None and returned_id != replay_id:
        raise ReplayCorpusError(
            f"replay endpoint returned id {returned_id!r} for requested {replay_id!r}"
        )
    log = detail.get("log")
    if not isinstance(log, str) or not log:
        raise ReplayCorpusError(f"replay {replay_id} has no battle log")
    return detail


def _compact_detail_metadata(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in detail.items()
        if key not in {"log", "inputlog"}
    }


def _coerce_optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _players_json(search_row: dict[str, Any], detail: dict[str, Any]) -> str:
    players = detail.get("players", search_row.get("players", []))
    if not isinstance(players, list) or not all(isinstance(player, str) for player in players):
        players = []
    return json.dumps(players, ensure_ascii=False, separators=(",", ":"))


def _upsert_replay_record(
    connection: sqlite3.Connection,
    *,
    layout: CorpusLayout,
    format_id: str,
    replay_id: str,
    search_row: dict[str, Any],
    raw: bytes,
    detail: dict[str, Any],
    raw_path: Path,
) -> None:
    uploadtime = _coerce_optional_int(detail.get("uploadtime"))
    if uploadtime is None:
        uploadtime = _coerce_optional_int(search_row.get("uploadtime"))
    rating = _coerce_optional_int(detail.get("rating"))
    if rating is None:
        rating = _coerce_optional_int(search_row.get("rating"))

    connection.execute(
        """
        INSERT INTO replays (
            replay_id, format_id, uploadtime, rating, players_json,
            raw_relative_path, raw_sha256, raw_bytes,
            search_metadata_json, detail_metadata_json, downloaded_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(replay_id) DO UPDATE SET
            format_id = excluded.format_id,
            uploadtime = excluded.uploadtime,
            rating = excluded.rating,
            players_json = excluded.players_json,
            raw_relative_path = excluded.raw_relative_path,
            raw_sha256 = excluded.raw_sha256,
            raw_bytes = excluded.raw_bytes,
            search_metadata_json = excluded.search_metadata_json,
            detail_metadata_json = excluded.detail_metadata_json,
            downloaded_at = excluded.downloaded_at
        """,
        (
            replay_id,
            format_id,
            uploadtime,
            rating,
            _players_json(search_row, detail),
            _relative_path(raw_path, root=layout.root),
            hashlib.sha256(raw).hexdigest(),
            len(raw),
            json.dumps(
                search_row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            json.dumps(
                _compact_detail_metadata(detail),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            _utc_now(),
        ),
    )
    connection.execute("DELETE FROM failures WHERE replay_id = ?", (replay_id,))
    connection.commit()


def _record_failure(
    connection: sqlite3.Connection,
    *,
    replay_id: str,
    format_id: str,
    search_row: dict[str, Any],
    error: BaseException,
) -> None:
    metadata = json.dumps(
        search_row,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    connection.execute(
        """
        INSERT INTO failures (
            replay_id, format_id, attempts, last_error,
            search_metadata_json, updated_at
        )
        VALUES (?, ?, 1, ?, ?, ?)
        ON CONFLICT(replay_id) DO UPDATE SET
            attempts = failures.attempts + 1,
            last_error = excluded.last_error,
            search_metadata_json = excluded.search_metadata_json,
            updated_at = excluded.updated_at
        """,
        (replay_id, format_id, str(error), metadata, _utc_now()),
    )
    connection.commit()


def _pending_failures(
    connection: sqlite3.Connection,
    *,
    format_id: str,
) -> list[tuple[str, dict[str, Any]]]:
    rows = connection.execute(
        """
        SELECT replay_id, search_metadata_json
        FROM failures
        WHERE format_id = ?
        ORDER BY updated_at ASC, replay_id ASC
        """,
        (format_id,),
    ).fetchall()
    pending: list[tuple[str, dict[str, Any]]] = []
    for replay_id, metadata_json in rows:
        try:
            metadata = json.loads(metadata_json)
        except json.JSONDecodeError:
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        metadata.setdefault("id", replay_id)
        pending.append((replay_id, metadata))
    return pending


def _has_indexed_replay(
    connection: sqlite3.Connection,
    *,
    replay_id: str,
    raw_path: Path,
) -> bool:
    row = connection.execute(
        "SELECT 1 FROM replays WHERE replay_id = ?",
        (replay_id,),
    ).fetchone()
    return row is not None and raw_path.is_file()


def _index_existing_raw(
    connection: sqlite3.Connection,
    *,
    layout: CorpusLayout,
    format_id: str,
    replay_id: str,
    search_row: dict[str, Any],
    raw_path: Path,
) -> bool:
    if not raw_path.is_file():
        return False
    raw = raw_path.read_bytes()
    try:
        detail = _validated_detail(raw, replay_id=replay_id)
    except ReplayCorpusError:
        return False
    _upsert_replay_record(
        connection,
        layout=layout,
        format_id=format_id,
        replay_id=replay_id,
        search_row=search_row,
        raw=raw,
        detail=detail,
        raw_path=raw_path,
    )
    return True


def download_replay_corpus(
    source: ReplaySource,
    *,
    config: DownloadConfig,
    project_root: str | Path | None = None,
    progress: Callable[[str], None] | None = print,
    clock: Callable[[], float] = time.monotonic,
) -> DownloadStats:
    """Download/resume a public-format replay archive."""

    started_at = clock()
    layout = initialize_layout(config.data_root, project_root=project_root)
    connection = _connect_manifest(layout.database)
    try:
        existing_replay_count = connection.execute(
            "SELECT COUNT(*) FROM replays WHERE format_id = ?",
            (config.format_id,),
        ).fetchone()[0]
        refreshing_known_archive = (
            config.restart_search and int(existing_replay_count) > 0
        )
        if config.restart_search:
            _reset_checkpoint(connection, format_id=config.format_id)
        saved = _checkpoint(connection, format_id=config.format_id)

        before = saved["before_uploadtime"] if saved is not None else None
        exhausted = bool(saved["exhausted"]) if saved is not None else False
        pages_completed = int(saved["pages_completed"]) if saved is not None else 0
        search_rows_seen = int(saved["search_rows_seen"]) if saved is not None else 0
        replay_total = int(saved["replays_downloaded"]) if saved is not None else 0

        run_downloaded = 0
        run_present = 0
        run_failed = 0

        for replay_id, row in _pending_failures(
            connection,
            format_id=config.format_id,
        ):
            if config.max_replays and run_downloaded >= config.max_replays:
                break
            path = _raw_path(
                layout,
                format_id=config.format_id,
                replay_id=replay_id,
            )
            try:
                raw = source.fetch_replay(replay_id)
                detail = _validated_detail(raw, replay_id=replay_id)
                _atomic_write(path, raw)
                _upsert_replay_record(
                    connection,
                    layout=layout,
                    format_id=config.format_id,
                    replay_id=replay_id,
                    search_row=row,
                    raw=raw,
                    detail=detail,
                    raw_path=path,
                )
            except Exception as error:
                _record_failure(
                    connection,
                    replay_id=replay_id,
                    format_id=config.format_id,
                    search_row=row,
                    error=error,
                )
                run_failed += 1
                if config.strict:
                    raise
                if progress is not None:
                    progress(f"RETRY FAILED {replay_id}: {error}")
                continue
            run_downloaded += 1
            replay_total += 1
            if progress is not None:
                progress(f"Recovered previously failed replay {replay_id}")

        if saved is not None and run_downloaded:
            _write_checkpoint(
                connection,
                format_id=config.format_id,
                before_uploadtime=before,
                exhausted=exhausted,
                pages_completed=pages_completed,
                search_rows_seen=search_rows_seen,
                replays_downloaded=replay_total,
            )

        if exhausted and not config.restart_search:
            return _download_stats(
                format_id=config.format_id,
                pages_completed=pages_completed,
                search_rows_seen=search_rows_seen,
                downloaded=run_downloaded,
                already_present=run_present,
                failed=run_failed,
                exhausted=True,
                next_before=None,
                started_at=started_at,
                now=clock(),
            )

        while config.max_replays == 0 or run_downloaded < config.max_replays:
            rows = source.search(format_id=config.format_id, before=before)
            if not rows:
                exhausted = True
                _write_checkpoint(
                    connection,
                    format_id=config.format_id,
                    before_uploadtime=None,
                    exhausted=True,
                    pages_completed=pages_completed + 1,
                    search_rows_seen=search_rows_seen,
                    replays_downloaded=replay_total,
                )
                pages_completed += 1
                break

            page_complete = True
            page_all_preexisting = True
            for row in rows:
                if config.max_replays and run_downloaded >= config.max_replays:
                    page_complete = False
                    break

                replay_id = row["id"]
                path = _raw_path(
                    layout,
                    format_id=config.format_id,
                    replay_id=replay_id,
                )
                search_rows_seen += 1

                if _has_indexed_replay(
                    connection,
                    replay_id=replay_id,
                    raw_path=path,
                ):
                    run_present += 1
                    continue

                if _index_existing_raw(
                    connection,
                    layout=layout,
                    format_id=config.format_id,
                    replay_id=replay_id,
                    search_row=row,
                    raw_path=path,
                ):
                    run_present += 1
                    replay_total += 1
                    page_all_preexisting = False
                    continue

                page_all_preexisting = False
                try:
                    raw = source.fetch_replay(replay_id)
                    detail = _validated_detail(raw, replay_id=replay_id)
                    _atomic_write(path, raw)
                    _upsert_replay_record(
                        connection,
                        layout=layout,
                        format_id=config.format_id,
                        replay_id=replay_id,
                        search_row=row,
                        raw=raw,
                        detail=detail,
                        raw_path=path,
                    )
                except Exception as error:
                    _record_failure(
                        connection,
                        replay_id=replay_id,
                        format_id=config.format_id,
                        search_row=row,
                        error=error,
                    )
                    run_failed += 1
                    if config.strict:
                        raise
                    if progress is not None:
                        progress(f"FAILED {replay_id}: {error}")
                    continue

                run_downloaded += 1
                replay_total += 1
                if progress is not None and (
                    run_downloaded == 1
                    or run_downloaded % PROGRESS_EVERY_DOWNLOADS == 0
                ):
                    progress(
                        _progress_message(
                            downloaded=run_downloaded,
                            replay_total=replay_total,
                            target=config.max_replays,
                            started_at=started_at,
                            now=clock(),
                        )
                    )

            if not page_complete:
                # Do not advance the cursor until every row on this page has been
                # considered; rerunning the page is safe because replay IDs are
                # deduplicated by both path and SQLite primary key.
                break

            pages_completed += 1
            if refreshing_known_archive and page_all_preexisting:
                exhausted = True
                before = None
                _write_checkpoint(
                    connection,
                    format_id=config.format_id,
                    before_uploadtime=None,
                    exhausted=True,
                    pages_completed=pages_completed,
                    search_rows_seen=search_rows_seen,
                    replays_downloaded=replay_total,
                )
                break

            has_more = len(rows) == SEARCH_PAGE_LIMIT
            if has_more:
                next_before = min(int(row["uploadtime"]) for row in rows)
                if before is not None and next_before >= before:
                    raise ReplayCorpusError(
                        "Showdown replay pagination cursor did not move backward"
                    )
                before = next_before
                _write_checkpoint(
                    connection,
                    format_id=config.format_id,
                    before_uploadtime=before,
                    exhausted=False,
                    pages_completed=pages_completed,
                    search_rows_seen=search_rows_seen,
                    replays_downloaded=replay_total,
                )
                continue

            exhausted = True
            before = None
            _write_checkpoint(
                connection,
                format_id=config.format_id,
                before_uploadtime=None,
                exhausted=True,
                pages_completed=pages_completed,
                search_rows_seen=search_rows_seen,
                replays_downloaded=replay_total,
            )
            break

        if not exhausted:
            _write_checkpoint(
                connection,
                format_id=config.format_id,
                before_uploadtime=before,
                exhausted=False,
                pages_completed=pages_completed,
                search_rows_seen=search_rows_seen,
                replays_downloaded=replay_total,
            )

        return _download_stats(
            format_id=config.format_id,
            pages_completed=pages_completed,
            search_rows_seen=search_rows_seen,
            downloaded=run_downloaded,
            already_present=run_present,
            failed=run_failed,
            exhausted=exhausted,
            next_before=before,
            started_at=started_at,
            now=clock(),
        )
    finally:
        connection.close()


def corpus_status(
    data_root: str | Path,
    *,
    format_id: str = DEFAULT_FORMAT,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    layout = initialize_layout(data_root, project_root=project_root)
    connection = _connect_manifest(layout.database)
    try:
        replay_count, total_bytes = connection.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(raw_bytes), 0)
            FROM replays
            WHERE format_id = ?
            """,
            (format_id,),
        ).fetchone()
        failures = connection.execute(
            "SELECT COUNT(*) FROM failures WHERE format_id = ?",
            (format_id,),
        ).fetchone()[0]
        checkpoint = _checkpoint(connection, format_id=format_id)
        return {
            "format_id": format_id,
            "replays": int(replay_count),
            "raw_bytes": int(total_bytes),
            "failures": int(failures),
            "checkpoint": checkpoint,
            "data_root": str(layout.root),
        }
    finally:
        connection.close()


def _resolve_cli_data_root(value: str | None) -> Path:
    selected = value or os.environ.get(DATA_ROOT_ENV)
    if not selected:
        raise ReplayCorpusError(
            f"Pass --data-root or set {DATA_ROOT_ENV}. "
            "The Windows launcher supplies the local F: drive default."
        )
    return Path(selected)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Archive public Pokémon Showdown replay JSON outside the Git repository."
    )
    parser.add_argument("--data-root", help=f"External corpus root; or set {DATA_ROOT_ENV}.")
    parser.add_argument("--format", default=DEFAULT_FORMAT, dest="format_id")
    parser.add_argument(
        "--max-replays",
        type=int,
        default=DEFAULT_MAX_REPLAYS,
        help="Maximum newly downloaded replays this run; 0 means unlimited.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_REQUEST_DELAY_SECONDS,
        help="Minimum delay between Showdown HTTP requests.",
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument(
        "--restart-search",
        action="store_true",
        help="Restart pagination from newest results without deleting archived replays.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Stop on the first individual replay download/validation failure.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print local corpus status without contacting Showdown.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        data_root = _resolve_cli_data_root(args.data_root)
        if args.status:
            print(json.dumps(corpus_status(data_root, format_id=args.format_id), indent=2))
            return

        source = ShowdownReplaySource(
            request_delay_seconds=args.delay,
            timeout_seconds=args.timeout,
            retries=args.retries,
        )
        stats = download_replay_corpus(
            source,
            config=DownloadConfig(
                data_root=data_root,
                format_id=args.format_id,
                max_replays=args.max_replays,
                restart_search=args.restart_search,
                strict=args.strict,
            ),
        )
        print(json.dumps(stats.__dict__, indent=2))
    except (ReplayCorpusError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
