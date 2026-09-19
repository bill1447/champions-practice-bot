from champions_practice.config import CHAMPIONS_FORMAT, SHOWDOWN_WS_URL


def test_champions_format_is_reg_mc() -> None:
    assert CHAMPIONS_FORMAT == "gen9championsvgc2026regmc"


def test_local_showdown_endpoint() -> None:
    assert SHOWDOWN_WS_URL == "ws://localhost:8000/showdown/websocket"
