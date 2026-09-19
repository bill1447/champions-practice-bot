from pathlib import Path

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.showdown import champions_format_present


def test_champions_format_present(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "formats.ts").write_text(
        f'{{ name: "test", id: "{CHAMPIONS_FORMAT}" }}',
        encoding="utf-8",
    )

    assert champions_format_present(tmp_path)


def test_champions_format_missing(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "formats.ts").write_text("other format", encoding="utf-8")

    assert not champions_format_present(tmp_path)
