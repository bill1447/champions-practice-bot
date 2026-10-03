from __future__ import annotations

import csv
import hashlib
import io
import sqlite3
from pathlib import Path
from typing import Any

from champions_practice.team_corpus import (
    REGULATION_BY_KEY,
    TeamCorpusError,
    VGCPastesHttpSource,
    initialize_team_layout,
    parse_vgcpastes_csv,
    pokepaste_raw_url,
    sync_team_corpus,
    team_corpus_status,
    vgcpastes_csv_url,
)


SPECIES = (
    "Garchomp-Mega-Z",
    "Raichu-Mega-Y",
    "Incineroar",
    "Volcarona",
    "Rillaboom",
    "Gholdengo",
)


def _index_csv(
    *,
    team_id: str = "MC001",
    paste_url: str = "https://pokepast.es/0123456789abcdef",
    evs: str = "Yes",
) -> bytes:
    banner1 = [""] * 45
    banner2 = [""] * 45
    header = [""] * 45
    header[0] = "Team ID"
    header[24] = "Pokepaste"
    header[25] = "EVs"
    header[37] = "Pokemon Text for Copypasta"
    header[44] = "Team ID"

    row = [""] * 45
    row[0] = team_id
    row[1] = "Example tournament team"
    row[3] = "Example Player"
    for index, item in zip(
        (7, 10, 13, 16, 19, 22),
        ("Item A", "Item B", "Item C", "Item D", "Item E", "Item F"),
        strict=True,
    ):
        row[index] = item
    row[24] = paste_url
    row[25] = evs
    row[26] = "Owner's"
    row[27] = "✔"
    row[28] = "ABC123"
    row[29] = "3 Oct 2026"
    row[30] = "Example Regional"
    row[31] = "Champion"
    row[32] = "https://example.test/source"
    row[33] = "https://example.test/report"
    row[34] = "https://example.test/other"
    row[35] = "example_owner"
    for offset, species in enumerate(SPECIES):
        row[37 + offset] = species
    row[44] = team_id

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerows((banner1, banner2, header, row))
    return buffer.getvalue().encode("utf-8")


class FakeSource:
    def __init__(
        self,
        *,
        indexes: dict[str, bytes],
        pastes: dict[str, bytes | BaseException],
    ) -> None:
        self.indexes = indexes
        self.pastes = pastes
        self.index_calls: list[str] = []
        self.paste_calls: list[str] = []

    def fetch_index(self, source) -> bytes:
        self.index_calls.append(source.key)
        return self.indexes[source.key]

    def fetch_paste(self, pokepaste_url: str) -> bytes:
        self.paste_calls.append(pokepaste_url)
        result = self.pastes[pokepaste_url]
        if isinstance(result, BaseException):
            raise result
        return result


class FakeValidator:
    def __init__(
        self,
        *,
        revision: str = "a" * 40,
        valid: bool = True,
        team_size: int = 6,
    ) -> None:
        self.showdown_revision = revision
        self.valid = valid
        self.team_size = team_size
        self.calls: list[tuple[str, str]] = []

    def validate_team(
        self,
        *,
        battle_format: str,
        team_text: str,
    ) -> dict[str, Any]:
        self.calls.append((battle_format, team_text))
        problems = [] if self.valid else ["Example validation failure"]
        return {
            "valid": self.valid,
            "problems": problems,
            "team_size": self.team_size,
            "packed_team": "packed-team",
            "canonical_text": "Canonical Team\n",
            "sets": [{"species": species} for species in SPECIES[: self.team_size]],
        }


def _external_root(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    data_root = tmp_path / "external-data"
    return project_root, data_root


def test_regulation_sources_cover_ma_mb_mc_with_current_first():
    assert tuple(REGULATION_BY_KEY) == ("mc", "mb", "ma")
    assert REGULATION_BY_KEY["mc"].format_id == "gen9championsvgc2026regmc"
    assert REGULATION_BY_KEY["mb"].format_id == "gen9championsvgc2026regmb"
    assert REGULATION_BY_KEY["ma"].format_id == "gen9championsvgc2026regma"


def test_vgcpastes_csv_url_uses_exact_public_sheet_gid():
    source = REGULATION_BY_KEY["mc"]
    assert vgcpastes_csv_url(source) == (
        "https://docs.google.com/spreadsheets/d/"
        "1axlwmzPA49rYkqXh7zHvAtSP-TKbM0ijGYBPRflLSWw/export"
        "?format=csv&gid=2001945654"
    )


def test_pokepaste_raw_url_is_strict_and_canonical():
    assert pokepaste_raw_url(
        "https://www.pokepast.es/ABCDEF0123456789"
    ) == "https://pokepast.es/abcdef0123456789/raw"

    for invalid in (
        "http://pokepast.es/0123456789abcdef",
        "https://example.com/0123456789abcdef",
        "https://pokepast.es/../../escape",
        "https://pokepast.es/not-hex",
    ):
        try:
            pokepaste_raw_url(invalid)
        except TeamCorpusError:
            pass
        else:
            raise AssertionError(f"accepted unsafe Pokepaste URL: {invalid}")


def test_parse_vgcpastes_csv_preserves_team_metadata():
    payload = _index_csv()
    source = REGULATION_BY_KEY["mc"]

    entries = parse_vgcpastes_csv(payload, source=source)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.regulation == "mc"
    assert entry.team_id == "MC001"
    assert entry.description == "Example tournament team"
    assert entry.full_name == "Example Player"
    assert entry.pokepaste_url == "https://pokepast.es/0123456789abcdef"
    assert entry.source_has_evs is True
    assert entry.tournament_event == "Example Regional"
    assert entry.rank == "Champion"
    assert entry.owner == "example_owner"
    assert entry.species == SPECIES
    assert entry.items == (
        "Item A",
        "Item B",
        "Item C",
        "Item D",
        "Item E",
        "Item F",
    )
    assert entry.source_index_sha256 == hashlib.sha256(payload).hexdigest()


def test_parse_vgcpastes_csv_fails_closed_on_schema_drift():
    rows = list(csv.reader(io.StringIO(_index_csv().decode("utf-8"))))
    rows[2][24] = "Paste URL"
    buffer = io.StringIO(newline="")
    csv.writer(buffer).writerows(rows)

    try:
        parse_vgcpastes_csv(
            buffer.getvalue().encode("utf-8"),
            source=REGULATION_BY_KEY["mc"],
        )
    except TeamCorpusError as error:
        assert "expected 'Pokepaste'" in str(error)
    else:
        raise AssertionError("schema drift was accepted")


def test_sync_archives_raw_and_canonical_and_marks_exact_truth(tmp_path: Path):
    project_root, data_root = _external_root(tmp_path)
    paste_url = "https://pokepast.es/0123456789abcdef"
    raw = b"Garchomp @ Item\nAbility: Rough Skin\n- Protect\n"
    source = FakeSource(
        indexes={"mc": _index_csv()},
        pastes={paste_url: raw},
    )
    validator = FakeValidator()

    stats = sync_team_corpus(
        source,
        validator,
        data_root=data_root,
        regulations=("mc",),
        max_teams=10,
        project_root=project_root,
        progress=None,
    )

    assert stats.index_rows == 1
    assert stats.processed == 1
    assert stats.downloaded == 1
    assert stats.valid == 1
    assert stats.exact_truth_ready == 1
    assert source.paste_calls == [paste_url]
    assert validator.calls == [
        ("gen9championsvgc2026regmc", raw.decode("utf-8"))
    ]

    raw_path = (
        data_root
        / "teams"
        / "raw"
        / "mc"
        / "MC001"
        / "0123456789abcdef.txt"
    )
    canonical_path = (
        data_root
        / "teams"
        / "canonical"
        / "mc"
        / "MC001"
        / "0123456789abcdef.txt"
    )
    assert raw_path.read_bytes() == raw
    assert canonical_path.read_text(encoding="utf-8") == "Canonical Team\n"

    status = team_corpus_status(data_root, project_root=project_root)
    assert status["teams"]["mc"] == {
        "indexed": 1,
        "valid": 1,
        "exact_truth_ready": 1,
    }
    assert status["fetch_failures"] == 0


def test_sync_second_pass_skips_current_paste_and_validation(tmp_path: Path):
    project_root, data_root = _external_root(tmp_path)
    paste_url = "https://pokepast.es/0123456789abcdef"
    source = FakeSource(
        indexes={"mc": _index_csv()},
        pastes={paste_url: b"Team\n"},
    )
    first_validator = FakeValidator()
    sync_team_corpus(
        source,
        first_validator,
        data_root=data_root,
        regulations=("mc",),
        project_root=project_root,
        progress=None,
    )

    second_source = FakeSource(
        indexes={"mc": _index_csv()},
        pastes={paste_url: AssertionError("must not refetch")},
    )
    second_validator = FakeValidator()
    stats = sync_team_corpus(
        second_source,
        second_validator,
        data_root=data_root,
        regulations=("mc",),
        project_root=project_root,
        progress=None,
    )

    assert stats.processed == 0
    assert stats.already_current == 1
    assert second_source.paste_calls == []
    assert second_validator.calls == []


def test_showdown_revision_change_revalidates_without_refetch(tmp_path: Path):
    project_root, data_root = _external_root(tmp_path)
    paste_url = "https://pokepast.es/0123456789abcdef"
    raw = b"Team\n"
    first_source = FakeSource(
        indexes={"mc": _index_csv()},
        pastes={paste_url: raw},
    )
    sync_team_corpus(
        first_source,
        FakeValidator(revision="a" * 40),
        data_root=data_root,
        regulations=("mc",),
        project_root=project_root,
        progress=None,
    )

    second_source = FakeSource(
        indexes={"mc": _index_csv()},
        pastes={paste_url: AssertionError("must use archived raw bytes")},
    )
    validator = FakeValidator(revision="b" * 40)
    stats = sync_team_corpus(
        second_source,
        validator,
        data_root=data_root,
        regulations=("mc",),
        project_root=project_root,
        progress=None,
    )

    assert stats.processed == 1
    assert stats.downloaded == 0
    assert stats.revalidated == 1
    assert second_source.paste_calls == []
    assert validator.calls == [("gen9championsvgc2026regmc", raw.decode("utf-8"))]


def test_no_evs_team_is_valid_but_not_exact_truth_ready(tmp_path: Path):
    project_root, data_root = _external_root(tmp_path)
    paste_url = "https://pokepast.es/0123456789abcdef"
    source = FakeSource(
        indexes={"mc": _index_csv(evs="No")},
        pastes={paste_url: b"Team\n"},
    )

    stats = sync_team_corpus(
        source,
        FakeValidator(valid=True),
        data_root=data_root,
        regulations=("mc",),
        project_root=project_root,
        progress=None,
    )

    assert stats.valid == 1
    assert stats.exact_truth_ready == 0


def test_invalid_team_is_preserved_but_not_exact_truth_ready(tmp_path: Path):
    project_root, data_root = _external_root(tmp_path)
    paste_url = "https://pokepast.es/0123456789abcdef"
    raw = b"Invalid but parseable team\n"
    source = FakeSource(
        indexes={"mc": _index_csv()},
        pastes={paste_url: raw},
    )

    stats = sync_team_corpus(
        source,
        FakeValidator(valid=False),
        data_root=data_root,
        regulations=("mc",),
        project_root=project_root,
        progress=None,
    )

    assert stats.invalid == 1
    assert stats.exact_truth_ready == 0
    raw_path = (
        data_root
        / "teams"
        / "raw"
        / "mc"
        / "MC001"
        / "0123456789abcdef.txt"
    )
    assert raw_path.read_bytes() == raw

    layout = initialize_team_layout(data_root, project_root=project_root)
    with sqlite3.connect(layout.database) as connection:
        state, problems = connection.execute(
            """
            SELECT validation_state, validation_problems_json
            FROM teams
            WHERE regulation = 'mc' AND team_id = 'MC001'
            """
        ).fetchone()
    assert state == "invalid"
    assert "Example validation failure" in problems


def test_missing_pokepaste_is_indexed_without_network_fetch(tmp_path: Path):
    project_root, data_root = _external_root(tmp_path)
    source = FakeSource(
        indexes={"mc": _index_csv(paste_url="")},
        pastes={},
    )

    stats = sync_team_corpus(
        source,
        FakeValidator(),
        data_root=data_root,
        regulations=("mc",),
        project_root=project_root,
        progress=None,
    )

    assert stats.index_rows == 1
    assert stats.processed == 0
    assert source.paste_calls == []

    layout = initialize_team_layout(data_root, project_root=project_root)
    with sqlite3.connect(layout.database) as connection:
        state, ready = connection.execute(
            """
            SELECT validation_state, exact_truth_ready
            FROM teams
            WHERE regulation = 'mc' AND team_id = 'MC001'
            """
        ).fetchone()
    assert state == "missing_paste"
    assert ready == 0


def test_fetch_failure_is_recorded_without_losing_index_snapshot(tmp_path: Path):
    project_root, data_root = _external_root(tmp_path)
    paste_url = "https://pokepast.es/0123456789abcdef"
    source = FakeSource(
        indexes={"mc": _index_csv()},
        pastes={paste_url: TeamCorpusError("temporary failure")},
    )

    stats = sync_team_corpus(
        source,
        FakeValidator(),
        data_root=data_root,
        regulations=("mc",),
        project_root=project_root,
        progress=None,
    )

    assert stats.failed == 1
    assert team_corpus_status(
        data_root,
        project_root=project_root,
    )["fetch_failures"] == 1
    snapshots = list((data_root / "teams" / "index" / "mc").glob("*.csv"))
    assert len(snapshots) == 1


def test_http_source_constructs_sheet_and_pokepaste_requests():
    calls: list[tuple[str, str]] = []

    class Response:
        def __init__(self, payload: bytes):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self) -> bytes:
            return self.payload

    def opener(request, *, timeout):
        calls.append((request.full_url, request.headers["Accept"]))
        if "docs.google.com" in request.full_url:
            return Response(b"sheet")
        return Response(b"paste")

    source = VGCPastesHttpSource(
        request_delay_seconds=0,
        retries=1,
        opener=opener,
    )
    regulation = REGULATION_BY_KEY["mc"]

    assert source.fetch_index(regulation) == b"sheet"
    assert source.fetch_paste(
        "https://pokepast.es/0123456789abcdef"
    ) == b"paste"
    assert calls == [
        (vgcpastes_csv_url(regulation), "text/csv"),
        ("https://pokepast.es/0123456789abcdef/raw", "text/plain"),
    ]
