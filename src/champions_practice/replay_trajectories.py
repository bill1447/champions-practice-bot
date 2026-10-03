"""Deterministic public replay trajectory extraction for policy learning.

Only archived public replay logs are consumed. Replay inputlog data is deliberately
ignored: it can contain exact submitted commands that are not generally available
from public replays. The extractor records public decision-boundary state plus only
action identity that is observable or conservatively reconstructible.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from champions_practice.replay_corpus import (
    DATA_ROOT_ENV,
    DEFAULT_FORMAT,
    ReplayCorpusError,
    _connect_manifest,
    _utc_now,
    _validate_public_id,
    ensure_external_data_root,
    initialize_layout,
)


TRAJECTORY_SCHEMA = "showdown-public-trajectory-v1"
PUBLIC_STATE_SCHEMA = "showdown-replay-public-state-v1"
JOINT_ACTION_SCHEMA = "showdown-replay-joint-action-v1"
DEFAULT_MAX_REPLAYS = 5000
_SLOT_RE = re.compile(r"^(p[12])([a-z])(?::|$)")


class TrajectoryExtractionError(RuntimeError):
    """A replay could not be converted without weakening label authority."""


@dataclass(frozen=True)
class TrajectoryConfig:
    data_root: Path
    format_id: str = DEFAULT_FORMAT
    max_replays: int = DEFAULT_MAX_REPLAYS
    refresh: bool = False
    strict: bool = False

    def __post_init__(self) -> None:
        _validate_public_id(self.format_id, label="format")
        if (
            isinstance(self.max_replays, bool)
            or not isinstance(self.max_replays, int)
            or self.max_replays < 0
        ):
            raise ValueError("max_replays must be a non-negative integer")


@dataclass(frozen=True)
class TrajectoryStats:
    format_id: str
    replay_rows_examined: int
    extracted: int
    already_current: int
    failed: int
    decision_boundaries: int
    complete_joint_labels: int
    incomplete_joint_labels: int


def _to_id(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _effect_id(value: object) -> str:
    text = str(value or "").strip()
    match = re.match(r"^(?:move|ability|item):\s*(.*)$", text, re.IGNORECASE)
    if match:
        text = match.group(1)
    return _to_id(text)


def _slot_ref(value: object) -> tuple[str, int] | None:
    match = _SLOT_RE.match(str(value or ""))
    if match is None:
        return None
    return match.group(1), ord(match.group(2)) - ord("a") + 1


def _side_ref(value: object) -> str | None:
    text = str(value or "")
    if text.startswith("p1"):
        return "p1"
    if text.startswith("p2"):
        return "p2"
    return None


def _species_from_details(value: object) -> str:
    return str(value or "").split(",", 1)[0].strip()


def _condition(value: object) -> dict[str, Any]:
    text = str(value or "").strip()
    if not text:
        return {
            "condition": None,
            "hp_percent": None,
            "status": None,
            "fainted": False,
        }
    if text == "0 fnt" or text.endswith(" fnt"):
        return {
            "condition": text,
            "hp_percent": 0.0,
            "status": None,
            "fainted": True,
        }

    fields = text.split()
    fraction = fields[0]
    status = _to_id(fields[1]) if len(fields) > 1 else None
    hp_percent: float | None = None
    if "/" in fraction:
        current_text, maximum_text = fraction.split("/", 1)
        try:
            current = float(current_text)
            maximum = float(maximum_text)
        except ValueError:
            pass
        else:
            if maximum > 0:
                hp_percent = round(current * 100.0 / maximum, 3)
    elif fraction.endswith("%"):
        try:
            hp_percent = float(fraction[:-1])
        except ValueError:
            pass
    return {
        "condition": text,
        "hp_percent": hp_percent,
        "status": status or None,
        "fainted": hp_percent == 0.0,
    }


def _empty_side() -> dict[str, Any]:
    return {
        "name": None,
        "preview_species": [],
        "active": [None, None],
        "side_conditions": set(),
        "revealed": {},
    }


class _PublicState:
    """Replay-only reducer for facts already public in the log prefix."""

    def __init__(self) -> None:
        self.turn = 0
        self.gametype: str | None = None
        self.players = {"p1": _empty_side(), "p2": _empty_side()}
        self.weather: str | None = None
        self.field_conditions: set[str] = set()

    def _revealed(self, side: str, species: str) -> dict[str, Any]:
        key = _to_id(species)
        revealed = self.players[side]["revealed"]
        if key not in revealed:
            revealed[key] = {
                "species": species,
                "seen": False,
                "moves": set(),
                "items": set(),
                "abilities": set(),
                "hp_percent": None,
                "status": None,
                "fainted": False,
            }
        return revealed[key]

    def _active(self, actor: object) -> tuple[str, int, dict[str, Any]] | None:
        slot = _slot_ref(actor)
        if slot is None:
            return None
        side, slot_number = slot
        if slot_number not in {1, 2}:
            return None
        active = self.players[side]["active"][slot_number - 1]
        if not isinstance(active, dict):
            return None
        return side, slot_number, active

    def _sync_revealed(self, side: str, active: dict[str, Any]) -> None:
        species = active.get("base_species")
        if not isinstance(species, str) or not species:
            return
        revealed = self._revealed(side, species)
        revealed["seen"] = True
        for key in ("hp_percent", "status", "fainted"):
            revealed[key] = active.get(key)

    def _field_event(self, event: str, parts: list[str]) -> bool:
        if event in {"-sidestart", "-sideend"} and len(parts) >= 4:
            side = _side_ref(parts[2])
            condition_id = _effect_id(parts[3])
            if side is not None and condition_id:
                conditions = self.players[side]["side_conditions"]
                if event == "-sidestart":
                    conditions.add(condition_id)
                else:
                    conditions.discard(condition_id)
            return True
        if event == "-weather" and len(parts) >= 3:
            weather = _effect_id(parts[2])
            self.weather = None if weather in {"", "none"} else weather
            return True
        if event in {"-fieldstart", "-fieldend"} and len(parts) >= 3:
            field_id = _effect_id(parts[2])
            if field_id:
                if event == "-fieldstart":
                    self.field_conditions.add(field_id)
                else:
                    self.field_conditions.discard(field_id)
            return True
        if event == "-clearallboost":
            for side in ("p1", "p2"):
                for active in self.players[side]["active"]:
                    if isinstance(active, dict):
                        active["boosts"] = {}
            return True
        return False

    def apply(self, line: str) -> None:
        if not line.startswith("|"):
            return
        parts = line.split("|")
        if len(parts) < 2:
            return
        event = parts[1]

        if event == "player" and len(parts) >= 4 and parts[2] in self.players:
            self.players[parts[2]]["name"] = parts[3]
            return
        if event == "gametype" and len(parts) >= 3:
            self.gametype = _to_id(parts[2]) or None
            return
        if event == "poke" and len(parts) >= 4 and parts[2] in self.players:
            species = _species_from_details(parts[3])
            if species:
                self.players[parts[2]]["preview_species"].append(species)
                self._revealed(parts[2], species)
            return
        if event == "turn" and len(parts) >= 3:
            try:
                self.turn = int(parts[2])
            except ValueError:
                pass
            return
        if self._field_event(event, parts):
            return

        if event in {"switch", "drag", "replace"} and len(parts) >= 5:
            slot = _slot_ref(parts[2])
            if slot is None:
                return
            side, slot_number = slot
            if slot_number not in {1, 2}:
                return
            species = _species_from_details(parts[3])
            active = {
                "base_species": species,
                "visible_species": species,
                **_condition(parts[4]),
                "boosts": {},
            }
            self.players[side]["active"][slot_number - 1] = active
            self._sync_revealed(side, active)
            return

        active_info = self._active(parts[2] if len(parts) >= 3 else "")
        if active_info is None:
            return
        side, _, active = active_info
        revealed = self._revealed(side, active["base_species"])

        if event in {"-damage", "-heal", "-sethp"} and len(parts) >= 4:
            active.update(_condition(parts[3]))
            self._sync_revealed(side, active)
        elif event == "-status" and len(parts) >= 4:
            status = _to_id(parts[3]) or None
            active["status"] = status
            revealed["status"] = status
        elif event == "-curestatus":
            active["status"] = None
            revealed["status"] = None
        elif event == "faint":
            active["hp_percent"] = 0.0
            active["fainted"] = True
            revealed["hp_percent"] = 0.0
            revealed["fainted"] = True
        elif event == "move" and len(parts) >= 4:
            called = any(
                str(value).strip().lower().startswith("[from]")
                for value in parts[5:]
            )
            if not called:
                move_id = _to_id(parts[3])
                if move_id:
                    revealed["moves"].add(move_id)
        elif event == "cant" and len(parts) >= 5:
            move_id = _to_id(parts[4])
            if move_id:
                revealed["moves"].add(move_id)
        elif event in {"-item", "-enditem"} and len(parts) >= 4:
            item_id = _to_id(parts[3])
            if item_id:
                revealed["items"].add(item_id)
        elif event == "-mega" and len(parts) >= 5:
            item_id = _to_id(parts[4])
            if item_id:
                revealed["items"].add(item_id)
        elif event == "-ability" and len(parts) >= 4:
            ability_id = _to_id(parts[3])
            if ability_id:
                revealed["abilities"].add(ability_id)
        elif event in {"detailschange", "-formechange"} and len(parts) >= 4:
            species = _species_from_details(parts[3])
            if species:
                active["visible_species"] = species
        elif event in {"-boost", "-unboost", "-setboost"} and len(parts) >= 5:
            stat = _to_id(parts[3])
            try:
                amount = int(parts[4])
            except ValueError:
                return
            boosts = active["boosts"]
            if event == "-boost":
                boosts[stat] = int(boosts.get(stat, 0)) + amount
            elif event == "-unboost":
                boosts[stat] = int(boosts.get(stat, 0)) - amount
            else:
                boosts[stat] = amount
        elif event == "-clearboost":
            active["boosts"] = {}
        elif event == "-clearpositiveboost":
            active["boosts"] = {
                stat: value
                for stat, value in active["boosts"].items()
                if value < 0
            }
        elif event == "-clearnegativeboost":
            active["boosts"] = {
                stat: value
                for stat, value in active["boosts"].items()
                if value > 0
            }

    def snapshot(self) -> dict[str, Any]:
        sides: dict[str, Any] = {}
        for side in ("p1", "p2"):
            source = self.players[side]
            revealed_rows = []
            for entry in source["revealed"].values():
                row = copy.deepcopy(entry)
                row["moves"] = sorted(row["moves"])
                row["items"] = sorted(row["items"])
                row["abilities"] = sorted(row["abilities"])
                revealed_rows.append(row)
            revealed_rows.sort(key=lambda row: _to_id(row["species"]))
            sides[side] = {
                "name": source["name"],
                "preview_species": list(source["preview_species"]),
                "active": copy.deepcopy(source["active"]),
                "side_conditions": sorted(source["side_conditions"]),
                "revealed": revealed_rows,
            }
        return {
            "schema": PUBLIC_STATE_SCHEMA,
            "turn": self.turn,
            "gametype": self.gametype,
            "field": {
                "weather": self.weather,
                "conditions": sorted(self.field_conditions),
            },
            "sides": sides,
        }


class _TurnLabels:
    """Collect action identity without claiming unavailable hidden commands."""

    _FORCED_SWITCH_ITEMS = {"ejectpack", "ejectbutton"}
    _FORCED_SWITCH_ABILITIES = {"emergencyexit", "wimpout"}

    def __init__(self, *, turn: int, state: dict[str, Any]) -> None:
        self.turn = turn
        self.state = state
        self.actions: dict[str, dict[int, dict[str, Any]]] = {
            "p1": {},
            "p2": {},
        }
        self.missing_reasons: dict[str, dict[int, set[str]]] = {
            "p1": {},
            "p2": {},
        }
        self.pending_gimmicks: dict[tuple[str, int], set[str]] = {}
        self.forced_switch_slots: set[tuple[str, int]] = set()
        self.action_phase_started = False

    def _reason(self, side: str, slot: int, reason: str) -> None:
        self.missing_reasons[side].setdefault(slot, set()).add(reason)

    def observe(self, line: str) -> None:
        if not line.startswith("|"):
            return
        parts = line.split("|")
        if len(parts) < 2:
            return
        event = parts[1]
        actor = _slot_ref(parts[2] if len(parts) >= 3 else "")

        if event == "-enditem" and actor is not None and len(parts) >= 4:
            if _to_id(parts[3]) in self._FORCED_SWITCH_ITEMS:
                self.forced_switch_slots.add(actor)
        elif event == "-ability" and actor is not None and len(parts) >= 4:
            if _to_id(parts[3]) in self._FORCED_SWITCH_ABILITIES:
                self.forced_switch_slots.add(actor)

        if event in {"-mega", "-zpower", "-terastallize", "-dynamax", "-burst"}:
            if actor is not None and actor[1] in {1, 2}:
                self.pending_gimmicks.setdefault(actor, set()).add(event[1:])
            return

        if event == "switch" and actor is not None:
            side, slot = actor
            if slot not in {1, 2} or self.action_phase_started:
                return
            start_active = self.state["sides"][side]["active"][slot - 1]
            if not isinstance(start_active, dict):
                return
            if actor in self.forced_switch_slots:
                self._reason(side, slot, "public-forced-switch-effect")
                return
            if slot in self.actions[side]:
                self._reason(side, slot, "multiple-pre-action-switches")
                return
            incoming = _species_from_details(parts[3] if len(parts) >= 4 else "")
            if not incoming:
                self._reason(side, slot, "switch-target-not-visible")
                return
            self.actions[side][slot] = {
                "slot": slot,
                "kind": "switch",
                "switch_species": incoming,
                "authority": "reconstructed-pre-action-switch",
            }
            return

        if event == "drag":
            return

        if event == "cant" and actor is not None:
            self.action_phase_started = True
            side, slot = actor
            if slot in {1, 2} and slot not in self.actions[side]:
                self._reason(side, slot, "selected-action-prevented-or-unobservable")
            return

        if event != "move" or actor is None:
            return

        self.action_phase_started = True
        side, slot = actor
        if slot not in {1, 2}:
            return
        called = any(
            str(value).strip().lower().startswith("[from]")
            for value in parts[5:]
        )
        if called:
            return
        if slot in self.actions[side]:
            self._reason(side, slot, "multiple-selected-actions-observed")
            return

        move_name = str(parts[3] if len(parts) >= 4 else "").strip()
        move_id = _to_id(move_name)
        if not move_id:
            self._reason(side, slot, "move-name-not-visible")
            return
        target = _slot_ref(parts[4] if len(parts) >= 5 else "")
        resolved_target = (
            {"side": target[0], "slot": target[1]}
            if target is not None and target[1] in {1, 2}
            else None
        )
        self.actions[side][slot] = {
            "slot": slot,
            "kind": "move",
            "move": move_id,
            "move_name": move_name,
            "gimmicks": sorted(self.pending_gimmicks.pop((side, slot), set())),
            "resolved_target": resolved_target,
            "selected_target": None,
            "target_authority": "resolved-public-target-only",
            "authority": "top-level-public-move",
        }

    def joint(self, side: str) -> dict[str, Any]:
        slots: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        active = self.state["sides"][side]["active"]
        for slot in (1, 2):
            observed = self.actions[side].get(slot)
            if observed is not None:
                slots.append(copy.deepcopy(observed))
                continue
            if active[slot - 1] is None:
                slots.append(
                    {
                        "slot": slot,
                        "kind": "pass",
                        "authority": "public-empty-slot",
                    }
                )
                continue
            reasons = sorted(
                self.missing_reasons[side].get(
                    slot,
                    {"selected-action-not-publicly-reconstructible"},
                )
            )
            missing.append({"slot": slot, "reasons": reasons})
        slots.sort(key=lambda action: action["slot"])
        return {
            "schema": JOINT_ACTION_SCHEMA,
            "side": side,
            "identity_complete": not missing,
            "exact_showdown_command_available": False,
            "actions": slots,
            "missing": missing,
        }


def _public_prefix_hash(lines: list[str], end_index: int) -> str:
    prefix = "\n".join(lines[: end_index + 1]).encode("utf-8")
    return hashlib.sha256(prefix).hexdigest()


def extract_public_trajectory(
    detail: dict[str, Any],
    *,
    replay_id: str,
    format_id: str,
    raw_sha256: str,
    rating: int | None = None,
    uploadtime: int | None = None,
) -> dict[str, Any]:
    """Extract turn-boundary state and authority-tagged joint actions.

    Replay inputlog content is deliberately ignored even when it exists.
    """
    log = detail.get("log")
    if not isinstance(log, str) or not log:
        raise TrajectoryExtractionError(f"replay {replay_id} has no public battle log")
    lines = log.splitlines()
    state = _PublicState()
    decisions: list[dict[str, Any]] = []
    current: _TurnLabels | None = None
    winner: str | None = None
    tied = False

    def finish_current() -> None:
        nonlocal current
        if current is None:
            return
        p1 = current.joint("p1")
        p2 = current.joint("p2")
        decisions.append(
            {
                "turn": current.turn,
                "public_state": current.state,
                "joint_actions": {"p1": p1, "p2": p2},
                "complete_label_sides": [
                    side
                    for side, joint in (("p1", p1), ("p2", p2))
                    if joint["identity_complete"]
                ],
            }
        )
        current = None

    for line_index, line in enumerate(lines):
        parts = line.split("|") if line.startswith("|") else []
        event = parts[1] if len(parts) >= 2 else ""

        if event == "turn":
            finish_current()
            state.apply(line)
            if state.gametype not in {None, "doubles"}:
                raise TrajectoryExtractionError(
                    f"replay {replay_id} is not a doubles battle"
                )
            try:
                turn = int(parts[2])
            except (IndexError, ValueError) as error:
                raise TrajectoryExtractionError(
                    f"replay {replay_id} has an invalid turn marker"
                ) from error
            snapshot = state.snapshot()
            snapshot["source_prefix"] = {
                "line_count": line_index + 1,
                "sha256": _public_prefix_hash(lines, line_index),
            }
            current = _TurnLabels(turn=turn, state=snapshot)
            continue

        if current is not None:
            current.observe(line)
        state.apply(line)

        if event == "win" and len(parts) >= 3:
            winner = parts[2]
        elif event == "tie":
            tied = True

    finish_current()
    if state.gametype not in {None, "doubles"}:
        raise TrajectoryExtractionError(f"replay {replay_id} is not a doubles battle")

    complete = sum(len(decision["complete_label_sides"]) for decision in decisions)
    total_side_labels = len(decisions) * 2
    players = detail.get("players")
    if not isinstance(players, list) or not all(isinstance(value, str) for value in players):
        players = [state.players["p1"]["name"], state.players["p2"]["name"]]

    return {
        "schema": TRAJECTORY_SCHEMA,
        "replay_id": replay_id,
        "game_group": replay_id,
        "format_id": format_id,
        "source": {
            "raw_sha256": raw_sha256,
            "rating": rating,
            "uploadtime": uploadtime,
            "players": players,
            "inputlog_used": False,
        },
        "result": {"winner": winner, "tie": tied},
        "label_authority": {
            "selected_move_identity": "top-level public |move| only",
            "called_moves": "excluded as selected labels",
            "prevented_actions": (
                "incomplete unless a selected action is otherwise public"
            ),
            "switches": "pre-first-action public switches only",
            "move_targets": (
                "resolved public target retained; selected target not claimed"
            ),
            "exact_showdown_commands": False,
        },
        "decision_boundaries": len(decisions),
        "complete_joint_labels": complete,
        "incomplete_joint_labels": total_side_labels - complete,
        "decisions": decisions,
    }


def _connect_trajectory_manifest(path: Path) -> sqlite3.Connection:
    connection = _connect_manifest(path)
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS trajectories (
            replay_id TEXT PRIMARY KEY,
            format_id TEXT NOT NULL,
            raw_sha256 TEXT NOT NULL,
            trajectory_relative_path TEXT NOT NULL,
            trajectory_sha256 TEXT NOT NULL,
            trajectory_bytes INTEGER NOT NULL,
            schema_id TEXT NOT NULL,
            decision_boundaries INTEGER NOT NULL,
            complete_joint_labels INTEGER NOT NULL,
            incomplete_joint_labels INTEGER NOT NULL,
            extracted_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_trajectories_format
            ON trajectories(format_id, replay_id);

        CREATE TABLE IF NOT EXISTS trajectory_failures (
            replay_id TEXT PRIMARY KEY,
            format_id TEXT NOT NULL,
            raw_sha256 TEXT NOT NULL,
            last_error TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    connection.commit()
    return connection


def _trajectory_path(root: Path, format_id: str, replay_id: str) -> Path:
    _validate_public_id(format_id, label="format")
    _validate_public_id(replay_id, label="replay id")
    return root / "trajectories" / format_id / f"{replay_id}.json"


def _atomic_write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)


def _safe_raw_path(root: Path, relative_path: str) -> Path:
    path = (root / Path(relative_path)).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise TrajectoryExtractionError(
            f"raw replay path escapes external corpus root: {relative_path}"
        ) from error
    return path


def _manifest_rows(
    connection: sqlite3.Connection,
    *,
    format_id: str,
) -> sqlite3.Cursor:
    return connection.execute(
        """
        SELECT replay_id, raw_relative_path, raw_sha256, rating, uploadtime
        FROM replays
        WHERE format_id = ?
        ORDER BY uploadtime DESC, replay_id ASC
        """,
        (format_id,),
    )


def extract_trajectory_corpus(
    *,
    config: TrajectoryConfig,
    project_root: str | Path | None = None,
) -> TrajectoryStats:
    layout = initialize_layout(config.data_root, project_root=project_root)
    connection = _connect_trajectory_manifest(layout.database)
    examined = 0
    extracted = 0
    already_current = 0
    failed = 0
    decisions = 0
    complete = 0
    incomplete = 0
    try:
        for replay_id, raw_relative_path, raw_sha256, rating, uploadtime in _manifest_rows(
            connection,
            format_id=config.format_id,
        ):
            if config.max_replays and extracted >= config.max_replays:
                break
            examined += 1
            output_path = _trajectory_path(layout.root, config.format_id, replay_id)
            existing = connection.execute(
                """
                SELECT raw_sha256, trajectory_relative_path, schema_id
                FROM trajectories
                WHERE replay_id = ?
                """,
                (replay_id,),
            ).fetchone()
            if (
                not config.refresh
                and existing is not None
                and existing[0] == raw_sha256
                and existing[2] == TRAJECTORY_SCHEMA
                and (layout.root / existing[1]).is_file()
            ):
                already_current += 1
                continue

            try:
                if not isinstance(raw_relative_path, str) or not raw_relative_path:
                    raise TrajectoryExtractionError(
                        f"replay {replay_id} has no raw relative path"
                    )
                raw_path = _safe_raw_path(layout.root, raw_relative_path)
                raw = raw_path.read_bytes()
                actual_sha = hashlib.sha256(raw).hexdigest()
                if actual_sha != raw_sha256:
                    raise TrajectoryExtractionError(
                        f"raw replay hash mismatch for {replay_id}"
                    )
                try:
                    detail = json.loads(raw)
                except json.JSONDecodeError as error:
                    raise TrajectoryExtractionError(
                        f"replay {replay_id} raw JSON is invalid"
                    ) from error
                if not isinstance(detail, dict):
                    raise TrajectoryExtractionError(
                        f"replay {replay_id} raw JSON is not an object"
                    )
                returned_id = detail.get("id")
                if returned_id is not None and returned_id != replay_id:
                    raise TrajectoryExtractionError(
                        f"replay id mismatch: expected {replay_id}, got {returned_id}"
                    )
                trajectory = extract_public_trajectory(
                    detail,
                    replay_id=replay_id,
                    format_id=config.format_id,
                    raw_sha256=raw_sha256,
                    rating=rating,
                    uploadtime=uploadtime,
                )
                payload = (
                    json.dumps(
                        trajectory,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                encoded = payload.encode("utf-8")
                digest = hashlib.sha256(encoded).hexdigest()
                _atomic_write_text(output_path, payload)
                relative = output_path.relative_to(layout.root).as_posix()
                connection.execute(
                    """
                    INSERT INTO trajectories (
                        replay_id, format_id, raw_sha256, trajectory_relative_path,
                        trajectory_sha256, trajectory_bytes, schema_id,
                        decision_boundaries, complete_joint_labels,
                        incomplete_joint_labels, extracted_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(replay_id) DO UPDATE SET
                        format_id = excluded.format_id,
                        raw_sha256 = excluded.raw_sha256,
                        trajectory_relative_path = excluded.trajectory_relative_path,
                        trajectory_sha256 = excluded.trajectory_sha256,
                        trajectory_bytes = excluded.trajectory_bytes,
                        schema_id = excluded.schema_id,
                        decision_boundaries = excluded.decision_boundaries,
                        complete_joint_labels = excluded.complete_joint_labels,
                        incomplete_joint_labels = excluded.incomplete_joint_labels,
                        extracted_at = excluded.extracted_at
                    """,
                    (
                        replay_id,
                        config.format_id,
                        raw_sha256,
                        relative,
                        digest,
                        len(encoded),
                        TRAJECTORY_SCHEMA,
                        trajectory["decision_boundaries"],
                        trajectory["complete_joint_labels"],
                        trajectory["incomplete_joint_labels"],
                        _utc_now(),
                    ),
                )
                connection.execute(
                    "DELETE FROM trajectory_failures WHERE replay_id = ?",
                    (replay_id,),
                )
                connection.commit()
            except Exception as error:
                connection.execute(
                    """
                    INSERT INTO trajectory_failures (
                        replay_id, format_id, raw_sha256, last_error, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(replay_id) DO UPDATE SET
                        format_id = excluded.format_id,
                        raw_sha256 = excluded.raw_sha256,
                        last_error = excluded.last_error,
                        updated_at = excluded.updated_at
                    """,
                    (
                        replay_id,
                        config.format_id,
                        raw_sha256,
                        str(error),
                        _utc_now(),
                    ),
                )
                connection.commit()
                failed += 1
                if config.strict:
                    raise
                continue

            extracted += 1
            decisions += trajectory["decision_boundaries"]
            complete += trajectory["complete_joint_labels"]
            incomplete += trajectory["incomplete_joint_labels"]

        return TrajectoryStats(
            format_id=config.format_id,
            replay_rows_examined=examined,
            extracted=extracted,
            already_current=already_current,
            failed=failed,
            decision_boundaries=decisions,
            complete_joint_labels=complete,
            incomplete_joint_labels=incomplete,
        )
    finally:
        connection.close()


def trajectory_status(
    data_root: str | Path,
    *,
    format_id: str = DEFAULT_FORMAT,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    root = ensure_external_data_root(data_root, project_root=project_root)
    layout = initialize_layout(root, project_root=project_root)
    connection = _connect_trajectory_manifest(layout.database)
    try:
        row = connection.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(decision_boundaries), 0),
                   COALESCE(SUM(complete_joint_labels), 0),
                   COALESCE(SUM(incomplete_joint_labels), 0)
            FROM trajectories
            WHERE format_id = ? AND schema_id = ?
            """,
            (format_id, TRAJECTORY_SCHEMA),
        ).fetchone()
        failures = connection.execute(
            "SELECT COUNT(*) FROM trajectory_failures WHERE format_id = ?",
            (format_id,),
        ).fetchone()[0]
        return {
            "schema": TRAJECTORY_SCHEMA,
            "format_id": format_id,
            "replays": int(row[0]),
            "decision_boundaries": int(row[1]),
            "complete_joint_labels": int(row[2]),
            "incomplete_joint_labels": int(row[3]),
            "failures": int(failures),
            "data_root": str(root),
        }
    finally:
        connection.close()


def _resolve_data_root(value: str | None) -> Path:
    selected = value or os.environ.get(DATA_ROOT_ENV)
    if not selected:
        raise TrajectoryExtractionError(
            f"Pass --data-root or set {DATA_ROOT_ENV}."
        )
    return Path(selected)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract public decision-time states and observable joint-action "
            "identities from archived Showdown replays."
        )
    )
    parser.add_argument("--data-root", help=f"External corpus root; or set {DATA_ROOT_ENV}.")
    parser.add_argument("--format", default=DEFAULT_FORMAT, dest="format_id")
    parser.add_argument(
        "--max-replays",
        type=int,
        default=DEFAULT_MAX_REPLAYS,
        help="Maximum newly extracted replays this run; 0 means unlimited.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-extract even when raw hash and trajectory schema are current.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Stop on the first replay extraction failure.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print local trajectory corpus status.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        data_root = _resolve_data_root(args.data_root)
        if args.status:
            print(json.dumps(trajectory_status(data_root, format_id=args.format_id), indent=2))
            return
        stats = extract_trajectory_corpus(
            config=TrajectoryConfig(
                data_root=data_root,
                format_id=args.format_id,
                max_replays=args.max_replays,
                refresh=args.refresh,
                strict=args.strict,
            )
        )
        print(json.dumps(stats.__dict__, indent=2))
    except (ReplayCorpusError, TrajectoryExtractionError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
