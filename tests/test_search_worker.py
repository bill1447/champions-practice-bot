from pathlib import Path
from types import SimpleNamespace

import pytest

from champions_practice.search_worker import (
    verify_showdown_checkout,
    write_showdown_build_stamp,
)


PIN = "a5df8274e85b0889bf2a9b3422a08b39732374fc"


def _runtime_tree(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    showdown = root / "external" / "pokemon-showdown"
    (showdown / "dist" / "sim").mkdir(parents=True)
    (showdown / "dist" / "sim" / "battle.js").write_text(
        "module.exports = {};\n",
        encoding="utf-8",
    )
    (showdown / "dist" / "sim" / "teams.js").write_text(
        "module.exports = {};\n",
        encoding="utf-8",
    )
    (root / "showdown-version.txt").write_text(PIN + "\n", encoding="utf-8")
    return root


def test_showdown_runtime_verification_accepts_pinned_clean_checkout(
    tmp_path,
    monkeypatch,
) -> None:
    root = _runtime_tree(tmp_path)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if "rev-parse" in args:
            return SimpleNamespace(returncode=0, stdout=PIN + "\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("champions_practice.search_worker.subprocess.run", fake_run)

    stamp = write_showdown_build_stamp(root)
    actual = verify_showdown_checkout(root)
    cached = verify_showdown_checkout(root)

    assert stamp["source_sha"] == PIN
    assert len(stamp["dist_sha256"]) == 64
    assert actual == PIN
    assert cached == PIN
    assert len(calls) == 6


def test_showdown_runtime_verification_rejects_wrong_revision(
    tmp_path,
    monkeypatch,
) -> None:
    root = _runtime_tree(tmp_path)
    wrong = "f10d679000000000000000000000000000000000"

    monkeypatch.setattr(
        "champions_practice.search_worker.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=wrong + "\n",
            stderr="",
        ),
    )

    with pytest.raises(RuntimeError, match="revision mismatch"):
        verify_showdown_checkout(root)


def test_showdown_runtime_verification_rejects_tracked_modifications(
    tmp_path,
    monkeypatch,
) -> None:
    root = _runtime_tree(tmp_path)
    calls = 0

    def fake_run(args, **kwargs):
        nonlocal calls
        calls += 1
        if "rev-parse" in args:
            return SimpleNamespace(returncode=0, stdout=PIN + "\n", stderr="")
        return SimpleNamespace(
            returncode=1 if calls == 2 else 0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr("champions_practice.search_worker.subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="tracked local modifications"):
        verify_showdown_checkout(root)



def test_showdown_runtime_verification_rejects_modified_built_dist(
    tmp_path,
    monkeypatch,
) -> None:
    root = _runtime_tree(tmp_path)

    def fake_run(args, **kwargs):
        if "rev-parse" in args:
            return SimpleNamespace(returncode=0, stdout=PIN + "\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("champions_practice.search_worker.subprocess.run", fake_run)

    write_showdown_build_stamp(root)
    battle = root / "external" / "pokemon-showdown" / "dist" / "sim" / "battle.js"
    battle.write_text("tampered runtime\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="built runtime hash mismatch"):
        verify_showdown_checkout(root)
