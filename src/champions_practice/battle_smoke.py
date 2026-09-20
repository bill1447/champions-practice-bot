"""Run one complete local Champions doubles battle through Showdown."""

from __future__ import annotations

import asyncio
from pathlib import Path

from champions_practice.client import close_player, wait_for_login
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.players import IntegrationBattlePlayer
from champions_practice.teams import SMOKE_TEAM


async def run_battle(timeout: float = 90.0) -> None:
    project_root = Path(__file__).resolve().parents[2]
    replay_dir = project_root / "runs" / "battle-smoke"
    replay_dir.mkdir(parents=True, exist_ok=True)

    player_one = IntegrationBattlePlayer(
        battle_format=CHAMPIONS_FORMAT,
        team=SMOKE_TEAM,
        max_concurrent_battles=1,
        accept_open_team_sheet=False,
        save_replays=str(replay_dir),
    )
    player_two = IntegrationBattlePlayer(
        battle_format=CHAMPIONS_FORMAT,
        team=SMOKE_TEAM,
        max_concurrent_battles=1,
        accept_open_team_sheet=False,
        save_replays=str(replay_dir),
    )

    try:
        wait_for_login(player_one)
        wait_for_login(player_two)
        print(f"Player 1: {player_one.username}")
        print(f"Player 2: {player_two.username}")
        print(f"Format:   {CHAMPIONS_FORMAT}")
        print("Starting one full Champions doubles battle...")

        await asyncio.wait_for(
            player_one.battle_against(player_two, n_battles=1),
            timeout=timeout,
        )

        if player_one.n_finished_battles != 1 or player_two.n_finished_battles != 1:
            raise RuntimeError(
                "Battle returned without both players recording one finished battle."
            )

        battle = next(iter(player_one.battles.values()))
        outcome = "P1 win" if battle.won else "P1 loss" if battle.lost else "tie"

        print()
        print("Battle complete.")
        print(f"Turns:    {battle.turn}")
        print(f"Outcome:  {outcome}")
        print(f"Replays:  {replay_dir}")
        print("RESULT:   full Champions battle path is healthy")
    finally:
        close_player(player_one)
        close_player(player_two)


def main() -> None:
    try:
        asyncio.run(run_battle())
    except TimeoutError as exc:
        raise SystemExit("ERROR: battle did not finish within 90 seconds") from exc


if __name__ == "__main__":
    main()
