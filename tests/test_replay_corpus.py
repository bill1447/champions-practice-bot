from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from champions_practice.replay_corpus import (
    DEFAULT_FORMAT,
    DownloadConfig,
    ReplayCorpusError,
    ShowdownReplaySource,
    _format_duration,
    _progress_message,
    _timing_snapshot,
    corpus_status,
    download_replay_corpus,
    ensure_external_data_root,
    initialize_layout,
)


def _search_row(
    replay_id: str,
    *,
    uploadtime: int,
    rating: int = 1500,
) -> dict[str, Any]:
    return {
        "id": replay_id,
        "format": "[Gen 9] Champions 2026 Reg M-C",
        "players": ["Alice", "Bob"],
        "rating": rating,
        "uploadtime": uploadtime,
    }


def _detail_bytes(
    replay_id: str,
    *,
    uploadtime: int,
    rating: int = 1500,
    extra_space: bool = False,
) -> bytes:
    detail = {
        "id": replay_id,
        "format": "[Gen 9] Champions 2026 Reg M-C",
        "players": ["Alice", "Bob"],
        "rating": rating,
        "uploadtime": uploadtime,
        "log": "|player|p1|Alice||1500\n|player|p2|Bob||1500\n|win|Alice\n",
    }
    if extra_space:
        return json.dumps(detail, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    return json.dumps(detail, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class _FakeHttpResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def read(self) -> bytes:
        return self.payload


class FakeReplaySource:
    def __init__(
        self,
        *,
        pages: dict[int | None, list[dict[str, Any]]],
        details: dict[str, bytes | BaseException],
    ) -> None:
        self.pages = pages
        self.details = details
        self.search_calls: list[tuple[str, int | None]] = []
        self.fetch_calls: list[str] = []

    def search(
        self,
        *,
        format_id: str,
        before: int | None,
    ) -> list[dict[str, Any]]:
        self.search_calls.append((format_id, before))
        return list(self.pages.get(before, []))

    def fetch_replay(self, replay_id: str) -> bytes:
        self.fetch_calls.append(replay_id)
        result = self.details[replay_id]
        if isinstance(result, BaseException):
            raise result
        return result


def _external_root(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    data_root = tmp_path / "external-data"
    return project_root, data_root


def test_download_timing_snapshot_reports_rate_and_eta():
    elapsed, rate, eta = _timing_snapshot(
        started_at=100.0,
        now=160.0,
        downloaded=120,
        target=600,
    )

    assert elapsed == 60.0
    assert rate == 120.0
    assert eta == 240.0


def test_download_timing_snapshot_handles_unlimited_run():
    elapsed, rate, eta = _timing_snapshot(
        started_at=10.0,
        now=40.0,
        downloaded=60,
        target=0,
    )

    assert elapsed == 30.0
    assert rate == 120.0
    assert eta is None


def test_progress_message_includes_elapsed_rate_and_eta():
    message = _progress_message(
        downloaded=100,
        replay_total=250,
        target=5000,
        started_at=0.0,
        now=50.0,
    )

    assert message == (
        "Downloaded 100/5000 this run (250 total indexed) | "
        "elapsed 00:00:50 | 120.0 replays/min | ETA 00:40:50"
    )


@pytest.mark.parametrize(
    ("seconds", "expected"),
    (
        (0, "00:00:00"),
        (59.6, "00:01:00"),
        (3661, "01:01:01"),
    ),
)
def test_format_duration(seconds: float, expected: str):
    assert _format_duration(seconds) == expected


def test_showdown_source_uses_documented_search_and_replay_json_urls():
    replay_id = f"{DEFAULT_FORMAT}-42"
    row = _search_row(replay_id, uploadtime=42)
    raw_detail = _detail_bytes(replay_id, uploadtime=42)
    calls: list[tuple[str, float]] = []

    def opener(request, *, timeout):
        calls.append((request.full_url, timeout))
        if "search.json" in request.full_url:
            return _FakeHttpResponse(json.dumps([row]).encode("utf-8"))
        return _FakeHttpResponse(raw_detail)

    source = ShowdownReplaySource(
        request_delay_seconds=0,
        timeout_seconds=7.5,
        retries=1,
        opener=opener,
    )

    rows = source.search(format_id=DEFAULT_FORMAT, before=123456)
    detail = source.fetch_replay(replay_id)

    assert rows == [row]
    assert detail == raw_detail
    assert calls == [
        (
            "https://replay.pokemonshowdown.com/search.json?"
            f"format={DEFAULT_FORMAT}&before=123456",
            7.5,
        ),
        (
            f"https://replay.pokemonshowdown.com/{replay_id}.json",
            7.5,
        ),
    ]


def test_replay_corpus_rejects_data_inside_repository(tmp_path: Path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    nested = project_root / "data" / "replays"

    with pytest.raises(ReplayCorpusError, match="outside the source repository"):
        ensure_external_data_root(nested, project_root=project_root)


def test_layout_matches_external_corpus_shape(tmp_path: Path):
    project_root, data_root = _external_root(tmp_path)

    layout = initialize_layout(data_root, project_root=project_root)

    assert layout.root == data_root.resolve()
    assert layout.raw.is_dir()
    assert layout.manifests.is_dir()
    assert layout.processed.is_dir()
    assert layout.trajectories.is_dir()
    assert layout.teams.is_dir()
    assert layout.models.is_dir()
    assert layout.cache.is_dir()
    assert layout.database == layout.manifests / "replays.sqlite3"


def test_download_preserves_raw_json_bytes_and_indexes_metadata(tmp_path: Path):
    project_root, data_root = _external_root(tmp_path)
    replay_id = f"{DEFAULT_FORMAT}-100"
    raw = _detail_bytes(replay_id, uploadtime=100, extra_space=True)
    source = FakeReplaySource(
        pages={None: [_search_row(replay_id, uploadtime=100)]},
        details={replay_id: raw},
    )

    stats = download_replay_corpus(
        source,
        config=DownloadConfig(data_root=data_root, max_replays=10),
        project_root=project_root,
        progress=None,
    )

    archived = data_root / "raw" / DEFAULT_FORMAT / f"{replay_id}.json"
    assert archived.read_bytes() == raw
    assert stats.downloaded == 1
    assert stats.exhausted
    assert source.fetch_calls == [replay_id]

    status = corpus_status(
        data_root,
        format_id=DEFAULT_FORMAT,
        project_root=project_root,
    )
    assert status["replays"] == 1
    assert status["raw_bytes"] == len(raw)
    assert status["failures"] == 0
    assert status["checkpoint"]["exhausted"] is True


def test_existing_raw_file_is_reindexed_without_redownload(tmp_path: Path):
    project_root, data_root = _external_root(tmp_path)
    replay_id = f"{DEFAULT_FORMAT}-101"
    raw = _detail_bytes(replay_id, uploadtime=101)
    layout = initialize_layout(data_root, project_root=project_root)
    path = layout.raw / DEFAULT_FORMAT / f"{replay_id}.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)

    source = FakeReplaySource(
        pages={None: [_search_row(replay_id, uploadtime=101)]},
        details={replay_id: AssertionError("must not redownload")},
    )

    stats = download_replay_corpus(
        source,
        config=DownloadConfig(data_root=data_root),
        project_root=project_root,
        progress=None,
    )

    assert stats.downloaded == 0
    assert stats.already_present == 1
    assert source.fetch_calls == []
    assert corpus_status(
        data_root,
        project_root=project_root,
    )["replays"] == 1


def test_51_row_page_uses_oldest_uploadtime_as_resume_cursor(tmp_path: Path):
    project_root, data_root = _external_root(tmp_path)
    first_page = [
        _search_row(f"{DEFAULT_FORMAT}-{2000 - index}", uploadtime=2000 - index)
        for index in range(51)
    ]
    next_before = first_page[-1]["uploadtime"]
    second_id = f"{DEFAULT_FORMAT}-1900"
    second_page = [_search_row(second_id, uploadtime=1900)]

    details = {
        row["id"]: _detail_bytes(row["id"], uploadtime=row["uploadtime"])
        for row in first_page + second_page
    }
    source = FakeReplaySource(
        pages={None: first_page, next_before: second_page},
        details=details,
    )

    stats = download_replay_corpus(
        source,
        config=DownloadConfig(data_root=data_root, max_replays=0),
        project_root=project_root,
        progress=None,
    )

    assert source.search_calls == [
        (DEFAULT_FORMAT, None),
        (DEFAULT_FORMAT, next_before),
    ]
    assert stats.downloaded == 52
    assert stats.pages_completed == 2
    assert stats.exhausted


def test_mid_page_limit_does_not_advance_checkpoint(tmp_path: Path):
    project_root, data_root = _external_root(tmp_path)
    rows = [
        _search_row(f"{DEFAULT_FORMAT}-{300 - index}", uploadtime=300 - index)
        for index in range(5)
    ]
    details = {
        row["id"]: _detail_bytes(row["id"], uploadtime=row["uploadtime"])
        for row in rows
    }

    first_source = FakeReplaySource(pages={None: rows}, details=details)
    first = download_replay_corpus(
        first_source,
        config=DownloadConfig(data_root=data_root, max_replays=2),
        project_root=project_root,
        progress=None,
    )

    assert first.downloaded == 2
    assert not first.exhausted
    assert first.next_before is None

    second_source = FakeReplaySource(pages={None: rows}, details=details)
    second = download_replay_corpus(
        second_source,
        config=DownloadConfig(data_root=data_root, max_replays=10),
        project_root=project_root,
        progress=None,
    )

    assert second_source.search_calls[0] == (DEFAULT_FORMAT, None)
    assert second.downloaded == 3
    assert second.already_present == 2
    assert second.exhausted


def test_completed_checkpoint_avoids_network_on_resume(tmp_path: Path):
    project_root, data_root = _external_root(tmp_path)
    replay_id = f"{DEFAULT_FORMAT}-400"
    details = {replay_id: _detail_bytes(replay_id, uploadtime=400)}
    source = FakeReplaySource(
        pages={None: [_search_row(replay_id, uploadtime=400)]},
        details=details,
    )
    download_replay_corpus(
        source,
        config=DownloadConfig(data_root=data_root),
        project_root=project_root,
        progress=None,
    )

    resumed = FakeReplaySource(
        pages={},
        details={},
    )
    stats = download_replay_corpus(
        resumed,
        config=DownloadConfig(data_root=data_root),
        project_root=project_root,
        progress=None,
    )

    assert resumed.search_calls == []
    assert resumed.fetch_calls == []
    assert stats.exhausted
    assert stats.downloaded == 0


def test_restart_search_rechecks_newest_without_redownloading_existing(tmp_path: Path):
    project_root, data_root = _external_root(tmp_path)
    old_id = f"{DEFAULT_FORMAT}-500"
    old_detail = _detail_bytes(old_id, uploadtime=500)
    first_source = FakeReplaySource(
        pages={None: [_search_row(old_id, uploadtime=500)]},
        details={old_id: old_detail},
    )
    download_replay_corpus(
        first_source,
        config=DownloadConfig(data_root=data_root),
        project_root=project_root,
        progress=None,
    )

    new_id = f"{DEFAULT_FORMAT}-501"
    source = FakeReplaySource(
        pages={
            None: [
                _search_row(new_id, uploadtime=501),
                _search_row(old_id, uploadtime=500),
            ]
        },
        details={
            new_id: _detail_bytes(new_id, uploadtime=501),
            old_id: AssertionError("must not redownload"),
        },
    )
    stats = download_replay_corpus(
        source,
        config=DownloadConfig(
            data_root=data_root,
            restart_search=True,
        ),
        project_root=project_root,
        progress=None,
    )

    assert stats.downloaded == 1
    assert stats.already_present == 1
    assert source.fetch_calls == [new_id]


def test_restart_search_stops_at_first_all_known_page(tmp_path: Path):
    project_root, data_root = _external_root(tmp_path)
    first_page = [
        _search_row(f"{DEFAULT_FORMAT}-{900 - index}", uploadtime=900 - index)
        for index in range(51)
    ]
    next_before = first_page[-1]["uploadtime"]
    tail_id = f"{DEFAULT_FORMAT}-800"
    tail_page = [_search_row(tail_id, uploadtime=800)]
    details = {
        row["id"]: _detail_bytes(row["id"], uploadtime=row["uploadtime"])
        for row in first_page + tail_page
    }
    initial = FakeReplaySource(
        pages={None: first_page, next_before: tail_page},
        details=details,
    )
    download_replay_corpus(
        initial,
        config=DownloadConfig(data_root=data_root, max_replays=0),
        project_root=project_root,
        progress=None,
    )

    refresh = FakeReplaySource(
        pages={None: first_page},
        details={},
    )
    stats = download_replay_corpus(
        refresh,
        config=DownloadConfig(
            data_root=data_root,
            restart_search=True,
            max_replays=0,
        ),
        project_root=project_root,
        progress=None,
    )

    assert refresh.search_calls == [(DEFAULT_FORMAT, None)]
    assert refresh.fetch_calls == []
    assert stats.downloaded == 0
    assert stats.already_present == 51
    assert stats.exhausted


def test_failed_replay_is_recorded_and_non_strict_run_continues(tmp_path: Path):
    project_root, data_root = _external_root(tmp_path)
    bad_id = f"{DEFAULT_FORMAT}-600"
    good_id = f"{DEFAULT_FORMAT}-599"
    source = FakeReplaySource(
        pages={
            None: [
                _search_row(bad_id, uploadtime=600),
                _search_row(good_id, uploadtime=599),
            ]
        },
        details={
            bad_id: ReplayCorpusError("gone"),
            good_id: _detail_bytes(good_id, uploadtime=599),
        },
    )

    stats = download_replay_corpus(
        source,
        config=DownloadConfig(data_root=data_root, strict=False),
        project_root=project_root,
        progress=None,
    )

    assert stats.failed == 1
    assert stats.downloaded == 1
    assert corpus_status(
        data_root,
        project_root=project_root,
    )["failures"] == 1


def test_failed_replay_is_retried_before_completed_checkpoint_short_circuit(
    tmp_path: Path,
):
    project_root, data_root = _external_root(tmp_path)
    bad_id = f"{DEFAULT_FORMAT}-650"
    first_source = FakeReplaySource(
        pages={None: [_search_row(bad_id, uploadtime=650)]},
        details={bad_id: ReplayCorpusError("temporary")},
    )
    first = download_replay_corpus(
        first_source,
        config=DownloadConfig(data_root=data_root),
        project_root=project_root,
        progress=None,
    )
    assert first.exhausted
    assert first.failed == 1

    recovered = _detail_bytes(bad_id, uploadtime=650)
    second_source = FakeReplaySource(
        pages={},
        details={bad_id: recovered},
    )
    second = download_replay_corpus(
        second_source,
        config=DownloadConfig(data_root=data_root),
        project_root=project_root,
        progress=None,
    )

    assert second_source.fetch_calls == [bad_id]
    assert second_source.search_calls == []
    assert second.downloaded == 1
    status = corpus_status(
        data_root,
        project_root=project_root,
    )
    assert status["replays"] == 1
    assert status["failures"] == 0


def test_strict_failure_stops_without_advancing_page_checkpoint(tmp_path: Path):
    project_root, data_root = _external_root(tmp_path)
    bad_id = f"{DEFAULT_FORMAT}-700"
    source = FakeReplaySource(
        pages={None: [_search_row(bad_id, uploadtime=700)]},
        details={bad_id: ReplayCorpusError("bad replay")},
    )

    with pytest.raises(ReplayCorpusError, match="bad replay"):
        download_replay_corpus(
            source,
            config=DownloadConfig(
                data_root=data_root,
                strict=True,
            ),
            project_root=project_root,
            progress=None,
        )

    layout = initialize_layout(data_root, project_root=project_root)
    with sqlite3.connect(layout.database) as connection:
        checkpoint = connection.execute(
            "SELECT before_uploadtime FROM checkpoints WHERE format_id = ?",
            (DEFAULT_FORMAT,),
        ).fetchone()
        failures = connection.execute(
            "SELECT attempts FROM failures WHERE replay_id = ?",
            (bad_id,),
        ).fetchone()

    assert checkpoint is None
    assert failures == (1,)


@pytest.mark.parametrize(
    "format_id",
    (
        "../escape",
        "GEN9CHAMPIONSVGC2026REGMC",
        "gen9_champions",
        "",
    ),
)
def test_invalid_format_ids_fail_before_io(tmp_path: Path, format_id: str):
    _, data_root = _external_root(tmp_path)
    with pytest.raises(ValueError):
        DownloadConfig(data_root=data_root, format_id=format_id)


def test_invalid_existing_raw_is_replaced_by_fresh_valid_download(tmp_path: Path):
    project_root, data_root = _external_root(tmp_path)
    replay_id = f"{DEFAULT_FORMAT}-800"
    layout = initialize_layout(data_root, project_root=project_root)
    path = layout.raw / DEFAULT_FORMAT / f"{replay_id}.json"
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")

    valid = _detail_bytes(replay_id, uploadtime=800)
    source = FakeReplaySource(
        pages={None: [_search_row(replay_id, uploadtime=800)]},
        details={replay_id: valid},
    )
    stats = download_replay_corpus(
        source,
        config=DownloadConfig(data_root=data_root),
        project_root=project_root,
        progress=None,
    )

    assert stats.downloaded == 1
    assert path.read_bytes() == valid


def test_truncated_utf32_existing_raw_is_replaced_by_fresh_valid_download(
    tmp_path: Path,
):
    project_root, data_root = _external_root(tmp_path)
    replay_id = f"{DEFAULT_FORMAT}-801"
    layout = initialize_layout(data_root, project_root=project_root)
    path = layout.raw / DEFAULT_FORMAT / f"{replay_id}.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\x00\x00\x00{\x00\x00\x00")

    valid = _detail_bytes(replay_id, uploadtime=801)
    source = FakeReplaySource(
        pages={None: [_search_row(replay_id, uploadtime=801)]},
        details={replay_id: valid},
    )
    stats = download_replay_corpus(
        source,
        config=DownloadConfig(data_root=data_root),
        project_root=project_root,
        progress=None,
    )

    assert source.fetch_calls == [replay_id]
    assert stats.downloaded == 1
    assert path.read_bytes() == valid
