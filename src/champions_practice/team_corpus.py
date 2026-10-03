"""Curated full-team corpus ingestion from the public VGCPastes repository.

The external corpus preserves the public index snapshot and raw Pokepaste bytes,
then asks the pinned Pokemon Showdown runtime to parse and validate each team.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from champions_practice.replay_corpus import (
    DATA_ROOT_ENV,
    DEFAULT_REQUEST_DELAY_SECONDS,
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    ensure_external_data_root,
)
from champions_practice.search_worker import TeamValidationWorker


VGCPASTES_SPREADSHEET_ID = "1axlwmzPA49rYkqXh7zHvAtSP-TKbM0ijGYBPRflLSWw"
GOOGLE_SHEETS_EXPORT_BASE = "https://docs.google.com/spreadsheets/d"
POKEPASTE_HOST = "pokepast.es"
DEFAULT_MAX_TEAMS = 500
PROGRESS_EVERY_TEAMS = 50
_INDEX_COLUMNS = 45


class TeamCorpusError(RuntimeError):
    """Team-corpus ingestion could not continue safely."""


@dataclass(frozen=True)
class RegulationSource:
    key: str
    label: str
    sheet_name: str
    sheet_gid: int
    format_id: str


REGULATION_SOURCES = (
    RegulationSource(
        key="mc",
        label="Champions M-C",
        sheet_name="Champions M-C",
        sheet_gid=2001945654,
        format_id="gen9championsvgc2026regmc",
    ),
    RegulationSource(
        key="mb",
        label="Champions M-B",
        sheet_name="Champions M-B",
        sheet_gid=1458357160,
        format_id="gen9championsvgc2026regmb",
    ),
    RegulationSource(
        key="ma",
        label="Champions M-A",
        sheet_name="Champions M-A",
        sheet_gid=791705272,
        format_id="gen9championsvgc2026regma",
    ),
)
REGULATION_BY_KEY = {source.key: source for source in REGULATION_SOURCES}


@dataclass(frozen=True)
class TeamIndexEntry:
    regulation: str
    format_id: str
    sheet_name: str
    sheet_gid: int
    team_id: str
    description: str
    full_name: str
    pokepaste_url: str | None
    source_has_evs: bool
    extracted_paste: str
    replica_status: str
    replica_code: str
    date_shared: str
    tournament_event: str
    rank: str
    source_url: str
    report_url: str
    other_links: str
    owner: str
    species: tuple[str, ...]
    items: tuple[str, ...]
    source_index_sha256: str


@dataclass(frozen=True)
class TeamCorpusLayout:
    root: Path
    teams_root: Path
    raw: Path
    canonical: Path
    index_snapshots: Path
    manifests: Path
    database: Path


@dataclass(frozen=True)
class TeamSyncStats:
    regulations: tuple[str, ...]
    index_rows: int
    processed: int
    downloaded: int
    revalidated: int
    already_current: int
    valid: int
    invalid: int
    failed: int
    exact_truth_ready: int
    elapsed_seconds: float
    teams_per_minute: float


class TeamIndexSource(Protocol):
    def fetch_index(self, source: RegulationSource) -> bytes: ...

    def fetch_paste(self, pokepaste_url: str) -> bytes: ...


class TeamValidator(Protocol):
    showdown_revision: str

    def validate_team(
        self,
        *,
        battle_format: str,
        team_text: str,
    ) -> dict[str, Any]: ...


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _format_duration(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _rate(*, count: int, elapsed: float) -> float:
    if count <= 0 or elapsed <= 0:
        return 0.0
    return count * 60.0 / elapsed


def _progress_message(
    *,
    processed: int,
    target: int,
    elapsed: float,
) -> str:
    rate = _rate(count=processed, elapsed=elapsed)
    eta: float | None = None
    if processed > 0 and target > processed:
        eta = (target - processed) * elapsed / processed
    eta_text = _format_duration(eta) if eta is not None else "calculating"
    return (
        f"Processed {processed}/{target} teams | "
        f"elapsed {_format_duration(elapsed)} | "
        f"{rate:.1f} teams/min | ETA {eta_text}"
    )


def _safe_cell(row: list[str], index: int) -> str:
    if index >= len(row):
        return ""
    return row[index].strip()


def _normalize_optional(value: str) -> str:
    value = value.strip()
    return "" if value in {"-", "None"} else value


def _normalize_pokepaste_url(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host not in {POKEPASTE_HOST, f"www.{POKEPASTE_HOST}"}:
        return None
    path_parts = [part for part in parts.path.split("/") if part]
    if len(path_parts) != 1:
        return None
    slug = path_parts[0]
    if not slug or any(character not in "0123456789abcdefABCDEF" for character in slug):
        return None
    return f"https://{POKEPASTE_HOST}/{slug.lower()}"


def pokepaste_raw_url(pokepaste_url: str) -> str:
    normalized = _normalize_pokepaste_url(pokepaste_url)
    if normalized is None:
        raise TeamCorpusError(f"Unsupported Pokepaste URL: {pokepaste_url!r}")
    parts = urlsplit(normalized)
    return urlunsplit((parts.scheme, parts.netloc, f"{parts.path}/raw", "", ""))


def vgcpastes_csv_url(source: RegulationSource) -> str:
    return (
        f"{GOOGLE_SHEETS_EXPORT_BASE}/{VGCPASTES_SPREADSHEET_ID}/export"
        f"?format=csv&gid={source.sheet_gid}"
    )


def parse_vgcpastes_csv(
    payload: bytes,
    *,
    source: RegulationSource,
) -> list[TeamIndexEntry]:
    digest = hashlib.sha256(payload).hexdigest()
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise TeamCorpusError(
            f"{source.sheet_name} CSV is not valid UTF-8"
        ) from error

    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 3:
        raise TeamCorpusError(f"{source.sheet_name} CSV is missing its header rows")

    header = rows[2]
    required = {
        0: "Team ID",
        24: "Pokepaste",
        25: "EVs",
        37: "Pokemon Text for Copypasta",
        44: "Team ID",
    }
    for column, expected in required.items():
        actual = _safe_cell(header, column)
        if actual != expected:
            raise TeamCorpusError(
                f"{source.sheet_name} column {column + 1} expected "
                f"{expected!r}, found {actual!r}"
            )

    entries: list[TeamIndexEntry] = []
    seen: set[str] = set()
    for row_number, row in enumerate(rows[3:], start=4):
        team_id = _safe_cell(row, 0)
        if not team_id:
            continue
        duplicate_id = _safe_cell(row, 44)
        if duplicate_id and duplicate_id != team_id:
            raise TeamCorpusError(
                f"{source.sheet_name} row {row_number} has inconsistent team IDs"
            )
        if team_id in seen:
            raise TeamCorpusError(
                f"{source.sheet_name} contains duplicate team ID {team_id!r}"
            )
        seen.add(team_id)

        species = tuple(
            value
            for index in range(37, 43)
            if (value := _safe_cell(row, index))
        )
        items = tuple(_safe_cell(row, index) for index in (7, 10, 13, 16, 19, 22))
        entries.append(
            TeamIndexEntry(
                regulation=source.key,
                format_id=source.format_id,
                sheet_name=source.sheet_name,
                sheet_gid=source.sheet_gid,
                team_id=team_id,
                description=_safe_cell(row, 1),
                full_name=_safe_cell(row, 3),
                pokepaste_url=_normalize_pokepaste_url(_safe_cell(row, 24)),
                source_has_evs=_safe_cell(row, 25).lower() == "yes",
                extracted_paste=_safe_cell(row, 26),
                replica_status=_safe_cell(row, 27),
                replica_code=_normalize_optional(_safe_cell(row, 28)),
                date_shared=_safe_cell(row, 29),
                tournament_event=_normalize_optional(_safe_cell(row, 30)),
                rank=_safe_cell(row, 31),
                source_url=_normalize_optional(_safe_cell(row, 32)),
                report_url=_normalize_optional(_safe_cell(row, 33)),
                other_links=_normalize_optional(_safe_cell(row, 34)),
                owner=_safe_cell(row, 35),
                species=species,
                items=items,
                source_index_sha256=digest,
            )
        )
    return entries


def initialize_team_layout(
    data_root: str | Path,
    *,
    project_root: str | Path | None = None,
) -> TeamCorpusLayout:
    root = ensure_external_data_root(data_root, project_root=project_root)
    teams_root = root / "teams"
    layout = TeamCorpusLayout(
        root=root,
        teams_root=teams_root,
        raw=teams_root / "raw",
        canonical=teams_root / "canonical",
        index_snapshots=teams_root / "index",
        manifests=teams_root / "manifests",
        database=teams_root / "manifests" / "teams.sqlite3",
    )
    for directory in (
        layout.raw,
        layout.canonical,
        layout.index_snapshots,
        layout.manifests,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return layout


def _connect_manifest(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS source_snapshots (
            regulation TEXT NOT NULL,
            source_index_sha256 TEXT NOT NULL,
            sheet_name TEXT NOT NULL,
            sheet_gid INTEGER NOT NULL,
            relative_path TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (regulation, source_index_sha256)
        );

        CREATE TABLE IF NOT EXISTS teams (
            regulation TEXT NOT NULL,
            team_id TEXT NOT NULL,
            format_id TEXT NOT NULL,
            sheet_name TEXT NOT NULL,
            sheet_gid INTEGER NOT NULL,
            description TEXT NOT NULL,
            full_name TEXT NOT NULL,
            pokepaste_url TEXT,
            source_has_evs INTEGER NOT NULL,
            extracted_paste TEXT NOT NULL,
            replica_status TEXT NOT NULL,
            replica_code TEXT NOT NULL,
            date_shared TEXT NOT NULL,
            tournament_event TEXT NOT NULL,
            rank TEXT NOT NULL,
            source_url TEXT NOT NULL,
            report_url TEXT NOT NULL,
            other_links TEXT NOT NULL,
            owner TEXT NOT NULL,
            species_json TEXT NOT NULL,
            items_json TEXT NOT NULL,
            source_index_sha256 TEXT NOT NULL,
            raw_relative_path TEXT,
            raw_sha256 TEXT,
            raw_bytes INTEGER,
            canonical_relative_path TEXT,
            canonical_sha256 TEXT,
            canonical_bytes INTEGER,
            packed_team TEXT,
            sets_json TEXT,
            validation_state TEXT NOT NULL,
            validation_problems_json TEXT NOT NULL,
            team_size INTEGER,
            validator_revision TEXT,
            exact_truth_ready INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (regulation, team_id)
        );

        CREATE INDEX IF NOT EXISTS idx_teams_format_ready
            ON teams(format_id, exact_truth_ready);

        CREATE TABLE IF NOT EXISTS fetch_failures (
            regulation TEXT NOT NULL,
            team_id TEXT NOT NULL,
            pokepaste_url TEXT,
            attempts INTEGER NOT NULL,
            last_error TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (regulation, team_id)
        );
        """
    )
    return connection


def _relative(path: Path, *, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _paste_slug(url: str) -> str:
    normalized = _normalize_pokepaste_url(url)
    if normalized is None:
        raise TeamCorpusError(f"Unsupported Pokepaste URL: {url!r}")
    return urlsplit(normalized).path.strip("/")


def _raw_path(
    layout: TeamCorpusLayout,
    *,
    entry: TeamIndexEntry,
) -> Path:
    slug = _paste_slug(entry.pokepaste_url or "")
    return layout.raw / entry.regulation / entry.team_id / f"{slug}.txt"


def _canonical_path(
    layout: TeamCorpusLayout,
    *,
    entry: TeamIndexEntry,
) -> Path:
    slug = _paste_slug(entry.pokepaste_url or "")
    return layout.canonical / entry.regulation / entry.team_id / f"{slug}.txt"


def _write_source_snapshot(
    connection: sqlite3.Connection,
    *,
    layout: TeamCorpusLayout,
    source: RegulationSource,
    payload: bytes,
    row_count: int,
) -> str:
    digest = hashlib.sha256(payload).hexdigest()
    path = layout.index_snapshots / source.key / f"{digest}.csv"
    if not path.is_file():
        _atomic_write(path, payload)
    connection.execute(
        """
        INSERT OR IGNORE INTO source_snapshots (
            regulation, source_index_sha256, sheet_name, sheet_gid,
            relative_path, row_count, fetched_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source.key,
            digest,
            source.sheet_name,
            source.sheet_gid,
            _relative(path, root=layout.root),
            row_count,
            _utc_now(),
        ),
    )
    connection.commit()
    return digest


def _metadata_values(entry: TeamIndexEntry) -> tuple[Any, ...]:
    return (
        entry.format_id,
        entry.sheet_name,
        entry.sheet_gid,
        entry.description,
        entry.full_name,
        entry.pokepaste_url,
        int(entry.source_has_evs),
        entry.extracted_paste,
        entry.replica_status,
        entry.replica_code,
        entry.date_shared,
        entry.tournament_event,
        entry.rank,
        entry.source_url,
        entry.report_url,
        entry.other_links,
        entry.owner,
        json.dumps(entry.species, ensure_ascii=False),
        json.dumps(entry.items, ensure_ascii=False),
        entry.source_index_sha256,
    )


def _existing_team(
    connection: sqlite3.Connection,
    *,
    entry: TeamIndexEntry,
) -> sqlite3.Row | None:
    connection.row_factory = sqlite3.Row
    return connection.execute(
        """
        SELECT *
        FROM teams
        WHERE regulation = ? AND team_id = ?
        """,
        (entry.regulation, entry.team_id),
    ).fetchone()


def _update_existing_metadata(
    connection: sqlite3.Connection,
    *,
    entry: TeamIndexEntry,
    exact_truth_ready: bool,
) -> None:
    connection.execute(
        """
        UPDATE teams SET
            format_id = ?,
            sheet_name = ?,
            sheet_gid = ?,
            description = ?,
            full_name = ?,
            pokepaste_url = ?,
            source_has_evs = ?,
            extracted_paste = ?,
            replica_status = ?,
            replica_code = ?,
            date_shared = ?,
            tournament_event = ?,
            rank = ?,
            source_url = ?,
            report_url = ?,
            other_links = ?,
            owner = ?,
            species_json = ?,
            items_json = ?,
            source_index_sha256 = ?,
            exact_truth_ready = ?,
            updated_at = ?
        WHERE regulation = ? AND team_id = ?
        """,
        (
            *_metadata_values(entry),
            int(exact_truth_ready),
            _utc_now(),
            entry.regulation,
            entry.team_id,
        ),
    )
    connection.commit()


def _store_missing_paste(
    connection: sqlite3.Connection,
    *,
    entry: TeamIndexEntry,
) -> None:
    connection.execute(
        """
        INSERT INTO teams (
            regulation, team_id, format_id, sheet_name, sheet_gid,
            description, full_name, pokepaste_url, source_has_evs,
            extracted_paste, replica_status, replica_code, date_shared,
            tournament_event, rank, source_url, report_url, other_links,
            owner, species_json, items_json, source_index_sha256,
            validation_state, validation_problems_json,
            exact_truth_ready, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, 'missing_paste', ?, 0, ?)
        ON CONFLICT(regulation, team_id) DO UPDATE SET
            format_id = excluded.format_id,
            sheet_name = excluded.sheet_name,
            sheet_gid = excluded.sheet_gid,
            description = excluded.description,
            full_name = excluded.full_name,
            pokepaste_url = excluded.pokepaste_url,
            source_has_evs = excluded.source_has_evs,
            extracted_paste = excluded.extracted_paste,
            replica_status = excluded.replica_status,
            replica_code = excluded.replica_code,
            date_shared = excluded.date_shared,
            tournament_event = excluded.tournament_event,
            rank = excluded.rank,
            source_url = excluded.source_url,
            report_url = excluded.report_url,
            other_links = excluded.other_links,
            owner = excluded.owner,
            species_json = excluded.species_json,
            items_json = excluded.items_json,
            source_index_sha256 = excluded.source_index_sha256,
            validation_state = excluded.validation_state,
            validation_problems_json = excluded.validation_problems_json,
            exact_truth_ready = 0,
            updated_at = excluded.updated_at
        """,
        (
            entry.regulation,
            entry.team_id,
            *_metadata_values(entry),
            json.dumps(["VGCPastes row has no supported Pokepaste URL"]),
            _utc_now(),
        ),
    )
    connection.commit()


def _store_validation(
    connection: sqlite3.Connection,
    *,
    layout: TeamCorpusLayout,
    entry: TeamIndexEntry,
    raw_path: Path,
    raw: bytes,
    validation: dict[str, Any] | None,
    validator_revision: str,
    validation_error: str | None = None,
) -> tuple[str, bool]:
    raw_hash = hashlib.sha256(raw).hexdigest()
    raw_relative = _relative(raw_path, root=layout.root)

    canonical_relative: str | None = None
    canonical_hash: str | None = None
    canonical_bytes: int | None = None
    packed_team: str | None = None
    sets_json: str | None = None
    team_size: int | None = None
    problems: list[str]
    state: str

    if validation_error is not None:
        state = "error"
        problems = [validation_error]
    else:
        assert validation is not None
        state = "valid" if validation["valid"] else "invalid"
        problems = list(validation["problems"])
        team_size = int(validation["team_size"])
        packed_team = validation["packed_team"]
        sets_json = json.dumps(
            validation["sets"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        canonical = validation["canonical_text"].encode("utf-8")
        canonical_path = _canonical_path(layout, entry=entry)
        _atomic_write(canonical_path, canonical)
        canonical_relative = _relative(canonical_path, root=layout.root)
        canonical_hash = hashlib.sha256(canonical).hexdigest()
        canonical_bytes = len(canonical)

    exact_truth_ready = (
        state == "valid"
        and entry.source_has_evs
        and team_size == 6
        and len(entry.species) == 6
    )

    connection.execute(
        """
        INSERT INTO teams (
            regulation, team_id, format_id, sheet_name, sheet_gid,
            description, full_name, pokepaste_url, source_has_evs,
            extracted_paste, replica_status, replica_code, date_shared,
            tournament_event, rank, source_url, report_url, other_links,
            owner, species_json, items_json, source_index_sha256,
            raw_relative_path, raw_sha256, raw_bytes,
            canonical_relative_path, canonical_sha256, canonical_bytes,
            packed_team, sets_json, validation_state,
            validation_problems_json, team_size, validator_revision,
            exact_truth_ready, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(regulation, team_id) DO UPDATE SET
            format_id = excluded.format_id,
            sheet_name = excluded.sheet_name,
            sheet_gid = excluded.sheet_gid,
            description = excluded.description,
            full_name = excluded.full_name,
            pokepaste_url = excluded.pokepaste_url,
            source_has_evs = excluded.source_has_evs,
            extracted_paste = excluded.extracted_paste,
            replica_status = excluded.replica_status,
            replica_code = excluded.replica_code,
            date_shared = excluded.date_shared,
            tournament_event = excluded.tournament_event,
            rank = excluded.rank,
            source_url = excluded.source_url,
            report_url = excluded.report_url,
            other_links = excluded.other_links,
            owner = excluded.owner,
            species_json = excluded.species_json,
            items_json = excluded.items_json,
            source_index_sha256 = excluded.source_index_sha256,
            raw_relative_path = excluded.raw_relative_path,
            raw_sha256 = excluded.raw_sha256,
            raw_bytes = excluded.raw_bytes,
            canonical_relative_path = excluded.canonical_relative_path,
            canonical_sha256 = excluded.canonical_sha256,
            canonical_bytes = excluded.canonical_bytes,
            packed_team = excluded.packed_team,
            sets_json = excluded.sets_json,
            validation_state = excluded.validation_state,
            validation_problems_json = excluded.validation_problems_json,
            team_size = excluded.team_size,
            validator_revision = excluded.validator_revision,
            exact_truth_ready = excluded.exact_truth_ready,
            updated_at = excluded.updated_at
        """,
        (
            entry.regulation,
            entry.team_id,
            *_metadata_values(entry),
            raw_relative,
            raw_hash,
            len(raw),
            canonical_relative,
            canonical_hash,
            canonical_bytes,
            packed_team,
            sets_json,
            state,
            json.dumps(problems, ensure_ascii=False),
            team_size,
            validator_revision,
            int(exact_truth_ready),
            _utc_now(),
        ),
    )
    connection.execute(
        "DELETE FROM fetch_failures WHERE regulation = ? AND team_id = ?",
        (entry.regulation, entry.team_id),
    )
    connection.commit()
    return state, exact_truth_ready


def _record_fetch_failure(
    connection: sqlite3.Connection,
    *,
    entry: TeamIndexEntry,
    error: BaseException,
) -> None:
    connection.execute(
        """
        INSERT INTO fetch_failures (
            regulation, team_id, pokepaste_url, attempts, last_error, updated_at
        )
        VALUES (?, ?, ?, 1, ?, ?)
        ON CONFLICT(regulation, team_id) DO UPDATE SET
            pokepaste_url = excluded.pokepaste_url,
            attempts = fetch_failures.attempts + 1,
            last_error = excluded.last_error,
            updated_at = excluded.updated_at
        """,
        (
            entry.regulation,
            entry.team_id,
            entry.pokepaste_url,
            str(error),
            _utc_now(),
        ),
    )
    connection.commit()


class VGCPastesHttpSource:
    """Sequential public client for Google Sheets CSV and Pokepaste raw text."""

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
        remaining = (
            self.request_delay_seconds
            - (time.monotonic() - self._last_request_finished)
        )
        if remaining > 0:
            self._sleep(remaining)

    def _get(self, url: str, *, accept: str) -> bytes:
        request = Request(
            url,
            headers={
                "User-Agent": (
                    "champions-practice-bot team-corpus/1 "
                    "(public research archive)"
                ),
                "Accept": accept,
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
        raise TeamCorpusError(
            f"GET failed after {self.retries} attempts: {url}"
        ) from last_error

    def fetch_index(self, source: RegulationSource) -> bytes:
        return self._get(vgcpastes_csv_url(source), accept="text/csv")

    def fetch_paste(self, pokepaste_url: str) -> bytes:
        return self._get(
            pokepaste_raw_url(pokepaste_url),
            accept="text/plain",
        )


def _needs_processing(
    existing: sqlite3.Row | None,
    *,
    entry: TeamIndexEntry,
    validator_revision: str,
    layout: TeamCorpusLayout,
) -> bool:
    if existing is None:
        return True
    if existing["pokepaste_url"] != entry.pokepaste_url:
        return True
    if existing["validator_revision"] != validator_revision:
        return True
    if existing["validation_state"] not in {"valid", "invalid"}:
        return True
    raw_relative = existing["raw_relative_path"]
    if not isinstance(raw_relative, str):
        return True
    return not (layout.root / raw_relative).is_file()


def sync_team_corpus(
    source_client: TeamIndexSource,
    validator: TeamValidator,
    *,
    data_root: str | Path,
    regulations: tuple[str, ...] = ("mc", "mb", "ma"),
    max_teams: int = DEFAULT_MAX_TEAMS,
    project_root: str | Path | None = None,
    progress: Callable[[str], None] | None = print,
    clock: Callable[[], float] = time.monotonic,
) -> TeamSyncStats:
    """Synchronize selected VGCPastes regulation sheets into the external corpus."""

    if isinstance(max_teams, bool) or not isinstance(max_teams, int) or max_teams < 0:
        raise ValueError("max_teams must be a non-negative integer")
    if not regulations:
        raise ValueError("at least one regulation is required")
    selected: list[RegulationSource] = []
    for key in regulations:
        if key not in REGULATION_BY_KEY:
            raise ValueError(f"unsupported regulation {key!r}")
        selected.append(REGULATION_BY_KEY[key])

    started = clock()
    layout = initialize_team_layout(data_root, project_root=project_root)
    connection = _connect_manifest(layout.database)
    try:
        entries: list[TeamIndexEntry] = []
        for regulation_source in selected:
            payload = source_client.fetch_index(regulation_source)
            parsed = parse_vgcpastes_csv(payload, source=regulation_source)
            _write_source_snapshot(
                connection,
                layout=layout,
                source=regulation_source,
                payload=payload,
                row_count=len(parsed),
            )
            entries.extend(parsed)

        pending: list[TeamIndexEntry] = []
        current_entries: list[tuple[TeamIndexEntry, sqlite3.Row]] = []
        missing_entries: list[TeamIndexEntry] = []
        for entry in entries:
            existing = _existing_team(connection, entry=entry)
            if entry.pokepaste_url is None:
                missing_entries.append(entry)
                continue
            if _needs_processing(
                existing,
                entry=entry,
                validator_revision=validator.showdown_revision,
                layout=layout,
            ):
                pending.append(entry)
            elif existing is not None:
                current_entries.append((entry, existing))

        for entry, existing in current_entries:
            ready = (
                bool(existing["validation_state"] == "valid")
                and entry.source_has_evs
                and existing["team_size"] == 6
                and len(entry.species) == 6
            )
            _update_existing_metadata(
                connection,
                entry=entry,
                exact_truth_ready=ready,
            )

        for entry in missing_entries:
            _store_missing_paste(connection, entry=entry)

        target = len(pending)
        if max_teams:
            target = min(target, max_teams)

        processed = 0
        downloaded = 0
        revalidated = 0
        valid = 0
        invalid = 0
        failed = 0
        exact_truth_ready = 0

        for entry in pending:
            if max_teams and processed >= max_teams:
                break
            existing = _existing_team(connection, entry=entry)
            raw_path = _raw_path(layout, entry=entry)
            same_paste = (
                existing is not None
                and existing["pokepaste_url"] == entry.pokepaste_url
                and raw_path.is_file()
            )
            try:
                if same_paste:
                    raw = raw_path.read_bytes()
                    revalidated += 1
                else:
                    raw = source_client.fetch_paste(entry.pokepaste_url or "")
                    if not raw.strip():
                        raise TeamCorpusError(
                            f"Pokepaste {entry.pokepaste_url} returned empty content"
                        )
                    _atomic_write(raw_path, raw)
                    downloaded += 1
            except Exception as error:
                _record_fetch_failure(connection, entry=entry, error=error)
                failed += 1
                processed += 1
                if progress is not None:
                    progress(f"FAILED {entry.regulation}/{entry.team_id}: {error}")
                continue

            try:
                team_text = raw.decode("utf-8")
                validation = validator.validate_team(
                    battle_format=entry.format_id,
                    team_text=team_text,
                )
                state, ready = _store_validation(
                    connection,
                    layout=layout,
                    entry=entry,
                    raw_path=raw_path,
                    raw=raw,
                    validation=validation,
                    validator_revision=validator.showdown_revision,
                )
            except Exception as error:
                state, ready = _store_validation(
                    connection,
                    layout=layout,
                    entry=entry,
                    raw_path=raw_path,
                    raw=raw,
                    validation=None,
                    validator_revision=validator.showdown_revision,
                    validation_error=str(error),
                )

            if state == "valid":
                valid += 1
            elif state == "invalid":
                invalid += 1
            else:
                failed += 1
            if ready:
                exact_truth_ready += 1
            processed += 1

            if progress is not None and (
                processed == 1 or processed % PROGRESS_EVERY_TEAMS == 0
            ):
                progress(
                    _progress_message(
                        processed=processed,
                        target=max(target, processed),
                        elapsed=clock() - started,
                    )
                )

        elapsed = max(0.0, clock() - started)
        return TeamSyncStats(
            regulations=tuple(source.key for source in selected),
            index_rows=len(entries),
            processed=processed,
            downloaded=downloaded,
            revalidated=revalidated,
            already_current=len(current_entries),
            valid=valid,
            invalid=invalid,
            failed=failed,
            exact_truth_ready=exact_truth_ready,
            elapsed_seconds=round(elapsed, 3),
            teams_per_minute=round(_rate(count=processed, elapsed=elapsed), 3),
        )
    finally:
        connection.close()


def team_corpus_status(
    data_root: str | Path,
    *,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    layout = initialize_team_layout(data_root, project_root=project_root)
    connection = _connect_manifest(layout.database)
    try:
        rows = connection.execute(
            """
            SELECT regulation, COUNT(*),
                   SUM(CASE WHEN validation_state = 'valid' THEN 1 ELSE 0 END),
                   SUM(exact_truth_ready)
            FROM teams
            GROUP BY regulation
            ORDER BY regulation
            """
        ).fetchall()
        failures = connection.execute(
            "SELECT COUNT(*) FROM fetch_failures"
        ).fetchone()[0]
        return {
            "data_root": str(layout.root),
            "teams": {
                regulation: {
                    "indexed": int(indexed),
                    "valid": int(valid or 0),
                    "exact_truth_ready": int(ready or 0),
                }
                for regulation, indexed, valid, ready in rows
            },
            "fetch_failures": int(failures),
        }
    finally:
        connection.close()


def _resolve_data_root(value: str | None) -> Path:
    selected = value or os.environ.get(DATA_ROOT_ENV)
    if not selected:
        raise TeamCorpusError(
            f"Pass --data-root or set {DATA_ROOT_ENV}. "
            "The Windows launcher supplies the local F: drive default."
        )
    return Path(selected)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an external validated VGCPastes team corpus."
    )
    parser.add_argument("--data-root", help=f"External corpus root; or set {DATA_ROOT_ENV}.")
    parser.add_argument(
        "--regulations",
        nargs="+",
        choices=tuple(REGULATION_BY_KEY),
        default=["mc", "mb", "ma"],
        help="Regulations to sync; defaults to current M-C first, then M-B and M-A.",
    )
    parser.add_argument(
        "--max-teams",
        type=int,
        default=DEFAULT_MAX_TEAMS,
        help="Maximum teams to fetch/revalidate this run; 0 means all pending teams.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_REQUEST_DELAY_SECONDS,
        help="Minimum delay between public HTTP requests.",
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print local team-corpus status without network access.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        data_root = _resolve_data_root(args.data_root)
        if args.status:
            print(json.dumps(team_corpus_status(data_root), indent=2))
            return

        source = VGCPastesHttpSource(
            request_delay_seconds=args.delay,
            timeout_seconds=args.timeout,
            retries=args.retries,
        )
        with TeamValidationWorker() as validator:
            stats = sync_team_corpus(
                source,
                validator,
                data_root=data_root,
                regulations=tuple(args.regulations),
                max_teams=args.max_teams,
            )
        print(json.dumps(stats.__dict__, indent=2))
    except (TeamCorpusError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
