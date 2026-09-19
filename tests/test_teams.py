import re

from champions_practice.teams import SMOKE_TEAM, SMOKE_TEAM_ORDER


def _team_blocks() -> list[str]:
    return [block for block in SMOKE_TEAM.strip().split("\n\n") if block.strip()]


def test_smoke_team_has_six_members() -> None:
    assert len(_team_blocks()) == 6


def test_smoke_team_uses_66_stat_points_per_member() -> None:
    for block in _team_blocks():
        ev_line = next(line for line in block.splitlines() if line.startswith("EVs:"))
        points = [int(value) for value in re.findall(r"\d+", ev_line)]
        assert sum(points) == 66
        assert max(points) <= 32


def test_smoke_team_item_clause() -> None:
    items = [block.splitlines()[0].split(" @ ", 1)[1] for block in _team_blocks()]
    assert len(items) == len(set(items))


def test_smoke_preview_selects_four_unique_members() -> None:
    assert len(SMOKE_TEAM_ORDER) == 4
    assert len(set(SMOKE_TEAM_ORDER)) == 4
    assert all(1 <= index <= 6 for index in SMOKE_TEAM_ORDER)
