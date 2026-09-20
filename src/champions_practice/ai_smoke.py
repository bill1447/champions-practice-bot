"""Run the v0 heuristic opponent against the deterministic baseline."""

from __future__ import annotations

import asyncio
from pathlib import Path

from champions_practice.client import close_player, wait_for_login
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.opponent import HeuristicOpponent
from champions_practice.players import IntegrationBattlePlayer
from champions_practice.teams import SMOKE_TEAM


async def run_battle(timeout: float = 90.0) -> None:
    project_root = Path(__file__).resolve().parents[2]
    replay_dir = project_root / "runs" / "ai-smoke"
    replay_dir.mkdir(parents=True, exist_ok=True)

    heuristic = HeuristicOpponent(
        battle_format=CHAMPIONS_FORMAT,
        team=SMOKE_TEAM,
        max_concurrent_battles=1,
        accept_open_team_sheet=False,
        save_replays=str(replay_dir),
        trace_choices=True,
        decision_trace_path=replay_dir / "decisions.jsonl",
    )
    baseline = IntegrationBattlePlayer(
        battle_format=CHAMPIONS_FORMAT,
        team=SMOKE_TEAM,
        max_concurrent_battles=1,
        accept_open_team_sheet=False,
        save_replays=str(replay_dir),
    )

    try:
        wait_for_login(heuristic)
        wait_for_login(baseline)

        print(f"Heuristic: {heuristic.username}")
        print(f"Baseline:  {baseline.username}")
        print(f"Format:    {CHAMPIONS_FORMAT}")
        print("Starting v0 heuristic-opponent battle...")

        await asyncio.wait_for(
            heuristic.battle_against(baseline, n_battles=1),
            timeout=timeout,
        )

        battle = next(iter(heuristic.battles.values()))
        outcome = "heuristic win" if battle.won else "heuristic loss" if battle.lost else "tie"

        print()
        print("Battle complete.")
        print(f"Turns:     {battle.turn}")
        print(f"Outcome:   {outcome}")
        print(f"Replays:   {replay_dir}")
        print(f"Decisions: {replay_dir / 'decisions.jsonl'}")
        print("RESULT:    heuristic opponent completed a legal Champions battle")
    finally:
        close_player(heuristic)
        close_player(baseline)


def main() -> None:
    try:
        asyncio.run(run_battle())
    except TimeoutError as exc:
        raise SystemExit("ERROR: heuristic battle did not finish within 90 seconds") from exc


if __name__ == "__main__":
    main()
