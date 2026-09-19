"""Small helpers shared by local poke-env commands."""

from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError as FutureTimeoutError

from poke_env.player import Player

from champions_practice.config import SHOWDOWN_WS_URL


def wait_for_login(player: Player, timeout: float = 10.0) -> None:
    """Wait until a poke-env player has logged into the local Showdown server."""
    future = asyncio.run_coroutine_threadsafe(
        player.ps_client.logged_in.wait(),
        player.ps_client.loop,
    )
    try:
        future.result(timeout=timeout)
    except FutureTimeoutError as exc:
        raise RuntimeError(
            f"Timed out connecting to local Showdown at {SHOWDOWN_WS_URL}"
        ) from exc


def close_player(player: Player, timeout: float = 5.0) -> None:
    """Best-effort shutdown of a poke-env websocket client."""
    future = asyncio.run_coroutine_threadsafe(
        player.ps_client._stop_listening(),
        player.ps_client.loop,
    )
    try:
        future.result(timeout=timeout)
    except Exception:
        # Commands are exiting immediately afterward. A socket that is already closing
        # should not hide the result of the actual smoke/integration test.
        pass
