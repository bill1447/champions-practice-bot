"""Helpers for verifying the local Pokémon Showdown checkout."""

from __future__ import annotations

from pathlib import Path

from champions_practice.config import CHAMPIONS_FORMAT_NAME


def champions_format_present(showdown_root: Path) -> bool:
    """Return whether the configured Champions format is present upstream.

    Showdown generates the battle format id from the human-readable format name.
    The literal id therefore does not appear in config/formats.ts.
    """
    formats_file = showdown_root / "config" / "formats.ts"
    if not formats_file.is_file():
        return False

    contents = formats_file.read_text(encoding="utf-8")
    return CHAMPIONS_FORMAT_NAME in contents


def default_showdown_root(project_root: Path) -> Path:
    return project_root / "external" / "pokemon-showdown"
