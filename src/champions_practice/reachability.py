"""Typed mechanics-reachability evidence with no live-admission authority.

This module defines the result contract for future Showdown-backed stochastic
damage and categorical reachability. It is intentionally not integrated with
recovery admission or live belief decisions.

A witnessed outcome establishes mechanical reachability for the supplied
sequential context. An exhaustively-disproved outcome establishes mechanical
impossibility only when the result explicitly covers the full sequential
transition context and all relevant randomness. Bounded sampling misses,
timeouts, and unsupported mechanics remain unresolved or unsupported and may
not be promoted into exclusion evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from champions_practice.observation_beliefs import public_observation_signature
from champions_practice.search_worker import ShowdownRequestError
from champions_practice.showdown_public_catalog import (
    ABILITY_IDS,
    ACTIVATION_EFFECT_IDENTITIES,
    CONDITION_IDS,
    FIELD_ACTIVATE_IDENTITIES,
    ITEM_IDS,
    MEGA_ITEM_IDS,
    MOVE_CATEGORIES,
    MOVE_DISPLAY_NAMES,
    MOVE_IDS,
    PRIMAL_ITEM_IDS,
    PSEUDO_WEATHER_IDS,
    SIDE_CONDITION_IDS,
    SPECIES_IDS,
    SPECIAL_EFFECT_IDS,
    TERRAIN_IDS,
    TRANSFORM_ITEM_SPECIES_IDS,
    WEATHER_IDS,
)


PUBLIC_OBSERVATION_SCHEMA_VERSION = "showdown-player-view-v7"


class ReachabilityStatus(str, Enum):
    """Authority level of one mechanics-reachability query."""

    WITNESSED = "witnessed"
    EXHAUSTIVELY_DISPROVED = "exhaustively-disproved"
    UNRESOLVED = "unresolved"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class ReachabilityCoverage:
    """Declared mechanics coverage for one sequential reachability query.

    The fingerprint binds evidence to the complete ordered transition context
    supplied by the eventual mechanics implementation. randomness_domains
    names the relevant random dimensions considered by that implementation;
    an empty tuple is valid for a deterministic transition.
    """

    sequential_context_fingerprint: str
    transitions_covered: int
    outcomes_examined: int
    observation_schema: str = PUBLIC_OBSERVATION_SCHEMA_VERSION
    randomness_domains: tuple[str, ...] = ()
    randomness_exhaustive: bool = False
    sequential_context_complete: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.sequential_context_fingerprint, str)
            or not self.sequential_context_fingerprint.strip()
        ):
            raise ValueError("reachability coverage requires a context fingerprint")
        if self.observation_schema != PUBLIC_OBSERVATION_SCHEMA_VERSION:
            raise ValueError(
                "reachability coverage uses an unsupported observation schema"
            )
        if self.transitions_covered <= 0:
            raise ValueError("reachability coverage must include at least one transition")
        if self.outcomes_examined < 0:
            raise ValueError("outcomes_examined must not be negative")
        if any(
            not isinstance(domain, str) or not domain.strip()
            for domain in self.randomness_domains
        ):
            raise ValueError("randomness domains must be non-empty strings")
        if len(set(self.randomness_domains)) != len(self.randomness_domains):
            raise ValueError("randomness domains must be unique")


@dataclass(frozen=True)
class ReachabilityResult:
    """Mechanics evidence only; this object has no recovery-install operation."""

    status: ReachabilityStatus
    coverage: ReachabilityCoverage | None = None
    witness_ids: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if any(
            not isinstance(witness_id, str) or not witness_id.strip()
            for witness_id in self.witness_ids
        ):
            raise ValueError("witness ids must be non-empty strings")
        if len(set(self.witness_ids)) != len(self.witness_ids):
            raise ValueError("witness ids must be unique")

        if self.status is ReachabilityStatus.WITNESSED:
            if self.coverage is None:
                raise ValueError("witnessed reachability requires declared coverage")
            if not self.witness_ids:
                raise ValueError("witnessed reachability requires a mechanics witness")
            if self.coverage.outcomes_examined <= 0:
                raise ValueError("witnessed reachability must examine at least one outcome")
            return

        if self.witness_ids:
            raise ValueError("non-witness reachability results cannot carry witnesses")

        if self.status is ReachabilityStatus.EXHAUSTIVELY_DISPROVED:
            if self.coverage is None:
                raise ValueError("exhaustive disproof requires declared coverage")
            if not self.coverage.randomness_exhaustive:
                raise ValueError("exhaustive disproof requires exhaustive randomness coverage")
            if not self.coverage.sequential_context_complete:
                raise ValueError(
                    "exhaustive disproof requires the full sequential transition context"
                )
            if self.coverage.outcomes_examined <= 0:
                raise ValueError("exhaustive disproof must examine at least one outcome")
            return

        if self.coverage is not None and (
            self.coverage.randomness_exhaustive
            and self.coverage.sequential_context_complete
        ):
            raise ValueError(
                "fully exhaustive coverage must be represented as a conclusive result"
            )

        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError(
                "unresolved and unsupported reachability results require a reason"
            )

    @property
    def establishes_reachability(self) -> bool:
        """Whether this result contains a concrete mechanics witness."""

        return self.status is ReachabilityStatus.WITNESSED

    @property
    def establishes_impossibility(self) -> bool:
        """Whether this result is valid exclusion evidence for this exact context."""

        return self.status is ReachabilityStatus.EXHAUSTIVELY_DISPROVED

    @property
    def conclusive(self) -> bool:
        """Whether mechanics reachability is established in either direction."""

        return self.establishes_reachability or self.establishes_impossibility

    @classmethod
    def witnessed(
        cls,
        *,
        coverage: ReachabilityCoverage,
        witness_ids: tuple[str, ...],
    ) -> "ReachabilityResult":
        return cls(
            status=ReachabilityStatus.WITNESSED,
            coverage=coverage,
            witness_ids=witness_ids,
        )

    @classmethod
    def exhaustively_disproved(
        cls,
        *,
        coverage: ReachabilityCoverage,
    ) -> "ReachabilityResult":
        return cls(
            status=ReachabilityStatus.EXHAUSTIVELY_DISPROVED,
            coverage=coverage,
        )

    @classmethod
    def unresolved(
        cls,
        *,
        reason: str,
        coverage: ReachabilityCoverage | None = None,
    ) -> "ReachabilityResult":
        return cls(
            status=ReachabilityStatus.UNRESOLVED,
            coverage=coverage,
            reason=reason,
        )

    @classmethod
    def unsupported(
        cls,
        *,
        reason: str,
        coverage: ReachabilityCoverage | None = None,
    ) -> "ReachabilityResult":
        return cls(
            status=ReachabilityStatus.UNSUPPORTED,
            coverage=coverage,
            reason=reason,
        )


class ReachabilityWorker(Protocol):
    """Restricted mechanics surface used by bounded reachability probes."""

    def branch_many(
        self,
        *,
        state: dict[str, Any],
        branches: list[dict[str, Any]],
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class PublicReachabilityStep:
    """One exact action pair and public outcome required by a witness path."""

    p1_choice: str
    p2_choice: str
    expected_public_view: dict[str, Any]
    rng_seeds: tuple[str | None, ...] = (None,)

    def __post_init__(self) -> None:
        for side, choice in (("p1", self.p1_choice), ("p2", self.p2_choice)):
            if not isinstance(choice, str) or not choice.strip():
                raise ValueError(
                    f"{side} reachability choice must be a non-empty exact command"
                )
        if not isinstance(self.expected_public_view, dict):
            raise ValueError("expected_public_view must be a dictionary")
        if not self.rng_seeds:
            raise ValueError("reachability step requires at least one RNG sample")
        if any(
            seed is not None
            and (not isinstance(seed, str) or not seed.strip())
            for seed in self.rng_seeds
        ):
            raise ValueError("RNG samples must be non-empty strings or None")


def _schema_error(path: str, message: str) -> str:
    return f"{path}: {message}"


def _exact_keys(
    value: dict[str, Any],
    *,
    path: str,
    keys: set[str],
) -> str | None:
    actual = set(value)
    missing = sorted(keys - actual)
    extra = sorted(actual - keys)
    if missing:
        return _schema_error(path, f"missing required field(s): {', '.join(missing)}")
    if extra:
        return _schema_error(path, f"unexpected field(s): {', '.join(extra)}")
    return None


def _non_bool_int(value: object, *, minimum: int | None = None) -> bool:
    if not isinstance(value, int) or isinstance(value, bool):
        return False
    return minimum is None or value >= minimum


def _number(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _percentage(value: object) -> bool:
    return _number(value) and 0 <= value <= 100


def _string_list(
    value: object,
    *,
    allow_empty_strings: bool = False,
) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str)
        and (allow_empty_strings or bool(item.strip()))
        for item in value
    )


_CANONICAL_ID = re.compile(r"^[a-z0-9]+$")
_CANONICAL_SLOT = re.compile(r"^p[12][ab]$")
_CANONICAL_SIDE = re.compile(r"^p[12]$")
_CANONICAL_INTEGER = re.compile(r"^(?:0|-[1-9][0-9]*|[1-9][0-9]*)$")
_CANONICAL_EFFECT = re.compile(r"^(?:move|ability|item):[a-z0-9]+$")
_CANONICAL_TAGGED = re.compile(r"^\[([a-z0-9]+)\](?::(.+))?$")
_PUBLIC_CONDITION = re.compile(
    r"^(0|[1-9][0-9]*)/([1-9][0-9]*)([ryg]?)"
    r"(?: (brn|frz|par|psn|slp|tox))?$"
)
_REQUEST_IDENT = re.compile(r"^(p[12]): .+$")
_CANONICAL_DETAILS = re.compile(r"^[a-z0-9\[][a-z0-9 .,'():+\-/\[\]]*$")
_MAJOR_STATUSES = frozenset({"brn", "frz", "par", "psn", "slp", "tox"})
_SUPPORTED_BOOSTS = frozenset(
    {"atk", "def", "spa", "spd", "spe", "accuracy", "evasion"}
)
_PINNED_TRANSFER_GROUPS = {
    "atkspa": "move:powerswap",
    "defspd": "move:guardswap",
}
_MAJOR_OR_FAINT_STATUSES = _MAJOR_STATUSES | {"fnt"}
_TYPES = frozenset(
    {
        "bug",
        "dark",
        "dragon",
        "electric",
        "fairy",
        "fighting",
        "fire",
        "flying",
        "ghost",
        "grass",
        "ground",
        "ice",
        "normal",
        "poison",
        "psychic",
        "rock",
        "steel",
        "water",
    }
)
_PROTOCOL_MARKERS = frozenset(
    {
        "eat",
        "premajor",
        "silent",
        "still",
        "upkeep",
        "zeffect",
    }
)
_PROTOCOL_EFFECT_IDS = (
    MOVE_IDS
    | ABILITY_IDS
    | ITEM_IDS
    | CONDITION_IDS
    | SPECIAL_EFFECT_IDS
    | {"none", "typechange"}
)
_MOVE_TARGETS = frozenset(
    {
        "adjacentAlly",
        "adjacentAllyOrSelf",
        "adjacentFoe",
        "all",
        "allAdjacent",
        "allAdjacentFoes",
        "allies",
        "allySide",
        "allyTeam",
        "any",
        "foeSide",
        "normal",
        "randomNormal",
        "scripted",
        "self",
    }
)
_PUBLIC_ACTION_EFFECTS = frozenset(
    {"-fail", "-miss", "-immune", "-notarget", "-block"}
)

# Producer-role domains derived from the pinned Showdown emitters. These are
# deliberately narrower than the union of every move/item/ability identifier.
_START_END_ABILITY_EFFECTS = frozenset(
    {"ability:flashfire", "ability:neutralizinggas", "ability:slowstart"}
)
_START_END_MOVE_EFFECTS = frozenset(
    {
        "move:attract",
        "move:bide",
        "move:dragoncheer",
        "move:focusenergy",
        "move:futuresight",
        "move:gmaxchistrike",
        "move:healblock",
        "move:imprison",
        "move:ingrain",
        "move:laserfocus",
        "move:leechseed",
        "move:noretreat",
        "move:octolock",
        "move:taunt",
        "move:yawn",
        "move:bind",
        "move:clamp",
        "move:firespin",
        "move:infestation",
        "move:magmastorm",
        "move:sandtomb",
        "move:snaptrap",
        "move:thundercage",
        "move:whirlpool",
        "move:wrap",
        "move:gmaxcentiferno",
        "move:gmaxsandblast",
    }
)
_START_END_PLAIN_EFFECTS = frozenset(
    {
        "aquaring",
        "attract",
        "autotomize",
        "charge",
        "confusion",
        "curse",
        "disable",
        "doomdesire",
        "dynamax",
        "embargo",
        "encore",
        "foresight",
        "illusion",
        "leechseed",
        "magnetrise",
        "mimic",
        "miracleeye",
        "nightmare",
        "octolock",
        "powershift",
        "powertrick",
        "protosynthesis",
        "quarkdrive",
        "saltcure",
        "skydrop",
        "slowstart",
        "smackdown",
        "stockpile",
        "substitute",
        "syrupbomb",
        "tarshot",
        "telekinesis",
        "throatchop",
        "torment",
        "uproar",
        "bind",
        "clamp",
        "firespin",
        "gmaxcentiferno",
        "gmaxsandblast",
        "infestation",
        "magmastorm",
        "sandtomb",
        "snaptrap",
        "thundercage",
        "whirlpool",
        "wrap",
    }
)
_SINGLE_TURN_EFFECT_IDENTITIES = frozenset(
    {
        "craftyshield",
        "helpinghand",
        "matblock",
        "maxguard",
        "move:beakblast",
        "move:electrify",
        "move:endure",
        "move:focuspunch",
        "move:followme",
        "move:instruct",
        "move:magiccoat",
        "move:protect",
        "move:ragepowder",
        "move:roost",
        "move:shelltrap",
        "move:spotlight",
        "powder",
        "protect",
        "quickguard",
        "snatch",
        "wideguard",
    }
)
_SINGLE_MOVE_EFFECT_IDENTITIES = frozenset(
    {"destinybond", "glaiverush", "grudge", "rage"}
)
_FORME_CHANGE_ABILITY_IDS = frozenset({"flowergift", "forecast"})
_PUBLIC_PREVENTION_IDENTITIES = frozenset(
    {
        "ability:armortail",
        "ability:damp",
        "ability:dazzling",
        "ability:queenlymajesty",
        "ability:truant",
        "attract",
        "disable",
        "flinch",
        "focuspunch",
        "frz",
        "move:gravity",
        "move:healblock",
        "move:imprison",
        "move:taunt",
        "move:throatchop",
        "nopp",
        "par",
        "recharge",
        "shelltrap",
        "slp",
    }
)
_PP_DEDUCTION_ACTIVATION_LIMITS = {
    "move:eeriespell": 3,
    "move:gmaxdepletion": 2,
    "move:spite": 4,
}
_BURST_ITEM_IDS = frozenset({"ultranecroziumz"})

_PUBLIC_MECHANICS_EVENTS = frozenset(
    {
        "-formechange",
        "-fail",
        "-block",
        "-notarget",
        "-miss",
        "-damage",
        "-heal",
        "-sethp",
        "-status",
        "-curestatus",
        "-cureteam",
        "-boost",
        "-unboost",
        "-setboost",
        "-swapboost",
        "-invertboost",
        "-clearboost",
        "-clearallboost",
        "-clearpositiveboost",
        "-clearnegativeboost",
        "-copyboost",
        "-weather",
        "-fieldstart",
        "-fieldend",
        "-fieldactivate",
        "-sidestart",
        "-sideend",
        "-swapsideconditions",
        "-start",
        "-end",
        "-crit",
        "-supereffective",
        "-resisted",
        "-immune",
        "-item",
        "-enditem",
        "-ability",
        "-endability",
        "-transform",
        "-mega",
        "-primal",
        "-burst",
        "-zpower",
        "-zbroken",
        "-terastallize",
        "-dynamax",
        "-activate",
        "-waiting",
        "-prepare",
        "-mustrecharge",
        "-nothing",
        "-hitcount",
        "-singlemove",
        "-singleturn",
        "-ohko",
    }
)


def _canonical_id(value: object) -> bool:
    return isinstance(value, str) and bool(_CANONICAL_ID.fullmatch(value))


def _canonical_slot(value: object) -> bool:
    return isinstance(value, str) and bool(_CANONICAL_SLOT.fullmatch(value))


def _canonical_side(value: object) -> bool:
    return isinstance(value, str) and bool(_CANONICAL_SIDE.fullmatch(value))


def _canonical_integer_text(value: object) -> bool:
    return isinstance(value, str) and bool(_CANONICAL_INTEGER.fullmatch(value))


def _to_id(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _display_move_id(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    for move_id, display_name in MOVE_DISPLAY_NAMES.items():
        if value == display_name:
            return move_id

    hidden_power = re.fullmatch(
        r"Hidden Power "
        r"(Bug|Dark|Dragon|Electric|Fairy|Fighting|Fire|Flying|Ghost|Grass|"
        r"Ground|Ice|Normal|Poison|Psychic|Rock|Steel|Water)",
        value,
    )
    if hidden_power is not None:
        return "hiddenpower"

    variable_power = re.fullmatch(r"(Return|Frustration) ([1-9][0-9]?|10[0-2])", value)
    if variable_power is not None:
        return variable_power.group(1).lower()
    return None


def _known_move_id(value: object) -> bool:
    return isinstance(value, str) and value in MOVE_IDS


def _known_public_move_id(value: object) -> bool:
    if _known_move_id(value):
        return True
    if not isinstance(value, str):
        return False
    if re.fullmatch(
        r"hiddenpower(?:bug|dark|dragon|electric|fairy|fighting|fire|flying|"
        r"ghost|grass|ground|ice|normal|poison|psychic|rock|steel|water)"
        r"(?:[1-9][0-9]?)?",
        value,
    ):
        return True
    return bool(re.fullmatch(r"(?:return|frustration)(?:[1-9][0-9]?|10[0-2])", value))


def _known_ability_id(value: object) -> bool:
    return isinstance(value, str) and value in ABILITY_IDS


def _known_item_id(value: object) -> bool:
    return isinstance(value, str) and value in ITEM_IDS


def _known_plain_effect_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and value in _PROTOCOL_EFFECT_IDS
        and not _canonical_slot(value)
        and not _canonical_side(value)
    )


def _known_effect_identity(value: object) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if value.startswith("move:"):
        return value[5:] in MOVE_IDS
    if value.startswith("ability:"):
        return value[8:] in ABILITY_IDS
    if value.startswith("item:"):
        return value[5:] in ITEM_IDS
    return _known_plain_effect_id(value)


def _known_move_identity(value: object) -> bool:
    if not isinstance(value, str):
        return False
    if value.startswith("move:"):
        return value[5:] in MOVE_IDS
    return value in MOVE_IDS


def _domain_effect_identity(
    value: object,
    domain: frozenset[str],
) -> bool:
    if not isinstance(value, str):
        return False
    if value in domain:
        return True
    return value.startswith("move:") and value[5:] in domain


def _type_payload(value: object) -> bool:
    if not isinstance(value, str):
        return False
    if value in _TYPES:
        return True
    return any(
        value == first + second
        for first in _TYPES
        for second in _TYPES
        if first != second
    )


def _canonical_protocol_token(value: object) -> bool:
    """Validate one exact output of the bridge's canonicalProtocolIdentity()."""

    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if (
        _CANONICAL_ID.fullmatch(value)
        or _CANONICAL_SLOT.fullmatch(value)
        or _CANONICAL_SIDE.fullmatch(value)
        or _CANONICAL_INTEGER.fullmatch(value)
        or _CANONICAL_EFFECT.fullmatch(value)
    ):
        return True
    tagged = _CANONICAL_TAGGED.fullmatch(value)
    if tagged is None:
        return False
    payload = tagged.group(2)
    return payload is None or _canonical_protocol_token(payload)


def _tagged_modifier_parts(value: object) -> tuple[str, str | None] | None:
    if not isinstance(value, str):
        return None
    tagged = _CANONICAL_TAGGED.fullmatch(value)
    if tagged is None:
        return None
    return tagged.group(1), tagged.group(2)


def _source_modifier(value: object) -> bool:
    parts = _tagged_modifier_parts(value)
    if parts is None or parts[0] != "from" or parts[1] is None:
        return False
    return _known_effect_identity(parts[1])


def _of_modifier(value: object) -> bool:
    parts = _tagged_modifier_parts(value)
    return (
        parts is not None
        and parts[0] == "of"
        and parts[1] is not None
        and _canonical_actor(parts[1], allow_side=True)
    )


def _ability_modifier(value: object) -> bool:
    parts = _tagged_modifier_parts(value)
    return (
        parts is not None
        and parts[0] == "ability"
        and parts[1] is not None
        and _known_ability_id(parts[1])
    )


def _move_modifier(value: object) -> bool:
    parts = _tagged_modifier_parts(value)
    return (
        parts is not None
        and parts[0] == "move"
        and parts[1] is not None
        and _known_public_move_id(parts[1])
    )


def _marker_modifier(value: object, allowed: set[str] | frozenset[str]) -> bool:
    parts = _tagged_modifier_parts(value)
    return parts is not None and parts[0] in allowed and parts[1] is None


def _wisher_modifier(value: object) -> bool:
    parts = _tagged_modifier_parts(value)
    return (
        parts is not None
        and parts[0] == "wisher"
        and parts[1] is not None
        and _canonical_id(parts[1])
        and not _canonical_actor(parts[1], allow_side=True)
    )


def _canonical_from_token(value: object) -> bool:
    return _source_modifier(value)


def _canonical_actor(value: object, *, allow_side: bool = False) -> bool:
    return _canonical_slot(value) or (allow_side and _canonical_side(value))


def _parse_public_condition(
    value: object,
    *,
    allow_champions_color: bool,
) -> tuple[int, int | None, str | None] | None:
    if not isinstance(value, str) or value != value.strip().lower():
        return None
    if value == "0 fnt":
        return (0, None, "fnt")

    match = _PUBLIC_CONDITION.fullmatch(value)
    if match is None:
        return None
    current = int(match.group(1))
    maximum = int(match.group(2))
    color = match.group(3)
    status = match.group(4)
    if current <= 0 or current > maximum:
        return None
    if color:
        if not allow_champions_color or maximum != 100:
            return None
        if current == 20:
            if color not in {"r", "y"}:
                return None
        elif current == 50:
            if color not in {"y", "g"}:
                return None
        else:
            return None
    return (current, maximum, status)


def _public_condition(value: object) -> bool:
    return _parse_public_condition(
        value,
        allow_champions_color=True,
    ) is not None


def _request_condition(value: object) -> bool:
    return _parse_public_condition(
        value,
        allow_champions_color=False,
    ) is not None


def _canonical_details(value: object) -> bool:
    return isinstance(value, str) and bool(_CANONICAL_DETAILS.fullmatch(value))


def _event_modifier_tail(
    values: list[str],
    *,
    path: str,
    allow_from: bool = False,
    allow_of: bool = False,
    markers: frozenset[str] | set[str] = frozenset(),
    allow_wisher: bool = False,
    allow_ability: bool = False,
) -> str | None:
    seen_tags: set[str] = set()
    for index, part in enumerate(values):
        tagged = _tagged_modifier_parts(part)
        if tagged is None:
            return _schema_error(
                f"{path}[{index}]",
                "must be a supported tagged producer modifier",
            )
        tag = tagged[0]
        if tag in seen_tags and tag not in {"silent", "still"}:
            return _schema_error(
                f"{path}[{index}]",
                "duplicates a producer modifier tag",
            )
        if allow_from and _source_modifier(part):
            seen_tags.add(tag)
            continue
        if allow_of and _of_modifier(part):
            seen_tags.add(tag)
            continue
        if allow_wisher and _wisher_modifier(part):
            seen_tags.add(tag)
            continue
        if allow_ability and _ability_modifier(part):
            seen_tags.add(tag)
            continue
        if _marker_modifier(part, markers):
            seen_tags.add(tag)
            continue
        return _schema_error(
            f"{path}[{index}]",
            "contains an unsupported modifier tag or payload",
        )
    return None


def _producer_hp_percent(hp: int, maxhp: int) -> float:
    return math.floor(((hp / maxhp) * 1000) + 0.5) / 10


def _canonical_optional_id(
    value: object,
    *,
    known: frozenset[str] | set[str] | None = None,
) -> bool:
    if value is None:
        return True
    if not _canonical_id(value):
        return False
    return known is None or value in known


def _canonical_id_list(
    value: object,
    *,
    known: frozenset[str] | set[str] | None = None,
) -> bool:
    return (
        isinstance(value, list)
        and all(
            _canonical_id(item) and (known is None or item in known)
            for item in value
        )
    )


def _boosts_schema_issue(value: object, *, path: str) -> str | None:
    if not isinstance(value, dict):
        return _schema_error(path, "must be a dictionary")
    if set(value) != _SUPPORTED_BOOSTS:
        missing = sorted(_SUPPORTED_BOOSTS - set(value))
        extra = sorted(set(value) - _SUPPORTED_BOOSTS)
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if extra:
            details.append(f"unsupported: {', '.join(extra)}")
        return _schema_error(
            path,
            "must contain the complete producer boost table"
            + (f" ({'; '.join(details)})" if details else ""),
        )
    for stat, amount in value.items():
        if (
            not _non_bool_int(amount)
            or amount < -6
            or amount > 6
        ):
            return _schema_error(
                f"{path}.{stat}",
                "boost stage must be an integer from -6 through 6",
            )
    return None


def _mechanics_event_schema_issue(value: object, *, path: str) -> str | None:
    """Validate explicit public variants emitted by the pinned Champions runtime."""

    if not isinstance(value, list) or not value:
        return _schema_error(path, "must be a non-empty list")
    if not all(isinstance(part, str) and part.strip() for part in value):
        return _schema_error(path, "entries must be non-empty strings")

    event = value[0]
    if event not in _PUBLIC_MECHANICS_EVENTS:
        return _schema_error(f"{path}[0]", "contains an unsupported mechanics event")

    if event in {"-damage", "-heal", "-sethp"}:
        if len(value) < 3:
            return _schema_error(path, f"{event} requires actor and condition")
        if not _canonical_actor(value[1], allow_side=True):
            return _schema_error(
                f"{path}[1]",
                "must be an active-slot or side-level producer identity",
            )
        if not _public_condition(value[2]):
            return _schema_error(
                f"{path}[2]",
                "must be a canonical pinned public HP/status condition",
            )
        return _event_modifier_tail(
            value[3:],
            path=f"{path}.modifiers",
            allow_from=True,
            allow_of=True,
            allow_wisher=True,
            markers={"partiallytrapped", "silent", "zeffect"},
        )

    if event == "-formechange":
        if len(value) < 3 or len(value) > 5:
            return _schema_error(
                path,
                "-formechange requires actor, species, and bounded metadata",
            )
        if not _canonical_slot(value[1]):
            return _schema_error(f"{path}[1]", "must be a canonical doubles slot")
        if value[2] not in SPECIES_IDS:
            return _schema_error(f"{path}[2]", "must be a pinned species id")
        tail = value[3:]
        if tail and tail[0] in {"[msg]", "[silent]"}:
            tail = tail[1:]
        if tail:
            if len(tail) != 1 or not _source_modifier(tail[0]):
                return _schema_error(
                    path,
                    "-formechange metadata must be message and/or typed source",
                )
            parts = _tagged_modifier_parts(tail[0])
            if (
                parts is None
                or parts[1] is None
                or not parts[1].startswith("ability:")
                or parts[1][8:] not in _FORME_CHANGE_ABILITY_IDS
            ):
                return _schema_error(
                    path,
                    "-formechange source must be a pinned forme-changing ability",
                )
        return None

    if event == "-hitcount":
        if len(value) not in {3, 8}:
            return _schema_error(
                path,
                "-hitcount must be bare or carry one complete action context",
            )
        if not _canonical_slot(value[1]):
            return _schema_error(f"{path}[1]", "must be a canonical doubles slot")
        if not _canonical_integer_text(value[2]) or int(value[2]) < 1:
            return _schema_error(
                f"{path}[2]",
                "must be the producer's canonical positive integer spelling",
            )
        if len(value) == 8:
            if value[3] != "[action]":
                return _schema_error(f"{path}[3]", "must be [action]")
            if value[4] not in {"player", "opponent"}:
                return _schema_error(f"{path}[4]", "must identify the public role")
            if value[5] not in {"1", "2"}:
                return _schema_error(f"{path}[5]", "must identify doubles slot 1 or 2")
            if not _known_public_move_id(value[6]):
                return _schema_error(f"{path}[6]", "must be a pinned move id")
            if value[7] not in {"selected", "called"}:
                return _schema_error(f"{path}[7]", "must identify move provenance")
        return None

    if event in {"-boost", "-unboost", "-setboost"}:
        if len(value) < 4:
            return _schema_error(path, f"{event} requires actor, stat, and stage")
        if not _canonical_slot(value[1]):
            return _schema_error(f"{path}[1]", "must be a canonical doubles slot")
        if value[2] not in _SUPPORTED_BOOSTS:
            return _schema_error(f"{path}[2]", "contains an unsupported boost dimension")
        if not _canonical_integer_text(value[3]):
            return _schema_error(
                f"{path}[3]",
                "must use the producer's canonical integer spelling",
            )
        amount = int(value[3])
        if event in {"-boost", "-unboost"}:
            if amount < 0 or amount > 6:
                return _schema_error(
                    f"{path}[3]",
                    "boost/unboost magnitude must be from 0 through 6",
                )
        elif amount < -6 or amount > 6:
            return _schema_error(
                f"{path}[3]",
                "setboost stage must be from -6 through 6",
            )
        return _event_modifier_tail(
            value[4:],
            path=f"{path}.modifiers",
            allow_from=True,
            markers={"silent", "zeffect"},
        )

    if event == "-mega":
        allowed_species = (
            TRANSFORM_ITEM_SPECIES_IDS.get(value[3], frozenset())
            if len(value) == 4 and isinstance(value[3], str)
            else frozenset()
        )
        if (
            len(value) != 4
            or not _canonical_slot(value[1])
            or value[2] not in SPECIES_IDS
            or value[3] not in MEGA_ITEM_IDS
            or value[2] not in allowed_species
        ):
            return _schema_error(
                path,
                "-mega requires a pinned species/Mega-item producer relationship",
            )
        return None

    if event in {"-swapsideconditions", "-ohko", "-nothing"}:
        if len(value) != 1:
            return _schema_error(path, f"{event} is a unary canonical event")
        return None

    if event == "-notarget":
        if len(value) not in {1, 2}:
            return _schema_error(path, "-notarget is unary or carries one actor")
        if len(value) == 2 and not _canonical_slot(value[1]):
            return _schema_error(f"{path}[1]", "must be a canonical doubles slot")
        return None

    if event == "-crit":
        if len(value) != 2 or not _canonical_slot(value[1]):
            return _schema_error(path, "-crit requires exactly one target slot")
        return None

    if event in {"-supereffective", "-resisted"}:
        if len(value) != 3 or not _canonical_slot(value[1]):
            return _schema_error(
                path,
                f"{event} requires target slot and Champions effectiveness level",
            )
        if value[2] not in {"1", "2"}:
            return _schema_error(
                f"{path}[2]",
                "must be Champions effectiveness level 1 or 2",
            )
        return None

    if event == "-immune":
        if len(value) < 2 or not _canonical_slot(value[1]):
            return _schema_error(path, "-immune requires a canonical target slot")
        return _event_modifier_tail(
            value[2:],
            path=f"{path}.modifiers",
            allow_from=True,
        )

    if event == "-miss":
        if len(value) not in {2, 3} or not _canonical_slot(value[1]):
            return _schema_error(
                path,
                "-miss requires source and optional target slots",
            )
        if len(value) == 3 and not _canonical_slot(value[2]):
            return _schema_error(f"{path}[2]", "must be a canonical target slot")
        return None

    if event in {
        "-mustrecharge",
        "-zpower",
        "-zbroken",
        "-dynamax",
        "-invertboost",
        "-clearboost",
    }:
        if len(value) != 2 or not _canonical_slot(value[1]):
            return _schema_error(
                path,
                f"{event} requires exactly one canonical Pokémon slot",
            )
        return None

    if event == "-primal":
        if (
            len(value) != 3
            or not _canonical_slot(value[1])
            or value[2] not in PRIMAL_ITEM_IDS
        ):
            return _schema_error(
                path,
                "-primal requires actor and a pinned Primal Orb",
            )
        return None

    if event in {"-status", "-curestatus"}:
        if len(value) < 3:
            return _schema_error(path, f"{event} requires actor and status")
        if not _canonical_slot(value[1]):
            return _schema_error(f"{path}[1]", "must be a canonical doubles slot")
        if not isinstance(value[2], str) or value[2] not in _MAJOR_STATUSES:
            return _schema_error(f"{path}[2]", "must be a major status id")
        return _event_modifier_tail(
            value[3:],
            path=f"{path}.modifiers",
            allow_from=True,
            allow_of=True,
            markers={"msg", "silent"},
        )

    if event == "-cureteam":
        if len(value) != 2 or not _canonical_actor(value[1], allow_side=True):
            return _schema_error(path, "-cureteam requires exactly one actor")
        return None

    if event in {"-item", "-enditem"}:
        if (
            len(value) < 3
            or not _canonical_slot(value[1])
            or not _known_item_id(value[2])
        ):
            return _schema_error(path, f"{event} requires actor and pinned item")
        return _event_modifier_tail(
            value[3:],
            path=f"{path}.modifiers",
            allow_from=True,
            allow_of=True,
            markers={"eat", "silent"},
        )

    if event == "-ability":
        if (
            len(value) < 3
            or not _canonical_slot(value[1])
            or not _known_ability_id(value[2])
        ):
            return _schema_error(path, "-ability requires actor and pinned ability")
        tail = value[3:]
        if not tail:
            return None
        if tail == ["boost"]:
            return None
        if not tail[0].startswith("["):
            if not _known_ability_id(tail[0]):
                return _schema_error(
                    f"{path}[3]",
                    "must be a prior pinned ability id",
                )
            tail = tail[1:]
        return _event_modifier_tail(
            tail,
            path=f"{path}.modifiers",
            allow_from=True,
            allow_of=True,
        )

    if event == "-endability":
        if len(value) != 2 or not _canonical_slot(value[1]):
            return _schema_error(path, "-endability requires exactly one actor")
        return None

    if event == "-terastallize":
        if (
            len(value) != 3
            or not _canonical_slot(value[1])
            or value[2] not in _TYPES
        ):
            return _schema_error(path, "-terastallize requires actor and Pokémon type")
        return None

    if event == "-transform":
        if (
            len(value) not in {3, 4}
            or not _canonical_slot(value[1])
            or not _canonical_slot(value[2])
        ):
            return _schema_error(path, "-transform requires actor and target slots")
        if len(value) == 4 and not _source_modifier(value[3]):
            return _schema_error(
                f"{path}[3]",
                "must be canonical transform provenance",
            )
        return None

    if event == "-waiting":
        if (
            len(value) != 3
            or not _canonical_slot(value[1])
            or not _canonical_slot(value[2])
        ):
            return _schema_error(path, "-waiting requires source and target slots")
        return None

    if event == "-swapboost":
        if (
            len(value) not in {4, 5}
            or not _canonical_slot(value[1])
            or not _canonical_slot(value[2])
        ):
            return _schema_error(path, "-swapboost requires source and target")
        if len(value) == 4:
            if value[3] != "[from]:move:heartswap":
                return _schema_error(
                    f"{path}[3]",
                    "provenance-only swap must be Heart Swap",
                )
            return None
        expected_source = _PINNED_TRANSFER_GROUPS.get(value[3])
        if expected_source is None or value[4] != f"[from]:{expected_source}":
            return _schema_error(
                path,
                "boost group must be the pinned Guard Swap or Power Swap variant",
            )
        return None

    if event == "-copyboost":
        if (
            len(value) != 4
            or not _canonical_slot(value[1])
            or not _canonical_slot(value[2])
            or value[3] not in {
                "[from]:move:psychup",
                "[from]:ability:costar",
            }
        ):
            return _schema_error(
                path,
                "-copyboost must be the pinned Psych Up or Costar variant",
            )
        return None

    if event == "-clearpositiveboost":
        if (
            len(value) != 4
            or not _canonical_slot(value[1])
            or not _canonical_slot(value[2])
            or not _known_move_identity(value[3])
        ):
            return _schema_error(
                path,
                "-clearpositiveboost requires target, source, and move effect",
            )
        return None

    if event == "-clearnegativeboost":
        if len(value) not in {2, 3} or not _canonical_slot(value[1]):
            return _schema_error(path, "-clearnegativeboost requires an actor")
        if len(value) == 3 and value[2] != "[zeffect]":
            return _schema_error(f"{path}[2]", "must be [zeffect]")
        return None

    if event == "-clearallboost":
        if len(value) != 1:
            return _schema_error(path, "-clearallboost is a unary canonical event")
        return None

    if event == "-weather":
        if len(value) < 2 or (
            value[1] != "none" and value[1] not in WEATHER_IDS
        ):
            return _schema_error(path, "-weather requires a pinned weather id")
        return _event_modifier_tail(
            value[2:],
            path=f"{path}.modifiers",
            allow_from=True,
            allow_of=True,
            markers={"upkeep"},
        )

    if event in {"-fieldstart", "-fieldend"}:
        if len(value) < 2 or not _domain_effect_identity(
            value[1],
            PSEUDO_WEATHER_IDS | TERRAIN_IDS,
        ):
            return _schema_error(
                path,
                f"{event} requires a pinned field-condition identity",
            )
        return _event_modifier_tail(
            value[2:],
            path=f"{path}.modifiers",
            allow_from=True,
            allow_of=True,
        )

    if event == "-fieldactivate":
        if len(value) < 2 or not (
            value[1] in FIELD_ACTIVATE_IDENTITIES
            or _domain_effect_identity(
                value[1],
                WEATHER_IDS | PSEUDO_WEATHER_IDS | TERRAIN_IDS,
            )
        ):
            return _schema_error(
                path,
                "-fieldactivate requires a pinned field activation identity",
            )
        return _event_modifier_tail(
            value[2:],
            path=f"{path}.modifiers",
            allow_from=True,
            allow_of=True,
        )

    if event in {"-sidestart", "-sideend"}:
        if (
            len(value) < 3
            or not _canonical_side(value[1])
            or not _domain_effect_identity(value[2], SIDE_CONDITION_IDS)
        ):
            return _schema_error(
                path,
                f"{event} requires side and pinned side-condition identity",
            )
        return _event_modifier_tail(
            value[3:],
            path=f"{path}.modifiers",
            allow_from=True,
            allow_of=True,
        )

    if event in {"-start", "-end"}:
        if len(value) < 3 or not _canonical_slot(value[1]):
            return _schema_error(path, f"{event} requires actor and effect")

        effect = value[2]
        tail = value[3:]

        if event == "-end" and effect in {"typechange", "typeadd"}:
            return _event_modifier_tail(
                tail,
                path=f"{path}.modifiers",
                markers={"silent"},
            )

        if effect == "typechange":
            # Reflect Type is the one pinned form that exposes only provenance;
            # ordinary type changes expose the resulting type payload first.
            if tail and _source_modifier(tail[0]):
                parts = _tagged_modifier_parts(tail[0])
                if (
                    parts is None
                    or parts[1] != "move:reflecttype"
                ):
                    return _schema_error(
                        f"{path}[3]",
                        "typechange provenance-only form must be Reflect Type",
                    )
                return _event_modifier_tail(
                    tail,
                    path=f"{path}.modifiers",
                    allow_from=True,
                    allow_of=True,
                    markers={"silent"},
                )
            if not tail or not _type_payload(tail[0]):
                return _schema_error(
                    f"{path}[3]",
                    "must expose the pinned resulting type payload",
                )
            return _event_modifier_tail(
                tail[1:],
                path=f"{path}.modifiers",
                allow_from=True,
                allow_of=True,
                markers={"silent"},
            )

        if effect == "typeadd":
            if not tail or not _type_payload(tail[0]):
                return _schema_error(
                    f"{path}[3]",
                    "must expose the pinned added-type payload",
                )
            return _event_modifier_tail(
                tail[1:],
                path=f"{path}.modifiers",
                allow_from=True,
                allow_of=True,
                markers={"silent"},
            )

        if event == "-start" and effect == "charge":
            if not tail:
                return None
            if not _known_public_move_id(tail[0]):
                return _schema_error(
                    f"{path}[3]",
                    "Charge producer payload must identify the active move",
                )
            return _event_modifier_tail(
                tail[1:],
                path=f"{path}.modifiers",
                allow_from=True,
            )

        if event == "-start" and effect == "disable":
            if not tail or not _known_public_move_id(tail[0]):
                return _schema_error(
                    f"{path}[3]",
                    "Disable producer payload must identify the disabled move",
                )
            return _event_modifier_tail(
                tail[1:],
                path=f"{path}.modifiers",
                allow_from=True,
                allow_of=True,
            )

        if event == "-start" and effect == "mimic":
            if len(tail) != 1 or not _known_public_move_id(tail[0]):
                return _schema_error(
                    f"{path}[3]",
                    "Mimic producer payload must identify the copied move",
                )
            return None

        if event == "-start" and effect == "dynamax":
            if tail not in ([], ["gmax"]):
                return _schema_error(
                    path,
                    "Dynamax producer payload is empty or exact G-Max marker",
                )
            return None

        if effect == "confusion":
            return _event_modifier_tail(
                tail,
                path=f"{path}.modifiers",
                allow_from=True,
                allow_of=True,
                markers={"fatigue"},
            )

        if event == "-start" and effect == "uproar":
            return _event_modifier_tail(
                tail,
                path=f"{path}.modifiers",
                markers={"upkeep"},
            )

        if event == "-start" and re.fullmatch(r"stockpile[1-3]", effect):
            if tail:
                return _schema_error(path, "Stockpile layer event has no tail")
            return None

        if event == "-start" and re.fullmatch(r"perish[0-3]", effect):
            return _event_modifier_tail(
                tail,
                path=f"{path}.modifiers",
                markers={"silent"},
            )

        dynamic_plain = (
            re.fullmatch(r"fallen[1-5]", effect)
            or re.fullmatch(
                r"(?:protosynthesis|quarkdrive)(?:atk|def|spa|spd|spe)",
                effect,
            )
        )
        if effect.startswith("item:"):
            return _schema_error(
                f"{path}[2]",
                "items are not pinned start/end producer effects",
            )
        if effect.startswith("ability:"):
            valid_effect = effect in _START_END_ABILITY_EFFECTS
        elif effect.startswith("move:"):
            valid_effect = effect in _START_END_MOVE_EFFECTS
        else:
            valid_effect = (
                effect in _START_END_PLAIN_EFFECTS
                or dynamic_plain is not None
            )
        if not valid_effect:
            return _schema_error(
                f"{path}[2]",
                "must be an effect emitted by a pinned start/end producer",
            )
        return _event_modifier_tail(
            tail,
            path=f"{path}.modifiers",
            allow_from=True,
            allow_of=True,
            markers={"msg", "partiallytrapped", "silent", "interrupt"},
        )

    if event == "-prepare":
        if (
            len(value) not in {3, 4}
            or not _canonical_slot(value[1])
            or not _known_move_id(value[2])
        ):
            return _schema_error(path, "-prepare requires actor and pinned move")
        if len(value) == 4 and not (
            _canonical_slot(value[3]) or value[3] == "[premajor]"
        ):
            return _schema_error(
                f"{path}[3]",
                "must be a target slot or [premajor]",
            )
        return None

    if event in {"-singlemove", "-singleturn"}:
        domain = (
            _SINGLE_MOVE_EFFECT_IDENTITIES
            if event == "-singlemove"
            else _SINGLE_TURN_EFFECT_IDENTITIES
        )
        if (
            len(value) < 3
            or not _canonical_slot(value[1])
            or value[2] not in domain
        ):
            return _schema_error(
                path,
                f"{event} requires an effect emitted by its pinned producer",
            )
        return _event_modifier_tail(
            value[3:],
            path=f"{path}.modifiers",
            allow_of=True,
            markers={"silent", "zeffect"},
        )

    if event == "-burst":
        allowed_species = (
            TRANSFORM_ITEM_SPECIES_IDS.get(value[3], frozenset())
            if len(value) == 4 and isinstance(value[3], str)
            else frozenset()
        )
        if (
            len(value) != 4
            or not _canonical_slot(value[1])
            or value[2] not in SPECIES_IDS
            or value[3] not in _BURST_ITEM_IDS
            or value[2] not in allowed_species
        ):
            return _schema_error(
                path,
                "-burst requires a pinned species/Ultra-Burst-item relationship",
            )
        return None

    if event == "-fail":
        if len(value) < 2 or not _canonical_slot(value[1]):
            return _schema_error(path, "-fail requires a canonical actor")
        tail = value[2:]
        if tail and not tail[0].startswith("["):
            if not _known_effect_identity(tail[0]):
                return _schema_error(f"{path}[2]", "must be a pinned action/effect")
            tail = tail[1:]
        return _event_modifier_tail(
            tail,
            path=f"{path}.modifiers",
            allow_from=True,
            allow_of=True,
            markers={"silent", "still"},
        )

    if event == "-block":
        if (
            len(value) < 3
            or not _canonical_slot(value[1])
            or not _known_effect_identity(value[2])
        ):
            return _schema_error(path, "-block requires target and blocking effect")
        if len(value) == 3:
            return None
        if len(value) < 5:
            return _schema_error(
                path,
                "-block optional move form requires move and attacker",
            )
        if not _known_move_identity(value[3]):
            return _schema_error(f"{path}[3]", "must be a pinned move")
        if not _canonical_slot(value[4]):
            return _schema_error(f"{path}[4]", "must be a canonical attacker slot")
        return _event_modifier_tail(
            value[5:],
            path=f"{path}.modifiers",
            allow_of=True,
        )

    if event == "-activate":
        if len(value) < 3 or not _canonical_slot(value[1]):
            return _schema_error(
                path,
                "-activate requires actor and activation effect",
            )
        effect = value[2]
        tail = value[3:]

        if effect == "confusion":
            if tail:
                return _schema_error(path, "confusion activation has no payload")
            return None

        pp_limit = _PP_DEDUCTION_ACTIVATION_LIMITS.get(effect)
        if pp_limit is not None:
            if len(tail) != 2 or not _known_public_move_id(tail[0]):
                return _schema_error(
                    path,
                    f"{effect} requires move id and PP deduction",
                )
            if (
                not _canonical_integer_text(tail[1])
                or int(tail[1]) < 1
                or int(tail[1]) > pp_limit
            ):
                return _schema_error(
                    f"{path}[4]",
                    f"{effect} PP deduction must be 1 through {pp_limit}",
                )
            return None

        if effect == "item:leppaberry":
            if (
                len(tail) != 2
                or not _known_public_move_id(tail[0])
                or tail[1] != "[consumed]"
            ):
                return _schema_error(
                    path,
                    "Leppa Berry requires restored move and [consumed]",
                )
            return None

        if effect == "item:custapberry":
            if tail != ["[consumed]"]:
                return _schema_error(path, "Custap Berry requires [consumed]")
            return None

        if effect in {"item:focusband", "item:quickclaw"}:
            if tail:
                return _schema_error(path, f"{effect} activation has no payload")
            return None

        if effect in {"item:safetygoggles", "item:mysteryberry"}:
            if len(tail) != 1 or not _known_public_move_id(tail[0]):
                return _schema_error(path, f"{effect} requires one move payload")
            return None

        if effect == "ability:forewarn":
            if (
                len(tail) != 2
                or not _known_public_move_id(tail[0])
                or not _of_modifier(tail[1])
            ):
                return _schema_error(
                    path,
                    "Forewarn requires warned move and [of] target",
                )
            return None

        if effect == "ability:symbiosis":
            if (
                len(tail) != 2
                or not _known_item_id(tail[0])
                or not _of_modifier(tail[1])
            ):
                return _schema_error(
                    path,
                    "Symbiosis requires transferred item and [of] target",
                )
            return None

        if effect in {"ability:protosynthesis", "ability:quarkdrive"}:
            if tail not in ([], ["[fromitem]"]):
                return _schema_error(
                    path,
                    f"{effect} accepts only the pinned [fromitem] marker",
                )
            return None

        if effect == "orichalcumpulse":
            if tail not in ([], ["[source]"]):
                return _schema_error(
                    path,
                    "Orichalcum Pulse accepts only the pinned [source] marker",
                )
            return None

        if effect == "ability:persistent":
            if len(tail) != 1 or not _move_modifier(tail[0]):
                return _schema_error(
                    path,
                    "Persistent activation requires one [move] payload",
                )
            return None

        if effect == "move:powder":
            if len(tail) != 1 or not _move_modifier(tail[0]):
                return _schema_error(path, "Powder activation requires [move]")
            return None

        if effect == "move:magnitude":
            if (
                len(tail) != 1
                or not _canonical_integer_text(tail[0])
                or int(tail[0]) not in range(4, 11)
            ):
                return _schema_error(path, "Magnitude requires level 4 through 10")
            return None

        if effect == "move:poltergeist":
            if len(tail) != 1 or not _known_item_id(tail[0]):
                return _schema_error(path, "Poltergeist requires a pinned item")
            return None

        if effect in {
            "move:grudge",
            "move:matblock",
            "move:sketch",
        }:
            if len(tail) != 1 or not _known_public_move_id(tail[0]):
                return _schema_error(path, f"{effect} requires one move payload")
            return None

        if effect == "skillswap":
            if (
                len(tail) != 3
                or not _known_ability_id(tail[0])
                or not _known_ability_id(tail[1])
                or not _of_modifier(tail[2])
            ):
                return _schema_error(
                    path,
                    "Skill Swap requires two abilities and [of] target",
                )
            return None

        if effect == "move:substitute":
            if tail not in ([], ["[damage]"], ["[broken]"]):
                return _schema_error(
                    path,
                    "Substitute activation has an unsupported marker",
                )
            return None

        if effect == "move:protect" and tail:
            return _schema_error(
                path,
                "Protect activation has no positional payload",
            )

        if effect not in ACTIVATION_EFFECT_IDENTITIES:
            return _schema_error(
                f"{path}[2]",
                "must be an effect emitted by a pinned activation producer",
            )

        # The only generic positional producer form is actor + [ability].
        # Everything else must be an effect-specific variant above or typed
        # producer modifiers; catalog membership alone is not positional authority.
        if (
            len(tail) == 2
            and _canonical_actor(tail[0], allow_side=True)
            and _ability_modifier(tail[1])
        ):
            return None

        seen_tags: set[str] = set()
        for index, part in enumerate(tail, start=3):
            tagged = _tagged_modifier_parts(part)
            if tagged is None:
                return _schema_error(
                    f"{path}[{index}]",
                    "contains an unsupported positional activation payload",
                )
            tag = tagged[0]
            if tag in seen_tags:
                return _schema_error(
                    f"{path}[{index}]",
                    "duplicates an activation modifier tag",
                )
            if (
                _ability_modifier(part)
                or _source_modifier(part)
                or _of_modifier(part)
                or _marker_modifier(part, {"broken", "silent"})
            ):
                seen_tags.add(tag)
                continue
            return _schema_error(
                f"{path}[{index}]",
                "contains unsupported activation modifier",
            )
        return None

    return _schema_error(path, f"{event} lacks an explicit v7 producer variant")


def _own_pokemon_schema_issue(value: object, *, path: str) -> str | None:
    if not isinstance(value, dict):
        return _schema_error(path, "must be a dictionary")
    issue = _exact_keys(
        value,
        path=path,
        keys={
            "species",
            "hp",
            "maxhp",
            "hp_percent",
            "fainted",
            "status",
            "boosts",
            "item",
            "ability",
            "moves",
            "speed",
            "damaging_move_count",
            "active",
        },
    )
    if issue:
        return issue
    if not isinstance(value["species"], str) or not value["species"].strip():
        return _schema_error(f"{path}.species", "must be a non-empty string")
    for field in ("hp", "speed", "damaging_move_count"):
        if not _non_bool_int(value[field], minimum=0):
            return _schema_error(f"{path}.{field}", "must be a non-negative integer")
    if not _non_bool_int(value["maxhp"], minimum=1):
        return _schema_error(f"{path}.maxhp", "must be a positive integer")
    if value["hp"] > value["maxhp"]:
        return _schema_error(f"{path}.hp", "must not exceed maxhp")
    if not _percentage(value["hp_percent"]):
        return _schema_error(
            f"{path}.hp_percent",
            "must be a finite percentage from 0 through 100",
        )
    expected_percent = _producer_hp_percent(value["hp"], value["maxhp"])
    if value["hp_percent"] != expected_percent:
        return _schema_error(
            f"{path}.hp_percent",
            "must exactly match producer hp/maxhp rounding",
        )
    if not isinstance(value["fainted"], bool):
        return _schema_error(f"{path}.fainted", "must be boolean")
    if value["fainted"] != (value["hp"] == 0):
        return _schema_error(f"{path}.fainted", "must agree with zero HP")
    status = value["status"]
    if status is not None and (
        not isinstance(status, str)
        or status not in _MAJOR_OR_FAINT_STATUSES
        or (status == "fnt" and not value["fainted"])
    ):
        return _schema_error(
            f"{path}.status",
            "must be a living major status, fnt on a fainted mon, or null",
        )
    issue = _boosts_schema_issue(value["boosts"], path=f"{path}.boosts")
    if issue:
        return issue
    if not _canonical_optional_id(value["item"], known=ITEM_IDS):
        return _schema_error(f"{path}.item", "must be a pinned item id or null")
    if not _canonical_optional_id(value["ability"], known=ABILITY_IDS):
        return _schema_error(f"{path}.ability", "must be a pinned ability id or null")
    if not isinstance(value["moves"], list) or not 1 <= len(value["moves"]) <= 4:
        return _schema_error(f"{path}.moves", "must contain one through four moves")
    move_ids = [_display_move_id(move) for move in value["moves"]]
    if any(move_id is None for move_id in move_ids):
        return _schema_error(
            f"{path}.moves",
            "must contain pinned public move display names",
        )
    expected_damaging = sum(
        MOVE_CATEGORIES[move_id] != "Status"
        for move_id in move_ids
        if move_id is not None
    )
    if value["damaging_move_count"] != expected_damaging:
        return _schema_error(
            f"{path}.damaging_move_count",
            "must match pinned public move categories",
        )
    if not isinstance(value["active"], bool):
        return _schema_error(f"{path}.active", "must be boolean")
    return None


def _public_active_schema_issue(value: object, *, path: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        return _schema_error(path, "must be a dictionary or null")
    issue = _exact_keys(
        value,
        path=path,
        keys={
            "species",
            "base_species",
            "hp_percent",
            "fainted",
            "status",
            "boosts",
        },
    )
    if issue:
        return issue
    for field in ("species", "base_species"):
        if not isinstance(value[field], str) or not value[field].strip():
            return _schema_error(f"{path}.{field}", "must be a non-empty string")
    if not _percentage(value["hp_percent"]):
        return _schema_error(
            f"{path}.hp_percent",
            "must be a finite percentage from 0 through 100",
        )
    if not isinstance(value["fainted"], bool):
        return _schema_error(f"{path}.fainted", "must be boolean")
    if value["fainted"] != (value["hp_percent"] == 0):
        return _schema_error(
            f"{path}.fainted",
            "must agree with zero public HP",
        )
    status = value["status"]
    if status is not None and (
        not isinstance(status, str)
        or status not in _MAJOR_OR_FAINT_STATUSES
        or (status == "fnt" and not value["fainted"])
    ):
        return _schema_error(
            f"{path}.status",
            "must be a living major status, fnt on a fainted mon, or null",
        )
    return _boosts_schema_issue(value["boosts"], path=f"{path}.boosts")


def _revealed_pokemon_schema_issue(value: object, *, path: str) -> str | None:
    if not isinstance(value, dict):
        return _schema_error(path, "must be a dictionary")
    issue = _exact_keys(
        value,
        path=path,
        keys={
            "species",
            "moves",
            "items",
            "abilities",
            "hp_percent",
            "status",
            "fainted",
            "seen",
        },
    )
    if issue:
        return issue
    if not isinstance(value["species"], str) or not value["species"].strip():
        return _schema_error(f"{path}.species", "must be a non-empty string")
    if not _canonical_id_list(value["moves"], known=MOVE_IDS):
        return _schema_error(f"{path}.moves", "must contain pinned move ids")
    if not _canonical_id_list(value["items"], known=ITEM_IDS):
        return _schema_error(f"{path}.items", "must contain pinned item ids")
    if not _canonical_id_list(value["abilities"], known=ABILITY_IDS):
        return _schema_error(f"{path}.abilities", "must contain pinned ability ids")
    for field in ("moves", "items", "abilities"):
        if value[field] != sorted(set(value[field])):
            return _schema_error(
                f"{path}.{field}",
                "must equal the producer's sorted unique knowledge list",
            )
    if value["hp_percent"] is not None and not _percentage(value["hp_percent"]):
        return _schema_error(
            f"{path}.hp_percent",
            "must be a finite percentage from 0 through 100 or null",
        )
    if not isinstance(value["fainted"], bool):
        return _schema_error(f"{path}.fainted", "must be boolean")
    if not isinstance(value["seen"], bool):
        return _schema_error(f"{path}.seen", "must be boolean")
    status = value["status"]
    if status is not None and (
        not isinstance(status, str)
        or status not in _MAJOR_OR_FAINT_STATUSES
        or (status == "fnt" and not value["fainted"])
    ):
        return _schema_error(
            f"{path}.status",
            "must be a living major status, fnt on a fainted mon, or null",
        )
    if value["hp_percent"] is not None and value["fainted"] != (
        value["hp_percent"] == 0
    ):
        return _schema_error(
            f"{path}.fainted",
            "must agree with zero revealed HP",
        )
    return None


def _opponent_action_schema_issue(value: object, *, path: str) -> str | None:
    if not isinstance(value, dict):
        return _schema_error(path, "must be a dictionary")
    issue = _exact_keys(
        value,
        path=path,
        keys={"turn", "slot", "move", "target"},
    )
    if issue:
        return issue
    if not _non_bool_int(value["turn"], minimum=1):
        return _schema_error(f"{path}.turn", "must be a positive integer")
    if not _non_bool_int(value["slot"]) or value["slot"] not in {1, 2}:
        return _schema_error(f"{path}.slot", "must be integer doubles slot 1 or 2")
    if not _known_public_move_id(value["move"]):
        return _schema_error(f"{path}.move", "must be a pinned move id")
    target = value["target"]
    if target is not None and (
        not _non_bool_int(target) or target not in {-2, -1, 1, 2}
    ):
        return _schema_error(
            f"{path}.target",
            "must be an integer doubles target location or null",
        )
    return None



def _execution_action_schema_issue(value: object, *, path: str) -> str | None:
    if not isinstance(value, dict):
        return _schema_error(path, "must be a dictionary")
    outcome = value.get("outcome")
    if outcome == "executed":
        keys = {
            "side",
            "slot",
            "outcome",
            "move",
            "source",
            "provenance",
            "effects",
        }
    elif outcome == "prevented":
        keys = {
            "side",
            "slot",
            "outcome",
            "reason",
            "attempted_move",
            "effects",
        }
    else:
        return _schema_error(f"{path}.outcome", "must be executed or prevented")
    issue = _exact_keys(value, path=path, keys=keys)
    if issue:
        return issue
    if value["side"] not in {"player", "opponent"}:
        return _schema_error(f"{path}.side", "must be player or opponent")
    if not _non_bool_int(value["slot"]) or value["slot"] not in {1, 2}:
        return _schema_error(f"{path}.slot", "must be integer doubles slot 1 or 2")
    effects = value["effects"]
    if (
        not isinstance(effects, list)
        or any(not isinstance(effect, str) for effect in effects)
        or effects != sorted(set(effects))
        or any(effect not in _PUBLIC_ACTION_EFFECTS for effect in effects)
    ):
        return _schema_error(
            f"{path}.effects",
            "must equal the producer's sorted unique public action effects",
        )
    if outcome == "executed":
        if not _known_public_move_id(value["move"]):
            return _schema_error(f"{path}.move", "must be a pinned move id")
        if value["source"] not in {"selected", "called"}:
            return _schema_error(f"{path}.source", "must be selected or called")
        provenance = value["provenance"]
        if (
            not isinstance(provenance, list)
            or any(not isinstance(item, str) for item in provenance)
            or any(not _source_modifier(item) for item in provenance)
        ):
            return _schema_error(
                f"{path}.provenance",
                "must contain canonical [from] provenance entries",
            )
        if (value["source"] == "called") != bool(provenance):
            return _schema_error(
                f"{path}.source",
                "must be called iff [from] provenance is present",
            )
    else:
        if not (
            _known_effect_identity(value["reason"])
            or value["reason"] in _PUBLIC_PREVENTION_IDENTITIES
        ):
            return _schema_error(
                f"{path}.reason",
                "must be pinned public prevention evidence",
            )
        if (
            value["attempted_move"] is not None
            and not _known_public_move_id(value["attempted_move"])
        ):
            return _schema_error(
                f"{path}.attempted_move",
                "must be a pinned move id or null",
            )
    return None


def _transition_ledger_schema_issue(view: dict[str, Any]) -> str | None:
    execution = view.get("public_execution_delta")
    if not isinstance(execution, dict):
        return _schema_error("$.public_execution_delta", "must be a dictionary")
    issue = _exact_keys(
        execution,
        path="$.public_execution_delta",
        keys={"turn", "actions"},
    )
    if issue:
        return issue
    if execution["turn"] is not None and not _non_bool_int(
        execution["turn"],
        minimum=1,
    ):
        return _schema_error(
            "$.public_execution_delta.turn",
            "must be a positive integer or null",
        )
    if not isinstance(execution["actions"], list):
        return _schema_error("$.public_execution_delta.actions", "must be a list")
    for index, action in enumerate(execution["actions"]):
        issue = _execution_action_schema_issue(
            action,
            path=f"$.public_execution_delta.actions[{index}]",
        )
        if issue:
            return issue

    mechanics = view.get("public_event_delta")
    if not isinstance(mechanics, dict):
        return _schema_error("$.public_event_delta", "must be a dictionary")
    issue = _exact_keys(
        mechanics,
        path="$.public_event_delta",
        keys={"turn", "events", "unsupported"},
    )
    if issue:
        return issue
    if mechanics["turn"] is not None and not _non_bool_int(
        mechanics["turn"],
        minimum=1,
    ):
        return _schema_error(
            "$.public_event_delta.turn",
            "must be a positive integer or null",
        )
    events = mechanics["events"]
    if not isinstance(events, list):
        return _schema_error("$.public_event_delta.events", "must be a list")
    for index, event in enumerate(events):
        issue = _mechanics_event_schema_issue(
            event,
            path=f"$.public_event_delta.events[{index}]",
        )
        if issue:
            return issue
    unsupported = mechanics["unsupported"]
    if not isinstance(unsupported, list):
        return _schema_error(
            "$.public_event_delta.unsupported",
            "must be a list",
        )
    if not all(
        isinstance(item, str) and item.strip()
        for item in unsupported
    ):
        return _schema_error(
            "$.public_event_delta.unsupported",
            "entries must be non-empty strings",
        )
    if len(set(unsupported)) != len(unsupported):
        return _schema_error(
            "$.public_event_delta.unsupported",
            "entries must be unique",
        )
    return None


def _request_pokemon_schema_issue(
    value: object,
    *,
    path: str,
    expected_side: str,
) -> str | None:
    if not isinstance(value, dict):
        return _schema_error(path, "must be a dictionary")
    required = {
        "ident",
        "details",
        "condition",
        "active",
        "stats",
        "moves",
        "baseAbility",
        "ability",
        "item",
        "pokeball",
        "commanding",
        "reviving",
    }
    missing = sorted(required - set(value))
    extra = sorted(set(value) - required)
    if missing:
        return _schema_error(path, f"missing required field(s): {', '.join(missing)}")
    if extra:
        return _schema_error(path, f"unexpected field(s): {', '.join(extra)}")
    ident = value["ident"]
    if not isinstance(ident, str):
        return _schema_error(f"{path}.ident", "must be a string")
    ident_match = _REQUEST_IDENT.fullmatch(ident)
    if ident_match is None or ident_match.group(1) != expected_side:
        return _schema_error(
            f"{path}.ident",
            "must carry the same side id as its request roster",
        )
    if not isinstance(value["details"], str) or not value["details"].strip():
        return _schema_error(f"{path}.details", "must be a non-empty string")
    if not _request_condition(value["condition"]):
        return _schema_error(
            f"{path}.condition",
            "must be an exact producer request condition",
        )
    if not _known_ability_id(value["baseAbility"]):
        return _schema_error(f"{path}.baseAbility", "must be a pinned ability id")
    ability = value["ability"]
    if not isinstance(ability, str) or (
        ability and not _known_ability_id(ability)
    ):
        return _schema_error(
            f"{path}.ability",
            "must be empty or a pinned ability id",
        )
    item = value["item"]
    if not isinstance(item, str) or (item and not _known_item_id(item)):
        return _schema_error(f"{path}.item", "must be empty or a pinned item id")
    pokeball = value["pokeball"]
    if not isinstance(pokeball, str) or (
        pokeball and not _known_item_id(pokeball)
    ):
        return _schema_error(
            f"{path}.pokeball",
            "must be empty or a pinned item id",
        )
    if not isinstance(value["active"], bool):
        return _schema_error(f"{path}.active", "must be boolean")
    stats = value["stats"]
    if not isinstance(stats, dict) or set(stats) != {"atk", "def", "spa", "spd", "spe"}:
        return _schema_error(
            f"{path}.stats",
            "must contain exactly atk, def, spa, spd, spe",
        )
    if not all(_non_bool_int(amount, minimum=0) for amount in stats.values()):
        return _schema_error(f"{path}.stats", "stat values must be non-negative integers")
    if (
        not isinstance(value["moves"], list)
        or not value["moves"]
        or not all(_known_public_move_id(move) for move in value["moves"])
    ):
        return _schema_error(
            f"{path}.moves",
            "must contain one or more pinned move ids",
        )
    for field in ("commanding", "reviving"):
        if not isinstance(value[field], bool):
            return _schema_error(f"{path}.{field}", "must be boolean")
    return None


def _request_side_schema_issue(value: object, *, path: str) -> str | None:
    if not isinstance(value, dict):
        return _schema_error(path, "must be a dictionary")
    required = {"name", "id", "pokemon"}
    allowed = required | {"noCancel"}
    missing = sorted(required - set(value))
    extra = sorted(set(value) - allowed)
    if missing:
        return _schema_error(path, f"missing required field(s): {', '.join(missing)}")
    if extra:
        return _schema_error(path, f"unexpected field(s): {', '.join(extra)}")
    if not isinstance(value["name"], str):
        return _schema_error(f"{path}.name", "must be a string")
    side_id = value["id"]
    if not isinstance(side_id, str) or side_id not in {"p1", "p2"}:
        return _schema_error(f"{path}.id", "must be a supported p1/p2 side id")
    if "noCancel" in value and not isinstance(value["noCancel"], bool):
        return _schema_error(f"{path}.noCancel", "must be boolean")
    if not isinstance(value["pokemon"], list):
        return _schema_error(f"{path}.pokemon", "must be a list")
    for index, pokemon in enumerate(value["pokemon"]):
        issue = _request_pokemon_schema_issue(
            pokemon,
            path=f"{path}.pokemon[{index}]",
            expected_side=side_id,
        )
        if issue:
            return issue
    return None


def _move_request_data_schema_issue(value: object, *, path: str) -> str | None:
    if not isinstance(value, dict):
        return _schema_error(path, "must be a dictionary")

    keys = set(value)
    locked_keys = {"move", "id"}
    struggle_keys = {"move", "id", "target", "disabled"}
    ordinary_keys = {"move", "id", "pp", "maxpp", "target", "disabled"}

    if keys == locked_keys:
        if value["id"] == "recharge":
            if value["move"] != "Recharge":
                return _schema_error(path, "recharge must use its pinned display name")
            return None
        if (
            not _known_move_id(value["id"])
            or _display_move_id(value["move"]) != value["id"]
        ):
            return _schema_error(
                path,
                "locked move display name/id must match pinned metadata",
            )
        return None

    if keys == struggle_keys:
        if (
            value["move"] != "Struggle"
            or value["id"] != "struggle"
            or value["target"] != "randomNormal"
            or value["disabled"] is not False
        ):
            return _schema_error(
                path,
                "reduced four-field move entry must be canonical Struggle",
            )
        return None

    if keys != ordinary_keys:
        return _schema_error(
            path,
            "move entry must be a pinned locked, Struggle, or ordinary variant",
        )

    if not _known_move_id(value["id"]):
        return _schema_error(f"{path}.id", "must be a pinned move id")
    if _display_move_id(value["move"]) != value["id"]:
        return _schema_error(
            f"{path}.move",
            "must be the pinned public display name for its move id",
        )
    if not _non_bool_int(value["pp"], minimum=0):
        return _schema_error(f"{path}.pp", "must be a non-negative integer")
    if not _non_bool_int(value["maxpp"], minimum=1):
        return _schema_error(f"{path}.maxpp", "must be a positive integer")
    if value["pp"] > value["maxpp"]:
        return _schema_error(f"{path}.pp", "must not exceed maxpp")
    if (
        not isinstance(value["target"], str)
        or value["target"] not in _MOVE_TARGETS
    ):
        return _schema_error(
            f"{path}.target",
            "must be a pinned Showdown move target",
        )
    if not isinstance(value["disabled"], (str, bool)):
        return _schema_error(f"{path}.disabled", "must be a string or boolean")
    return None



def _max_moves_schema_issue(value: object, *, path: str) -> str | None:
    if not isinstance(value, dict):
        return _schema_error(path, "must be a dictionary")
    if not set(value).issubset({"maxMoves", "gigantamax"}) or "maxMoves" not in value:
        return _schema_error(path, "contains invalid max-move fields")
    if not isinstance(value["maxMoves"], list):
        return _schema_error(f"{path}.maxMoves", "must be a list")
    for index, move in enumerate(value["maxMoves"]):
        if not isinstance(move, dict):
            return _schema_error(f"{path}.maxMoves[{index}]", "must be a dictionary")
        if not {"move", "target"}.issubset(move) or not set(move).issubset(
            {"move", "target", "disabled"}
        ):
            return _schema_error(
                f"{path}.maxMoves[{index}]",
                "contains invalid max-move fields",
            )
        if not isinstance(move["move"], str) or not move["move"].strip():
            return _schema_error(
                f"{path}.maxMoves[{index}].move",
                "must be a non-empty string",
            )
        if (
            not isinstance(move["target"], str)
            or move["target"] not in _MOVE_TARGETS
        ):
            return _schema_error(
                f"{path}.maxMoves[{index}].target",
                "must be a pinned Showdown move target",
            )
        if "disabled" in move and not isinstance(move["disabled"], bool):
            return _schema_error(
                f"{path}.maxMoves[{index}].disabled",
                "must be boolean",
            )
    if "gigantamax" in value and not isinstance(value["gigantamax"], str):
        return _schema_error(f"{path}.gigantamax", "must be a string")
    return None


def _z_move_schema_issue(value: object, *, path: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, list):
        return _schema_error(path, "must be a list or null")
    for index, move in enumerate(value):
        if move is None:
            continue
        if (
            not isinstance(move, dict)
            or set(move) != {"move", "target"}
            or not isinstance(move["move"], str)
            or not move["move"].strip()
            or not isinstance(move["target"], str)
            or move["target"] not in _MOVE_TARGETS
        ):
            return _schema_error(
                f"{path}[{index}]",
                "must be null or a move/target dictionary",
            )
    return None


def _active_request_slot_schema_issue(value: object, *, path: str) -> str | None:
    if not isinstance(value, dict):
        return _schema_error(path, "must be a dictionary")
    allowed = {
        "moves",
        "maybeDisabled",
        "maybeLocked",
        "trapped",
        "maybeTrapped",
        "canMegaEvo",
        "canMegaEvoX",
        "canMegaEvoY",
        "canUltraBurst",
        "canZMove",
        "canDynamax",
        "maxMoves",
        "canTerastallize",
    }
    if "moves" not in value:
        return _schema_error(path, "missing required field: moves")
    extra = sorted(set(value) - allowed)
    if extra:
        return _schema_error(path, f"unexpected field(s): {', '.join(extra)}")
    if not isinstance(value["moves"], list) or not value["moves"]:
        return _schema_error(
            f"{path}.moves",
            "must be a non-empty producer move-choice list",
        )
    for index, move in enumerate(value["moves"]):
        issue = _move_request_data_schema_issue(
            move,
            path=f"{path}.moves[{index}]",
        )
        if issue:
            return issue
    for field in (
        "maybeDisabled",
        "maybeLocked",
        "trapped",
        "maybeTrapped",
        "canMegaEvo",
        "canMegaEvoX",
        "canMegaEvoY",
        "canUltraBurst",
        "canDynamax",
    ):
        if field in value and not isinstance(value[field], bool):
            return _schema_error(f"{path}.{field}", "must be boolean")
    if "canZMove" in value:
        issue = _z_move_schema_issue(value["canZMove"], path=f"{path}.canZMove")
        if issue:
            return issue
    if "maxMoves" in value:
        issue = _max_moves_schema_issue(value["maxMoves"], path=f"{path}.maxMoves")
        if issue:
            return issue
    if "canTerastallize" in value and not isinstance(value["canTerastallize"], str):
        return _schema_error(f"{path}.canTerastallize", "must be a string")
    return None


def _request_schema_issue(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        return _schema_error("$.request", "must be a dictionary or null")

    if value.get("teamPreview") is True:
        kind = "team"
        allowed = {"teamPreview", "maxChosenTeamSize", "side", "noCancel"}
    elif value.get("wait") is True:
        kind = "wait"
        allowed = {"wait", "side", "noCancel"}
    elif "forceSwitch" in value:
        kind = "switch"
        allowed = {"forceSwitch", "side", "noCancel", "update"}
    elif "active" in value:
        kind = "move"
        allowed = {"active", "side", "ally", "noCancel", "update"}
    else:
        return _schema_error("$.request", "does not identify a known request kind")

    extra = sorted(set(value) - allowed)
    if extra:
        return _schema_error(
            "$.request",
            f"unexpected field(s) for {kind} request: {', '.join(extra)}",
        )
    if "side" not in value:
        return _schema_error("$.request", "missing required field: side")
    issue = _request_side_schema_issue(value["side"], path="$.request.side")
    if issue:
        return issue
    if "noCancel" in value and not isinstance(value["noCancel"], bool):
        return _schema_error("$.request.noCancel", "must be boolean")
    if "update" in value and not isinstance(value["update"], bool):
        return _schema_error("$.request.update", "must be boolean")

    if kind == "team":
        if "maxChosenTeamSize" in value and not _non_bool_int(
            value["maxChosenTeamSize"],
            minimum=1,
        ):
            return _schema_error(
                "$.request.maxChosenTeamSize",
                "must be a positive integer",
            )
    elif kind == "switch":
        if (
            not isinstance(value["forceSwitch"], list)
            or len(value["forceSwitch"]) != 2
            or not all(isinstance(item, bool) for item in value["forceSwitch"])
        ):
            return _schema_error(
                "$.request.forceSwitch",
                "must be a list of booleans",
            )
    elif kind == "move":
        if not isinstance(value["active"], list) or len(value["active"]) != 2:
            return _schema_error(
                "$.request.active",
                "must contain exactly two doubles slots",
            )
        for index, slot in enumerate(value["active"]):
            if slot is None:
                continue
            issue = _active_request_slot_schema_issue(
                slot,
                path=f"$.request.active[{index}]",
            )
            if issue:
                return issue
        if "ally" in value:
            issue = _request_side_schema_issue(
                value["ally"],
                path="$.request.ally",
            )
            if issue:
                return issue
    return None


def public_reachability_observation_issue(
    view: object,
) -> str | None:
    """Return the first authority-schema failure for a public reachability view."""

    if not isinstance(view, dict):
        return _schema_error("$", "public observation must be a dictionary")
    issue = _exact_keys(
        view,
        path="$",
        keys={
            "turn",
            "phase",
            "opponent_last_actions",
            "public_execution_delta",
            "public_event_delta",
            "ended",
            "winner",
            "field",
            "request",
            "player",
            "opponent",
        },
    )
    if issue:
        return issue
    if not _non_bool_int(view["turn"], minimum=0):
        return _schema_error("$.turn", "must be a non-negative integer")
    if (
        not isinstance(view["phase"], str)
        or view["phase"] not in {"", "teampreview", "move", "switch", "ended"}
    ):
        return _schema_error("$.phase", "contains an unknown phase")
    if not isinstance(view["ended"], bool):
        return _schema_error("$.ended", "must be boolean")
    if view["winner"] is not None and not isinstance(view["winner"], str):
        return _schema_error("$.winner", "must be a string or null")

    opponent_actions = view["opponent_last_actions"]
    if not isinstance(opponent_actions, list):
        return _schema_error("$.opponent_last_actions", "must be a list")
    for index, action in enumerate(opponent_actions):
        issue = _opponent_action_schema_issue(
            action,
            path=f"$.opponent_last_actions[{index}]",
        )
        if issue:
            return issue
    if opponent_actions:
        action_turns = [action["turn"] for action in opponent_actions]
        action_slots = [action["slot"] for action in opponent_actions]
        if any(turn > view["turn"] for turn in action_turns):
            return _schema_error(
                "$.opponent_last_actions",
                "cannot contain actions from a future turn",
            )
        if len(set(action_turns)) != 1:
            return _schema_error(
                "$.opponent_last_actions",
                "must contain only the producer's latest observed action turn",
            )
        if len(set(action_slots)) != len(action_slots):
            return _schema_error(
                "$.opponent_last_actions",
                "must contain at most one retained action per doubles slot",
            )
        if action_slots != sorted(action_slots):
            return _schema_error(
                "$.opponent_last_actions",
                "must preserve producer slot ordering",
            )

    issue = _transition_ledger_schema_issue(view)
    if issue:
        return issue

    execution = view["public_execution_delta"]
    if (
        opponent_actions
        and execution["turn"] == opponent_actions[0]["turn"]
    ):
        public_selected = {
            (action["slot"], action["move"])
            for action in execution["actions"]
            if (
                action["side"] == "opponent"
                and action["outcome"] == "executed"
                and action["source"] == "selected"
            )
        }
        for index, action in enumerate(opponent_actions):
            if (action["slot"], action["move"]) not in public_selected:
                return _schema_error(
                    f"$.opponent_last_actions[{index}]",
                    "must agree with aligned public selected execution evidence",
                )

    field = view["field"]
    if not isinstance(field, dict):
        return _schema_error("$.field", "must be a dictionary")
    issue = _exact_keys(
        field,
        path="$.field",
        keys={"weather", "terrain", "pseudo_weather"},
    )
    if issue:
        return issue
    if field["weather"] is not None and (
        not isinstance(field["weather"], str)
        or field["weather"] not in WEATHER_IDS
    ):
        return _schema_error(
            "$.field.weather",
            "must be a pinned weather id or null",
        )
    if field["terrain"] is not None and (
        not isinstance(field["terrain"], str)
        or field["terrain"] not in TERRAIN_IDS
    ):
        return _schema_error(
            "$.field.terrain",
            "must be a pinned terrain id or null",
        )
    pseudo_weather = field["pseudo_weather"]
    if (
        not isinstance(pseudo_weather, list)
        or any(not isinstance(item, str) for item in pseudo_weather)
        or (
            isinstance(pseudo_weather, list)
            and all(isinstance(item, str) for item in pseudo_weather)
            and pseudo_weather != sorted(set(pseudo_weather))
        )
        or any(
            isinstance(item, str) and item not in PSEUDO_WEATHER_IDS
            for item in pseudo_weather
        )
    ):
        return _schema_error(
            "$.field.pseudo_weather",
            "must be sorted unique pinned pseudo-weather ids",
        )

    issue = _request_schema_issue(view["request"])
    if issue:
        return issue

    player = view["player"]
    if not isinstance(player, dict):
        return _schema_error("$.player", "must be a dictionary")
    issue = _exact_keys(
        player,
        path="$.player",
        keys={"name", "active", "active_details", "side_conditions", "team"},
    )
    if issue:
        return issue
    if not isinstance(player["name"], str):
        return _schema_error("$.player.name", "must be a string")
    if not isinstance(player["active"], list) or not all(
        item is None or isinstance(item, str)
        for item in player["active"]
    ):
        return _schema_error(
            "$.player.active",
            "must be a list of strings or nulls",
        )
    if not isinstance(player["active_details"], list):
        return _schema_error("$.player.active_details", "must be a list")
    if len(player["active"]) != len(player["active_details"]):
        return _schema_error(
            "$.player.active_details",
            "must align with player.active",
        )
    for index, pokemon in enumerate(player["active_details"]):
        if pokemon is None:
            continue
        issue = _own_pokemon_schema_issue(
            pokemon,
            path=f"$.player.active_details[{index}]",
        )
        if issue:
            return issue
    if (
        not isinstance(player["side_conditions"], list)
        or any(not isinstance(item, str) for item in player["side_conditions"])
        or (
            isinstance(player["side_conditions"], list)
            and all(isinstance(item, str) for item in player["side_conditions"])
            and player["side_conditions"]
            != sorted(set(player["side_conditions"]))
        )
        or any(
            isinstance(item, str) and item not in SIDE_CONDITION_IDS
            for item in player["side_conditions"]
        )
    ):
        return _schema_error(
            "$.player.side_conditions",
            "must be sorted pinned public side-condition ids",
        )
    if not isinstance(player["team"], list):
        return _schema_error("$.player.team", "must be a list")
    for index, pokemon in enumerate(player["team"]):
        issue = _own_pokemon_schema_issue(
            pokemon,
            path=f"$.player.team[{index}]",
        )
        if issue:
            return issue

    if len(player["active"]) != 2:
        return _schema_error(
            "$.player.active",
            "must contain exactly two doubles slots",
        )
    for index, (species, details) in enumerate(
        zip(player["active"], player["active_details"], strict=True)
    ):
        if species is None or details is None:
            if species is not None or details is not None:
                return _schema_error(
                    f"$.player.active_details[{index}]",
                    "must be null iff the active slot is null",
                )
            continue
        if index >= len(player["team"]):
            return _schema_error(
                f"$.player.active_details[{index}]",
                "has no ordered producer team entry",
            )
        if species != details["species"]:
            return _schema_error(
                f"$.player.active[{index}]",
                "must match active_details species",
            )
        if details != player["team"][index]:
            return _schema_error(
                f"$.player.active_details[{index}]",
                "must equal the same ordered player.team slot",
            )
        if not details["fainted"] and not details["active"]:
            return _schema_error(
                f"$.player.active_details[{index}].active",
                "living occupied slots must remain active",
            )

    occupied_slots = {
        index
        for index, details in enumerate(player["active_details"])
        if details is not None
    }
    for index, pokemon in enumerate(player["team"]):
        if pokemon["active"] and index not in occupied_slots:
            return _schema_error(
                f"$.player.team[{index}].active",
                "cannot mark an unoccupied ordered slot active",
            )

    request = view["request"]
    if isinstance(request, dict):
        request_side = request.get("side")
        request_roster = (
            request_side.get("pokemon")
            if isinstance(request_side, dict)
            else None
        )
        if isinstance(request_roster, list) and len(player["team"]) != len(
            request_roster
        ):
            return _schema_error(
                "$.player.team",
                "must match the producer request roster length",
            )

    opponent = view["opponent"]
    if not isinstance(opponent, dict):
        return _schema_error("$.opponent", "must be a dictionary")
    issue = _exact_keys(
        opponent,
        path="$.opponent",
        keys={
            "name",
            "preview_species",
            "side_conditions",
            "active",
            "revealed",
        },
    )
    if issue:
        return issue
    if not isinstance(opponent["name"], str):
        return _schema_error("$.opponent.name", "must be a string")
    if not _string_list(opponent["preview_species"]):
        return _schema_error(
            "$.opponent.preview_species",
            "must be a list of non-empty strings",
        )
    if (
        not isinstance(opponent["side_conditions"], list)
        or any(not isinstance(item, str) for item in opponent["side_conditions"])
        or (
            isinstance(opponent["side_conditions"], list)
            and all(isinstance(item, str) for item in opponent["side_conditions"])
            and opponent["side_conditions"]
            != sorted(set(opponent["side_conditions"]))
        )
        or any(
            isinstance(item, str) and item not in SIDE_CONDITION_IDS
            for item in opponent["side_conditions"]
        )
    ):
        return _schema_error(
            "$.opponent.side_conditions",
            "must be sorted pinned public side-condition ids",
        )
    if not isinstance(opponent["active"], list) or len(opponent["active"]) != 2:
        return _schema_error(
            "$.opponent.active",
            "must contain exactly two doubles slots",
        )
    for index, pokemon in enumerate(opponent["active"]):
        issue = _public_active_schema_issue(
            pokemon,
            path=f"$.opponent.active[{index}]",
        )
        if issue:
            return issue
    if not isinstance(opponent["revealed"], list):
        return _schema_error("$.opponent.revealed", "must be a list")
    for index, pokemon in enumerate(opponent["revealed"]):
        issue = _revealed_pokemon_schema_issue(
            pokemon,
            path=f"$.opponent.revealed[{index}]",
        )
        if issue:
            return issue

    preview_order: list[str] = []
    preview_species_by_key: dict[str, str] = {}
    for index, species in enumerate(opponent["preview_species"]):
        species_key = _to_id(species)
        if species_key not in SPECIES_IDS:
            return _schema_error(
                f"$.opponent.preview_species[{index}]",
                "must identify a pinned preview species",
            )
        if species_key not in preview_species_by_key:
            preview_order.append(species_key)
        # Match JavaScript Map.set(): replacement keeps the original key order
        # while the latest display value becomes the stored observation species.
        preview_species_by_key[species_key] = species

    if len(opponent["revealed"]) != len(preview_order):
        return _schema_error(
            "$.opponent.revealed",
            "must contain one knowledge record per normalized preview species",
        )

    revealed_by_key: dict[str, dict[str, Any]] = {}
    for index, species_key in enumerate(preview_order):
        pokemon = opponent["revealed"][index]
        expected_species = preview_species_by_key[species_key]
        if pokemon["species"] != expected_species:
            return _schema_error(
                f"$.opponent.revealed[{index}].species",
                "must preserve preview-derived producer key order and display value",
            )
        if not pokemon["seen"] and (
            pokemon["moves"]
            or pokemon["items"]
            or pokemon["abilities"]
            or pokemon["hp_percent"] is not None
            or pokemon["status"] is not None
            or pokemon["fainted"]
        ):
            return _schema_error(
                f"$.opponent.revealed[{index}]",
                "unseen producer knowledge must retain exact default values",
            )
        revealed_by_key[species_key] = pokemon

    for index, active in enumerate(opponent["active"]):
        if active is None:
            continue
        base_key = _to_id(active["base_species"])
        revealed = revealed_by_key.get(base_key)
        if revealed is None or not revealed["seen"]:
            return _schema_error(
                f"$.opponent.active[{index}].base_species",
                "must resolve to a seen preview-derived knowledge record",
            )
    return None


def _observation_unsupported_result(
    *,
    role: str,
    issue: str,
) -> ReachabilityResult:
    return ReachabilityResult.unsupported(
        reason=(
            f"{role} public observation does not satisfy "
            f"{PUBLIC_OBSERVATION_SCHEMA_VERSION}: {issue}"
        )
    )


def _reachability_hash(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _reachability_observation_signature(view: dict[str, Any]) -> str:
    """Return the exact public evidence projection certified by reachability."""

    normalized = json.loads(public_observation_signature(view))
    normalized["opponent_last_actions"] = view.get("opponent_last_actions")
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def _public_target_unsupported(view: dict[str, Any]) -> tuple[str, ...]:
    delta = view.get("public_event_delta")
    if not isinstance(delta, dict):
        return ()
    unsupported = delta.get("unsupported")
    if not isinstance(unsupported, list):
        return ()
    return tuple(
        value
        for value in unsupported
        if isinstance(value, str) and value.strip()
    )


def _probe_context_fingerprint(
    *,
    state: dict[str, Any],
    side: str,
    steps: tuple[PublicReachabilityStep, ...],
    previews: dict[str, list[str]] | None,
    max_branches: int,
) -> str:
    return "sha256:" + _reachability_hash(
        {
            "observation_schema": PUBLIC_OBSERVATION_SCHEMA_VERSION,
            "state": state,
            "side": side,
            "previews": previews,
            "max_branches": max_branches,
            "steps": [
                {
                    "p1_choice": step.p1_choice,
                    "p2_choice": step.p2_choice,
                    "expected_public_signature": public_observation_signature(
                        step.expected_public_view
                    ),
                    "rng_seeds": step.rng_seeds,
                }
                for step in steps
            ],
        }
    )


def _sampled_coverage(
    *,
    fingerprint: str,
    transitions_covered: int,
    outcomes_examined: int,
    sequential_context_complete: bool,
) -> ReachabilityCoverage | None:
    if transitions_covered <= 0:
        return None
    return ReachabilityCoverage(
        sequential_context_fingerprint=fingerprint,
        transitions_covered=transitions_covered,
        outcomes_examined=outcomes_examined,
        randomness_domains=("showdown-prng-seed",),
        randomness_exhaustive=False,
        sequential_context_complete=sequential_context_complete,
    )


def witness_public_observation_sequence(
    worker: ReachabilityWorker,
    *,
    state: dict[str, Any],
    side: str,
    steps: tuple[PublicReachabilityStep, ...],
    previews: dict[str, list[str]] | None = None,
    max_branches: int = 4096,
) -> ReachabilityResult:
    """Search bounded Showdown branches for one exact sequential public witness.

    This is positive-evidence machinery only. Every child transition is resolved
    by Showdown from the exact parent state that produced it, so outcomes from
    incompatible paths are never combined. Failure to find a witness remains
    UNRESOLVED because the configured RNG seeds are bounded samples rather than
    exhaustive mechanics enumeration.
    """

    if side not in {"p1", "p2"}:
        raise ValueError("reachability side must be p1 or p2")
    if not isinstance(state, dict) or not state:
        raise ValueError("reachability requires a serialized Showdown state")
    if not steps:
        raise ValueError("reachability requires at least one sequential step")
    if max_branches <= 0:
        raise ValueError("max_branches must be positive")

    for index, step in enumerate(steps):
        schema_issue = public_reachability_observation_issue(
            step.expected_public_view
        )
        if schema_issue:
            return _observation_unsupported_result(
                role=f"expected transition {index + 1}",
                issue=schema_issue,
            )
        unsupported = _public_target_unsupported(step.expected_public_view)
        if unsupported:
            return ReachabilityResult.unsupported(
                reason=(
                    f"transition {index + 1} contains unsupported public mechanics "
                    f"evidence: {', '.join(unsupported)}"
                )
            )

    fingerprint = _probe_context_fingerprint(
        state=state,
        side=side,
        steps=steps,
        previews=previews,
        max_branches=max_branches,
    )
    paths: list[tuple[dict[str, Any], tuple[str | None, ...]]] = [
        (state, ())
    ]
    outcomes_examined = 0
    transitions_covered = 0

    for step_index, step in enumerate(steps):
        wanted = _reachability_observation_signature(step.expected_public_view)
        next_paths: list[
            tuple[dict[str, Any], tuple[str | None, ...]]
        ] = []
        final_step = step_index == len(steps) - 1

        for parent_state, seed_path in paths:
            remaining = max_branches - outcomes_examined
            if remaining <= 0:
                return ReachabilityResult.unresolved(
                    reason=(
                        "bounded reachability branch budget exhausted before "
                        "the sequential query completed"
                    ),
                    coverage=_sampled_coverage(
                        fingerprint=fingerprint,
                        transitions_covered=transitions_covered,
                        outcomes_examined=outcomes_examined,
                        sequential_context_complete=False,
                    ),
                )

            selected_seeds = step.rng_seeds[:remaining]
            truncated = len(selected_seeds) < len(step.rng_seeds)
            branches: list[dict[str, Any]] = []
            for seed in selected_seeds:
                branch: dict[str, Any] = {
                    "p1_choice": step.p1_choice,
                    "p2_choice": step.p2_choice,
                    "include_state": True,
                    "view_side": side,
                    "rng_seed": seed,
                }
                if previews is not None:
                    branch["previews"] = previews
                branches.append(branch)

            try:
                resolved = worker.branch_many(
                    state=parent_state,
                    branches=branches,
                )
            except TimeoutError:
                return ReachabilityResult.unresolved(
                    reason=(
                        f"Showdown reachability probe timed out at transition "
                        f"{step_index + 1}"
                    ),
                    coverage=_sampled_coverage(
                        fingerprint=fingerprint,
                        transitions_covered=transitions_covered,
                        outcomes_examined=outcomes_examined,
                        sequential_context_complete=False,
                    ),
                )
            except ShowdownRequestError as error:
                if error.choice_rejected:
                    continue
                raise

            if len(resolved) != len(branches):
                raise RuntimeError(
                    "reachability worker returned an incomplete branch batch"
                )

            outcomes_examined += len(resolved)
            transitions_covered = step_index + 1

            for index, (seed, branch_result) in enumerate(
                zip(selected_seeds, resolved, strict=True)
            ):
                if branch_result.get("index") != index:
                    raise RuntimeError(
                        "reachability worker returned branches out of contract order"
                    )
                child_state = branch_result.get("state")
                public_view = branch_result.get("view")
                if not isinstance(child_state, dict):
                    raise RuntimeError(
                        "reachability worker omitted exact child state"
                    )
                schema_issue = public_reachability_observation_issue(public_view)
                if schema_issue:
                    return _observation_unsupported_result(
                        role="worker-returned",
                        issue=schema_issue,
                    )
                assert isinstance(public_view, dict)
                worker_unsupported = _public_target_unsupported(public_view)
                if worker_unsupported:
                    return ReachabilityResult.unsupported(
                        reason=(
                            "worker-returned transition contains unsupported "
                            "public mechanics evidence: "
                            f"{', '.join(worker_unsupported)}"
                        )
                    )
                if _reachability_observation_signature(public_view) != wanted:
                    continue

                child_seed_path = seed_path + (seed,)
                if final_step:
                    witness_id = "sha256:" + _reachability_hash(
                        {
                            "context": fingerprint,
                            "rng_path": child_seed_path,
                        }
                    )
                    return ReachabilityResult.witnessed(
                        coverage=ReachabilityCoverage(
                            sequential_context_fingerprint=fingerprint,
                            transitions_covered=len(steps),
                            outcomes_examined=outcomes_examined,
                            randomness_domains=("showdown-prng-seed",),
                            randomness_exhaustive=False,
                            sequential_context_complete=True,
                        ),
                        witness_ids=(witness_id,),
                    )
                next_paths.append((child_state, child_seed_path))

            if truncated:
                return ReachabilityResult.unresolved(
                    reason=(
                        "bounded reachability branch budget exhausted before "
                        "all configured RNG samples were evaluated"
                    ),
                    coverage=_sampled_coverage(
                        fingerprint=fingerprint,
                        transitions_covered=transitions_covered,
                        outcomes_examined=outcomes_examined,
                        sequential_context_complete=False,
                    ),
                )

        if not next_paths:
            return ReachabilityResult.unresolved(
                reason=(
                    f"configured bounded RNG samples produced no mechanics "
                    f"witness at transition {step_index + 1}"
                ),
                coverage=_sampled_coverage(
                    fingerprint=fingerprint,
                    transitions_covered=transitions_covered,
                    outcomes_examined=outcomes_examined,
                    sequential_context_complete=final_step,
                ),
            )
        paths = next_paths

    raise AssertionError("reachability sequence ended without a typed result")



def evaluate_deterministic_public_transition(
    worker: ReachabilityWorker,
    *,
    state: dict[str, Any],
    side: str,
    step: PublicReachabilityStep,
    previews: dict[str, list[str]] | None = None,
) -> ReachabilityResult:
    """Evaluate one public transition with zero-draw negative authority.

    A matching Showdown branch is still a positive witness regardless of how much
    RNG it consumes. A mismatch becomes EXHAUSTIVELY_DISPROVED only when the
    pinned Showdown branch reports zero low-level PRNG draws for the complete
    transition. Any transition that consumes one or more draws remains UNRESOLVED:
    one sampled seed is not exhaustive randomness coverage.
    """

    if side not in {"p1", "p2"}:
        raise ValueError("reachability side must be p1 or p2")
    if not isinstance(state, dict) or not state:
        raise ValueError("reachability requires a serialized Showdown state")
    if len(step.rng_seeds) != 1:
        raise ValueError(
            "deterministic reachability requires exactly one configured RNG seed"
        )

    schema_issue = public_reachability_observation_issue(
        step.expected_public_view
    )
    if schema_issue:
        return _observation_unsupported_result(
            role="expected",
            issue=schema_issue,
        )

    unsupported = _public_target_unsupported(step.expected_public_view)
    if unsupported:
        return ReachabilityResult.unsupported(
            reason=(
                "transition contains unsupported public mechanics evidence: "
                f"{', '.join(unsupported)}"
            )
        )

    fingerprint = _probe_context_fingerprint(
        state=state,
        side=side,
        steps=(step,),
        previews=previews,
        max_branches=1,
    )
    seed = step.rng_seeds[0]
    branch: dict[str, Any] = {
        "p1_choice": step.p1_choice,
        "p2_choice": step.p2_choice,
        "include_state": True,
        "view_side": side,
        "rng_seed": seed,
        "include_rng_draw_count": True,
    }
    if previews is not None:
        branch["previews"] = previews

    try:
        resolved = worker.branch_many(
            state=state,
            branches=[branch],
        )
    except TimeoutError:
        return ReachabilityResult.unresolved(
            reason="Showdown deterministic reachability probe timed out"
        )
    except ShowdownRequestError as error:
        if error.choice_rejected:
            return ReachabilityResult.unresolved(
                reason="exact transition command was rejected by Showdown"
            )
        raise

    if len(resolved) != 1 or resolved[0].get("index") != 0:
        raise RuntimeError(
            "deterministic reachability worker returned an invalid branch batch"
        )
    branch_result = resolved[0]
    public_view = branch_result.get("view")
    child_state = branch_result.get("state")
    draw_count = branch_result.get("rng_draw_count")
    if not isinstance(child_state, dict):
        raise RuntimeError(
            "deterministic reachability worker omitted exact child state"
        )
    schema_issue = public_reachability_observation_issue(public_view)
    if schema_issue:
        return _observation_unsupported_result(
            role="worker-returned",
            issue=schema_issue,
        )
    assert isinstance(public_view, dict)
    worker_unsupported = _public_target_unsupported(public_view)
    if worker_unsupported:
        return ReachabilityResult.unsupported(
            reason=(
                "worker-returned transition contains unsupported public "
                f"mechanics evidence: {', '.join(worker_unsupported)}"
            )
        )
    if not isinstance(draw_count, int) or isinstance(draw_count, bool) or draw_count < 0:
        raise RuntimeError(
            "deterministic reachability worker omitted a valid PRNG draw count"
        )

    wanted = _reachability_observation_signature(step.expected_public_view)
    observed = _reachability_observation_signature(public_view)
    randomness_domains = () if draw_count == 0 else ("showdown-prng-draw",)
    coverage = ReachabilityCoverage(
        sequential_context_fingerprint=fingerprint,
        transitions_covered=1,
        outcomes_examined=1,
        randomness_domains=randomness_domains,
        randomness_exhaustive=draw_count == 0,
        sequential_context_complete=True,
    )

    if observed == wanted:
        witness_id = "sha256:" + _reachability_hash(
            {
                "context": fingerprint,
                "rng_seed": seed,
                "rng_draw_count": draw_count,
                "observed_public_signature": observed,
            }
        )
        return ReachabilityResult.witnessed(
            coverage=coverage,
            witness_ids=(witness_id,),
        )

    if draw_count == 0:
        return ReachabilityResult.exhaustively_disproved(
            coverage=coverage,
        )

    return ReachabilityResult.unresolved(
        reason=(
            "Showdown branch mismatched after consuming "
            f"{draw_count} PRNG draw(s); one sampled seed is not exhaustive"
        ),
        coverage=coverage,
    )
