"""Structured JSONL traces for later battle review and UI work."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from poke_env.battle import AbstractBattle, Pokemon


def _pokemon_snapshot(mon: Pokemon | None) -> dict[str, Any] | None:
    if mon is None:
        return None

    return {
        "species": mon.species,
        "hp_fraction": round(float(mon.current_hp_fraction), 4),
        "fainted": bool(mon.fainted),
        "status": None if mon.status is None else str(mon.status),
        "boosts": dict(mon.boosts),
        "revealed_moves": sorted(mon.moves),
    }


def public_battle_snapshot(battle: AbstractBattle) -> dict[str, Any]:
    """Capture the public state needed for later decision review."""
    our_active = getattr(battle, "active_pokemon", [])
    opponent_active = getattr(battle, "opponent_active_pokemon", [])

    fields = sorted(str(field) for field in getattr(battle, "fields", {}))
    weather = sorted(str(item) for item in getattr(battle, "weather", {}))

    return {
        "turn": int(getattr(battle, "turn", 0)),
        "our_active": [_pokemon_snapshot(mon) for mon in our_active],
        "opponent_active": [_pokemon_snapshot(mon) for mon in opponent_active],
        "fields": fields,
        "weather": weather,
    }


class DecisionTrace:
    """Append machine-readable decision records to one JSONL file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            json.dump(record, handle, sort_keys=True)
            handle.write("\n")
