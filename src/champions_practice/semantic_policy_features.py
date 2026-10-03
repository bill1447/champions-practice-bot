"""Deterministic public-state and semantic-action features for policy learning."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

FEATURE_SCHEMA = "semantic-policy-features-v1"
DEFAULT_STATE_BUCKETS = 65_536
DEFAULT_ACTION_BUCKETS = 32_768

RATING_WEIGHTS = {
    "unrated": 0.10,
    "<1200": 0.15,
    "1200-1399": 0.35,
    "1400-1599": 1.00,
    "1600-1799": 2.00,
    "1800+": 3.00,
}


class SemanticPolicyFeatureError(ValueError):
    """A policy row cannot be featurized without changing its meaning."""


def _to_id(value: object) -> str:
    return "".join(character for character in str(value or "").lower() if character.isalnum())


def stable_bucket(token: str, buckets: int) -> int:
    if not isinstance(token, str) or not token:
        raise SemanticPolicyFeatureError("feature token must be a non-empty string")
    if isinstance(buckets, bool) or not isinstance(buckets, int) or buckets < 2:
        raise SemanticPolicyFeatureError("feature bucket count must be at least two")
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return 1 + (int.from_bytes(digest[:8], "big") % (buckets - 1))


def hash_tokens(tokens: Iterable[str], buckets: int) -> tuple[int, ...]:
    return tuple(sorted({stable_bucket(token, buckets) for token in tokens}))


def _hp_bucket(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "unknown"
    clipped = min(100.0, max(0.0, float(value)))
    return str(min(10, int(clipped // 10)))


def _turn_band(turn: int) -> str:
    if turn == 1:
        return "1"
    if turn <= 4:
        return "2-4"
    if turn <= 8:
        return "5-8"
    if turn <= 12:
        return "9-12"
    return "13+"


def _side_tokens(role: str, side: dict[str, Any]) -> list[str]:
    tokens: list[str] = []

    preview = side.get("preview_species", [])
    if isinstance(preview, list):
        for species in preview:
            species_id = _to_id(species)
            if species_id:
                tokens.append(f"{role}:preview:{species_id}")

    conditions = side.get("side_conditions", [])
    if isinstance(conditions, list):
        for condition in conditions:
            condition_id = _to_id(condition)
            if condition_id:
                tokens.append(f"{role}:sidecondition:{condition_id}")

    active = side.get("active", [])
    if isinstance(active, list):
        for index, pokemon in enumerate(active, start=1):
            slot = f"{role}:active:{index}"
            if not isinstance(pokemon, dict):
                tokens.append(f"{slot}:empty")
                continue
            base_species = _to_id(pokemon.get("base_species"))
            visible_species = _to_id(pokemon.get("visible_species"))
            if base_species:
                tokens.append(f"{slot}:base:{base_species}")
            if visible_species:
                tokens.append(f"{slot}:visible:{visible_species}")
            tokens.append(f"{slot}:hp:{_hp_bucket(pokemon.get('hp_percent'))}")
            status = _to_id(pokemon.get("status"))
            if status:
                tokens.append(f"{slot}:status:{status}")
            if pokemon.get("fainted") is True:
                tokens.append(f"{slot}:fainted")
            boosts = pokemon.get("boosts", {})
            if isinstance(boosts, dict):
                for stat, value in sorted(boosts.items()):
                    if isinstance(value, bool) or not isinstance(value, int):
                        continue
                    tokens.append(
                        f"{slot}:boost:{_to_id(stat)}:{max(-6, min(6, value))}"
                    )

    revealed = side.get("revealed", [])
    if isinstance(revealed, list):
        for pokemon in revealed:
            if not isinstance(pokemon, dict):
                continue
            species = _to_id(pokemon.get("species"))
            if not species:
                continue
            prefix = f"{role}:revealed:{species}"
            if pokemon.get("seen") is True:
                tokens.append(f"{prefix}:seen")
            tokens.append(f"{prefix}:hp:{_hp_bucket(pokemon.get('hp_percent'))}")
            status = _to_id(pokemon.get("status"))
            if status:
                tokens.append(f"{prefix}:status:{status}")
            if pokemon.get("fainted") is True:
                tokens.append(f"{prefix}:fainted")
            for field in ("moves", "items", "abilities"):
                values = pokemon.get(field, [])
                if not isinstance(values, list):
                    continue
                singular = field[:-1] if field.endswith("s") else field
                for value in values:
                    value_id = _to_id(value)
                    if value_id:
                        tokens.append(f"{prefix}:{singular}:{value_id}")

    return tokens


def state_tokens(public_state: dict[str, Any], *, side: str) -> tuple[str, ...]:
    """Return actor-relative tokens from replay-public decision state only."""
    if side not in {"p1", "p2"}:
        raise SemanticPolicyFeatureError("side must be p1 or p2")
    if not isinstance(public_state, dict):
        raise SemanticPolicyFeatureError("public_state must be an object")
    turn = public_state.get("turn")
    if isinstance(turn, bool) or not isinstance(turn, int) or turn < 1:
        raise SemanticPolicyFeatureError("public state has invalid turn")

    tokens = [
        f"turn:band:{_turn_band(turn)}",
        f"turn:exact:{min(turn, 20)}",
    ]
    game_type = _to_id(public_state.get("gametype"))
    if game_type:
        tokens.append(f"gametype:{game_type}")

    field = public_state.get("field", {})
    if isinstance(field, dict):
        weather = _to_id(field.get("weather"))
        tokens.append(f"field:weather:{weather or 'none'}")
        conditions = field.get("conditions", [])
        if isinstance(conditions, list):
            for condition in conditions:
                condition_id = _to_id(condition)
                if condition_id:
                    tokens.append(f"field:condition:{condition_id}")

    sides = public_state.get("sides")
    if not isinstance(sides, dict):
        raise SemanticPolicyFeatureError("public state has no sides")
    opponent = "p2" if side == "p1" else "p1"
    player_state = sides.get(side)
    opponent_state = sides.get(opponent)
    if not isinstance(player_state, dict) or not isinstance(opponent_state, dict):
        raise SemanticPolicyFeatureError("public state is missing a side")
    tokens.extend(_side_tokens("self", player_state))
    tokens.extend(_side_tokens("opponent", opponent_state))
    return tuple(sorted(set(tokens)))


def _normalize_gimmick(value: object) -> str:
    gimmick = _to_id(value)
    if gimmick in {"megax", "megay"}:
        return "mega"
    if gimmick == "zpower":
        return "zmove"
    if gimmick == "burst":
        return "ultra"
    return gimmick


def normalized_semantic_label(label: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(label, dict):
        raise SemanticPolicyFeatureError("semantic label must be an object")
    actions = label.get("actions")
    if not isinstance(actions, list) or not actions:
        raise SemanticPolicyFeatureError("semantic label has no actions")

    normalized: list[dict[str, Any]] = []
    slots: set[int] = set()
    for action in actions:
        if not isinstance(action, dict):
            raise SemanticPolicyFeatureError("semantic action must be an object")
        slot = action.get("slot")
        if isinstance(slot, bool) or not isinstance(slot, int) or slot < 1:
            raise SemanticPolicyFeatureError("semantic action has invalid slot")
        if slot in slots:
            raise SemanticPolicyFeatureError("semantic label contains duplicate slots")
        slots.add(slot)
        kind = action.get("kind")
        if kind == "move":
            move = _to_id(action.get("move"))
            if not move:
                raise SemanticPolicyFeatureError("semantic move has no move id")
            gimmicks = action.get("gimmicks", [])
            if not isinstance(gimmicks, list):
                raise SemanticPolicyFeatureError("semantic move gimmicks must be a list")
            normalized.append(
                {
                    "slot": slot,
                    "kind": "move",
                    "move": move,
                    "gimmicks": sorted(
                        {
                            normalized_gimmick
                            for value in gimmicks
                            if (normalized_gimmick := _normalize_gimmick(value))
                        }
                    ),
                }
            )
        elif kind == "switch":
            species = _to_id(
                action.get("switch_species_id") or action.get("switch_species")
            )
            if not species:
                raise SemanticPolicyFeatureError("semantic switch has no species")
            normalized.append(
                {
                    "slot": slot,
                    "kind": "switch",
                    "switch_species_id": species,
                }
            )
        elif kind == "pass":
            normalized.append({"slot": slot, "kind": "pass"})
        else:
            raise SemanticPolicyFeatureError(
                f"unsupported semantic action kind {kind!r}"
            )

    normalized.sort(key=lambda action: action["slot"])
    family = "+".join(action["kind"] for action in normalized)
    return {"actions": normalized, "action_family": family}


def canonical_action_key(label: dict[str, Any]) -> str:
    normalized = normalized_semantic_label(label)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def action_tokens(label: dict[str, Any]) -> tuple[str, ...]:
    normalized = normalized_semantic_label(label)
    tokens = [f"joint:family:{normalized['action_family']}"]
    for action in normalized["actions"]:
        slot = action["slot"]
        kind = action["kind"]
        prefix = f"slot:{slot}"
        tokens.append(f"{prefix}:kind:{kind}")
        if kind == "move":
            tokens.append(f"{prefix}:move:{action['move']}")
            gimmicks = action.get("gimmicks", [])
            if gimmicks:
                for gimmick in gimmicks:
                    tokens.append(f"{prefix}:gimmick:{gimmick}")
            else:
                tokens.append(f"{prefix}:gimmick:none")
        elif kind == "switch":
            tokens.append(
                f"{prefix}:switch:{action['switch_species_id']}"
            )
    return tuple(sorted(set(tokens)))


def rating_weight(rating_band: str) -> float:
    if rating_band not in RATING_WEIGHTS:
        raise SemanticPolicyFeatureError(
            f"unsupported rating band {rating_band!r}"
        )
    return RATING_WEIGHTS[rating_band]
