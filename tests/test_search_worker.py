from pathlib import Path
from types import SimpleNamespace

import pytest

from champions_practice.search_worker import (
    ShowdownSearchWorker,
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


def _present_faint_result():
    return {
        "outcomes": [{
            "state": {"sides": [
                {"pokemon": [
                    {"hp": 0, "fainted": True, "isActive": False},
                    {"hp": 110, "fainted": False, "isActive": True},
                ]},
                {"pokemon": []},
            ]},
            "hp": [0, 110],
        }],
        "reason": None,
    }


def test_present_hp_validator_admits_publicly_fainted_native_slot(monkeypatch):
    worker = object.__new__(ShowdownSearchWorker)
    result = _present_faint_result()
    monkeypatch.setattr(worker, "request", lambda *args, **kwargs: result)
    public = {"opponent": {"active": [
        {"fainted": True, "hp_percent": 0},
        {"fainted": False, "hp_percent": 88},
    ]}}
    admitted = worker.materialize_present_hypotheses(
        state={"fresh": True}, current_view=public, limit=4,
    )
    assert admitted["outcomes"][0]["hp"] == [0, 110]


@pytest.mark.parametrize("mutation", [
    "public-living", "public-positive-hp", "native-living", "native-active",
    "native-positive-hp", "reported-negative-hp", "reported-bool-hp",
    "reported-mismatched-hp", "living-declared-faint",
])
def test_present_hp_validator_rejects_false_zero_hp_authority(
    monkeypatch, mutation,
):
    worker = object.__new__(ShowdownSearchWorker)
    result = _present_faint_result()
    public = {"opponent": {"active": [
        {"fainted": True, "hp_percent": 0},
        {"fainted": False, "hp_percent": 88},
    ]}}
    mon = result["outcomes"][0]["state"]["sides"][0]["pokemon"][0]
    if mutation == "public-living":
        public["opponent"]["active"][0]["fainted"] = False
    elif mutation == "public-positive-hp":
        public["opponent"]["active"][0]["hp_percent"] = 1
    elif mutation == "native-living":
        mon["fainted"] = False
    elif mutation == "native-active":
        mon["isActive"] = True
    elif mutation == "native-positive-hp":
        mon["hp"] = 1
    elif mutation == "reported-negative-hp":
        result["outcomes"][0]["hp"][0] = -1
    elif mutation == "reported-bool-hp":
        result["outcomes"][0]["hp"][0] = False
    elif mutation == "reported-mismatched-hp":
        result["outcomes"][0]["hp"][0] = 1
    elif mutation == "living-declared-faint":
        public["opponent"]["active"][1]["fainted"] = True
    monkeypatch.setattr(worker, "request", lambda *args, **kwargs: result)
    with pytest.raises(RuntimeError, match="invalid present state"):
        worker.materialize_present_hypotheses(
            state={"fresh": True}, current_view=public, limit=4,
        )


def _own_speed_forensic():
    return {
        "stage": "after-native-unburden-removal",
        "slot": 0, "species": "Sneasler",
        "observed_speed": 133, "native_cached_speed": 266,
        "native_action_speed": 132, "native_stored_speed": 132,
        "speed_boost": 0, "status": None,
        "ability": "unburden", "item": None,
        "unburden_volatile": False, "trick_room": False,
        "terrain": "psychicterrain", "weather": None,
        "pre_removal_action_speed": 264,
    }


def test_present_native_speed_diagnostic_validated_without_candidate(monkeypatch):
    worker = object.__new__(ShowdownSearchWorker)
    data = {
        "outcomes": [], "reason": "own-unburden-speed-unresolved",
        "own_speed_diagnostic": _own_speed_forensic(),
    }
    monkeypatch.setattr(worker, "request", lambda *args, **kwargs: data)
    result = worker.materialize_present_hypotheses(
        state={"fresh": True}, current_view={"opponent": {"active": []}}, limit=2,
    )
    assert result["own_speed_diagnostic"]["native_action_speed"] == 132
    assert result["outcomes"] == []


@pytest.mark.parametrize("invalid", [
    "unexpected-key", "unbounded-species", "bool-as-speed", "bad-stage",
    "has-hypothesis", "private-opponent", "wrong-slot",
])
def test_present_native_speed_diagnostic_rejects_malformed_payload(monkeypatch, invalid):
    worker = object.__new__(ShowdownSearchWorker)
    detail = _own_speed_forensic()
    report = {
        "outcomes": [], "reason": "own-unburden-speed-unresolved",
        "own_speed_diagnostic": detail,
    }
    if invalid == "unexpected-key":
        detail["extra"] = 1
    elif invalid == "unbounded-species":
        detail["species"] = "X" * 100
    elif invalid == "bool-as-speed":
        detail["native_cached_speed"] = True
    elif invalid == "bad-stage":
        detail["stage"] = "oracle-source"
    elif invalid == "has-hypothesis":
        report["outcomes"] = [{"state": {}, "hp": [1, 1]}]
    elif invalid == "private-opponent":
        detail["opponent_set"] = {"item": "Private"}
    elif invalid == "wrong-slot":
        detail["slot"] = -1
    monkeypatch.setattr(worker, "request", lambda *args, **kwargs: report)
    expected = (
        "successful native worlds cannot carry speed failure diagnostics"
        if invalid == "has-hypothesis"
        else "own speed diagnostic"
    )
    with pytest.raises(RuntimeError, match=expected):
        worker.materialize_present_hypotheses(
            state={"fresh": True}, current_view={"opponent": {"active": []}}, limit=2,
        )
