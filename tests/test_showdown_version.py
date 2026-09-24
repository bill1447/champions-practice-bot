from pathlib import Path
import re


def test_showdown_version_pin_is_full_git_sha() -> None:
    root = Path(__file__).resolve().parents[1]
    pin = (root / "showdown-version.txt").read_text(encoding="utf-8").strip()

    assert re.fullmatch(r"[0-9a-f]{40}", pin)
