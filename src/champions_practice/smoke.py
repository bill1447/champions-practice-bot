"""Live smoke test for the local Showdown + poke-env connection."""

from __future__ import annotations

from pathlib import Path

from poke_env.player import RandomPlayer

from champions_practice.client import close_player, wait_for_login
from champions_practice.config import CHAMPIONS_FORMAT, SHOWDOWN_WS_URL
from champions_practice.showdown import champions_format_present, default_showdown_root


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    showdown_root = default_showdown_root(project_root)

    print("Champions Practice Bot - connectivity smoke test")
    print(f"Format:   {CHAMPIONS_FORMAT}")
    print(f"Showdown: {SHOWDOWN_WS_URL}")

    if not champions_format_present(showdown_root):
        raise SystemExit(
            f"ERROR: {CHAMPIONS_FORMAT} was not found in "
            f"{showdown_root / 'config' / 'formats.ts'}"
        )

    print("Format:   found in local Showdown checkout")

    player = RandomPlayer(
        battle_format=CHAMPIONS_FORMAT,
        max_concurrent_battles=1,
    )

    try:
        wait_for_login(player)
        print(f"poke-env: connected as {player.username}")
        print("RESULT:   local Showdown connection is healthy")
    finally:
        close_player(player)


if __name__ == "__main__":
    main()
