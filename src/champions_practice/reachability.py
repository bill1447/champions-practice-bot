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
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from champions_practice.observation_beliefs import public_observation_signature
from champions_practice.search_worker import ShowdownRequestError


PUBLIC_OBSERVATION_SCHEMA_VERSION = "showdown-player-view-v1"


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
    randomness_domains: tuple[str, ...] = ()
    randomness_exhaustive: bool = False
    sequential_context_complete: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.sequential_context_fingerprint, str)
            or not self.sequential_context_fingerprint.strip()
        ):
            raise ValueError("reachability coverage requires a context fingerprint")
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
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
    )


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


def _boosts_schema_issue(value: object, *, path: str) -> str | None:
    if not isinstance(value, dict):
        return _schema_error(path, "must be a dictionary")
    for stat, amount in value.items():
        if not isinstance(stat, str) or not stat.strip():
            return _schema_error(path, "boost keys must be non-empty strings")
        if not _non_bool_int(amount):
            return _schema_error(f"{path}.{stat}", "boost must be an integer")
    return None


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
    for field in ("hp", "maxhp", "speed", "damaging_move_count"):
        if not _non_bool_int(value[field], minimum=0):
            return _schema_error(f"{path}.{field}", "must be a non-negative integer")
    if not _number(value["hp_percent"]):
        return _schema_error(f"{path}.hp_percent", "must be numeric")
    if not isinstance(value["fainted"], bool):
        return _schema_error(f"{path}.fainted", "must be boolean")
    if value["status"] is not None and not isinstance(value["status"], str):
        return _schema_error(f"{path}.status", "must be a string or null")
    issue = _boosts_schema_issue(value["boosts"], path=f"{path}.boosts")
    if issue:
        return issue
    for field in ("item", "ability"):
        if value[field] is not None and not isinstance(value[field], str):
            return _schema_error(f"{path}.{field}", "must be a string or null")
    if not _string_list(value["moves"]):
        return _schema_error(f"{path}.moves", "must be a list of non-empty strings")
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
    if not _number(value["hp_percent"]):
        return _schema_error(f"{path}.hp_percent", "must be numeric")
    if not isinstance(value["fainted"], bool):
        return _schema_error(f"{path}.fainted", "must be boolean")
    if value["status"] is not None and not isinstance(value["status"], str):
        return _schema_error(f"{path}.status", "must be a string or null")
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
    for field in ("moves", "items", "abilities"):
        if not _string_list(value[field]):
            return _schema_error(f"{path}.{field}", "must be a list of non-empty strings")
    if value["hp_percent"] is not None and not _number(value["hp_percent"]):
        return _schema_error(f"{path}.hp_percent", "must be numeric or null")
    if value["status"] is not None and not isinstance(value["status"], str):
        return _schema_error(f"{path}.status", "must be a string or null")
    for field in ("fainted", "seen"):
        if not isinstance(value[field], bool):
            return _schema_error(f"{path}.{field}", "must be boolean")
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
    if not _non_bool_int(value["slot"], minimum=1):
        return _schema_error(f"{path}.slot", "must be a positive integer")
    if not isinstance(value["move"], str) or not value["move"].strip():
        return _schema_error(f"{path}.move", "must be a non-empty string")
    if value["target"] is not None and not _non_bool_int(value["target"]):
        return _schema_error(f"{path}.target", "must be an integer or null")
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
    if not _non_bool_int(value["slot"], minimum=1):
        return _schema_error(f"{path}.slot", "must be a positive integer")
    if not _string_list(value["effects"]):
        return _schema_error(f"{path}.effects", "must be a list of non-empty strings")
    if outcome == "executed":
        if not isinstance(value["move"], str) or not value["move"].strip():
            return _schema_error(f"{path}.move", "must be a non-empty string")
        if value["source"] not in {"selected", "called"}:
            return _schema_error(f"{path}.source", "must be selected or called")
        if not _string_list(value["provenance"]):
            return _schema_error(
                f"{path}.provenance",
                "must be a list of non-empty strings",
            )
    else:
        if not isinstance(value["reason"], str) or not value["reason"].strip():
            return _schema_error(f"{path}.reason", "must be a non-empty string")
        if (
            value["attempted_move"] is not None
            and (
                not isinstance(value["attempted_move"], str)
                or not value["attempted_move"].strip()
            )
        ):
            return _schema_error(
                f"{path}.attempted_move",
                "must be a non-empty string or null",
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
        if not isinstance(event, list) or not event:
            return _schema_error(
                f"$.public_event_delta.events[{index}]",
                "must be a non-empty list",
            )
        if not all(isinstance(part, str) and part.strip() for part in event):
            return _schema_error(
                f"$.public_event_delta.events[{index}]",
                "entries must be non-empty strings",
            )
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


def _request_schema_issue(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        return _schema_error("$.request", "must be a dictionary or null")
    side = value.get("side")
    if not isinstance(side, dict) or not isinstance(side.get("pokemon"), list):
        return _schema_error(
            "$.request.side.pokemon",
            "must be present as a list",
        )
    request_kinds = 0
    if value.get("teamPreview") is True:
        request_kinds += 1
    if value.get("wait") is True:
        request_kinds += 1
    if "forceSwitch" in value:
        if not isinstance(value["forceSwitch"], list) or not all(
            isinstance(item, bool) for item in value["forceSwitch"]
        ):
            return _schema_error(
                "$.request.forceSwitch",
                "must be a list of booleans",
            )
        request_kinds += 1
    if "active" in value:
        if not isinstance(value["active"], list):
            return _schema_error("$.request.active", "must be a list")
        request_kinds += 1
    if request_kinds != 1:
        return _schema_error(
            "$.request",
            "must identify exactly one request kind",
        )
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
    if view["phase"] not in {"", "teampreview", "move", "switch", "ended"}:
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

    issue = _transition_ledger_schema_issue(view)
    if issue:
        return issue

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
    for name in ("weather", "terrain"):
        if field[name] is not None and not isinstance(field[name], str):
            return _schema_error(f"$.field.{name}", "must be a string or null")
    if not _string_list(field["pseudo_weather"]):
        return _schema_error(
            "$.field.pseudo_weather",
            "must be a list of non-empty strings",
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
    if not _string_list(player["side_conditions"]):
        return _schema_error(
            "$.player.side_conditions",
            "must be a list of non-empty strings",
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
    for name in ("preview_species", "side_conditions"):
        if not _string_list(opponent[name]):
            return _schema_error(
                f"$.opponent.{name}",
                "must be a list of non-empty strings",
            )
    if not isinstance(opponent["active"], list):
        return _schema_error("$.opponent.active", "must be a list")
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
        wanted = public_observation_signature(step.expected_public_view)
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
                if public_observation_signature(public_view) != wanted:
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

    wanted = public_observation_signature(step.expected_public_view)
    observed = public_observation_signature(public_view)
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
