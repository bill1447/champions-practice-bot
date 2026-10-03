"""Authority-preserving adapter from replay action identities to legal joint menus.

Public replay trajectories do not contain a complete player-side Showdown request.
This module therefore never manufactures a legal menu. A caller must supply the exact
menu produced by pinned Showdown plus the choosing side's party-slot species mapping.
The adapter either identifies one exact menu entry or abstains.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Iterable


POLICY_EXAMPLE_SCHEMA = "showdown-replay-policy-example-v1"
MENU_MATCH_SCHEMA = "showdown-replay-menu-match-v1"
LEGAL_MENU_AUTHORITY = "pinned-showdown-legal-choices"

_TRANSFORMATION_TOKENS = {
    "mega",
    "megax",
    "megay",
    "ultra",
    "zmove",
    "dynamax",
    "terastallize",
}
_GENERIC_MEGA_TOKENS = {"mega", "megax", "megay"}
_TARGET_RE = re.compile(r"^[+-]?\d+$")


class ReplayMenuAdapterError(ValueError):
    """Replay/menu data are malformed rather than merely ambiguous."""


@dataclass(frozen=True)
class ParsedCommand:
    kind: str
    raw: str
    move: str | None = None
    target: int | None = None
    transformations: tuple[str, ...] = ()
    switch_slot: int | None = None


@dataclass(frozen=True)
class MenuMatch:
    status: str
    reason: str | None
    matched_choice: str | None
    matched_index: int | None
    candidates: tuple[str, ...]
    candidate_indices: tuple[int, ...]
    ambiguity_dimensions: tuple[str, ...] = ()

    @property
    def matched(self) -> bool:
        return self.status == "matched"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": MENU_MATCH_SCHEMA,
            "status": self.status,
            "reason": self.reason,
            "matched_choice": self.matched_choice,
            "matched_index": self.matched_index,
            "candidates": list(self.candidates),
            "candidate_indices": list(self.candidate_indices),
            "ambiguity_dimensions": list(self.ambiguity_dimensions),
        }


def _to_id(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _parse_command(command: str) -> ParsedCommand:
    raw = command.strip()
    if not raw:
        raise ReplayMenuAdapterError("legal choice contains an empty slot command")
    tokens = raw.split()
    kind = tokens[0]

    if kind == "pass":
        if len(tokens) != 1:
            raise ReplayMenuAdapterError(f"invalid pass command: {raw!r}")
        return ParsedCommand(kind="pass", raw=raw)

    if kind == "switch":
        if len(tokens) != 2 or not tokens[1].isdigit():
            raise ReplayMenuAdapterError(f"invalid switch command: {raw!r}")
        slot = int(tokens[1])
        if slot < 1:
            raise ReplayMenuAdapterError(f"invalid switch slot: {raw!r}")
        return ParsedCommand(kind="switch", raw=raw, switch_slot=slot)

    if kind == "move":
        if len(tokens) < 2:
            raise ReplayMenuAdapterError(f"invalid move command: {raw!r}")
        move = _to_id(tokens[1])
        if not move:
            raise ReplayMenuAdapterError(f"invalid move id: {raw!r}")
        targets = [token for token in tokens[2:] if _TARGET_RE.fullmatch(token)]
        if len(targets) > 1:
            raise ReplayMenuAdapterError(f"move command has multiple targets: {raw!r}")
        target = int(targets[0]) if targets else None
        transformations = tuple(
            token for token in tokens[2:] if token in _TRANSFORMATION_TOKENS
        )
        known_extras = set(targets).union(transformations)
        unknown = [
            token
            for token in tokens[2:]
            if token not in known_extras
        ]
        if unknown:
            raise ReplayMenuAdapterError(
                f"unsupported legal move command tokens {unknown!r}: {raw!r}"
            )
        return ParsedCommand(
            kind="move",
            raw=raw,
            move=move,
            target=target,
            transformations=transformations,
        )

    raise ReplayMenuAdapterError(f"unsupported legal slot command: {raw!r}")


def parse_legal_choice(choice: str) -> tuple[ParsedCommand, ...]:
    if not isinstance(choice, str) or not choice.strip():
        raise ReplayMenuAdapterError("legal choice must be a non-empty string")
    if choice == "wait":
        return (ParsedCommand(kind="wait", raw="wait"),)
    if choice.startswith("team "):
        return (ParsedCommand(kind="team", raw=choice),)
    return tuple(_parse_command(command) for command in choice.split(","))


def _normalized_label_transformations(action: dict[str, Any]) -> tuple[str, ...]:
    raw = action.get("gimmicks", [])
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(value, str) for value in raw):
        raise ReplayMenuAdapterError("replay move gimmicks must be a list of strings")
    normalized: list[str] = []
    for value in raw:
        token = _to_id(value)
        if token == "burst":
            token = "ultra"
        elif token == "zpower":
            token = "zmove"
        if token not in _TRANSFORMATION_TOKENS:
            raise ReplayMenuAdapterError(f"unsupported replay gimmick {value!r}")
        normalized.append(token)
    return tuple(sorted(normalized))


def _transformations_match(
    label_transformations: tuple[str, ...],
    command_transformations: tuple[str, ...],
) -> bool:
    command = tuple(sorted(command_transformations))
    if label_transformations == ("mega",):
        return len(command) == 1 and command[0] in _GENERIC_MEGA_TOKENS
    return label_transformations == command


def _validate_joint_label(label: dict[str, Any], *, side: str) -> dict[int, dict[str, Any]]:
    if not isinstance(label, dict):
        raise ReplayMenuAdapterError("joint action label must be an object")
    if label.get("side") != side:
        raise ReplayMenuAdapterError(
            f"joint action side mismatch: expected {side!r}, got {label.get('side')!r}"
        )
    actions = label.get("actions")
    if not isinstance(actions, list):
        raise ReplayMenuAdapterError("joint action label has no action list")

    by_slot: dict[int, dict[str, Any]] = {}
    for action in actions:
        if not isinstance(action, dict):
            raise ReplayMenuAdapterError("joint action contains a non-object action")
        slot = action.get("slot")
        if isinstance(slot, bool) or not isinstance(slot, int) or slot < 1:
            raise ReplayMenuAdapterError("joint action contains an invalid slot")
        if slot in by_slot:
            raise ReplayMenuAdapterError("joint action contains duplicate slots")
        kind = action.get("kind")
        if kind not in {"move", "switch", "pass"}:
            raise ReplayMenuAdapterError(f"unsupported replay action kind {kind!r}")
        by_slot[slot] = action
    return by_slot


def _switch_species(
    command: ParsedCommand,
    party_species: tuple[str, ...],
) -> str | None:
    if command.switch_slot is None:
        return None
    index = command.switch_slot - 1
    if index < 0 or index >= len(party_species):
        raise ReplayMenuAdapterError(
            f"legal switch slot {command.switch_slot} exceeds party mapping"
        )
    return party_species[index]


def _action_matches(
    action: dict[str, Any],
    command: ParsedCommand,
    *,
    party_species: tuple[str, ...],
) -> bool:
    kind = action["kind"]
    if kind != command.kind:
        return False

    if kind == "pass":
        return True

    if kind == "switch":
        species = action.get("switch_species")
        if not isinstance(species, str) or not species:
            raise ReplayMenuAdapterError("replay switch action has no species identity")
        command_species = _switch_species(command, party_species)
        return _to_id(species) == _to_id(command_species)

    move = action.get("move")
    if not isinstance(move, str) or not _to_id(move):
        raise ReplayMenuAdapterError("replay move action has no move identity")
    if _to_id(move) != command.move:
        return False
    label_transformations = _normalized_label_transformations(action)
    return _transformations_match(label_transformations, command.transformations)


def _choice_matches_label(
    label_by_slot: dict[int, dict[str, Any]],
    commands: tuple[ParsedCommand, ...],
    *,
    party_species: tuple[str, ...],
) -> bool:
    if len(commands) != len(label_by_slot):
        return False
    if set(label_by_slot) != set(range(1, len(commands) + 1)):
        return False
    return all(
        _action_matches(
            label_by_slot[slot],
            commands[slot - 1],
            party_species=party_species,
        )
        for slot in range(1, len(commands) + 1)
    )


def _ambiguity_dimensions(
    parsed_candidates: Iterable[tuple[ParsedCommand, ...]],
) -> tuple[str, ...]:
    candidates = tuple(parsed_candidates)
    if len(candidates) < 2:
        return ()
    dimensions: set[str] = set()
    width = len(candidates[0])

    for slot in range(width):
        commands = [candidate[slot] for candidate in candidates]
        if len({command.target for command in commands}) > 1:
            dimensions.add("selected-target")
        if len({command.switch_slot for command in commands}) > 1:
            dimensions.add("switch-slot")
        if len({command.transformations for command in commands}) > 1:
            dimensions.add("gimmick-variant")
        signatures = {
            (
                command.kind,
                command.move,
                command.target,
                command.transformations,
                command.switch_slot,
            )
            for command in commands
        }
        if len(signatures) == 1 and len({command.raw for command in commands}) > 1:
            dimensions.add("command-syntax")

    return tuple(sorted(dimensions))


def match_replay_joint_to_legal_menu(
    label: dict[str, Any],
    legal_choices: Iterable[str],
    *,
    side: str,
    party_species: Iterable[str],
) -> MenuMatch:
    """Map one replay joint-action identity to exactly one Showdown legal choice.

    Resolved replay targets are deliberately not used to choose among target variants.
    If the selected target is unavailable and more than one legal target matches the
    observed move identity, this function abstains.
    """
    if side not in {"p1", "p2"}:
        raise ReplayMenuAdapterError("side must be p1 or p2")
    party = tuple(party_species)
    if not party or not all(isinstance(species, str) and species for species in party):
        raise ReplayMenuAdapterError("party_species must contain non-empty strings")

    choices = tuple(legal_choices)
    if not choices:
        raise ReplayMenuAdapterError("legal menu cannot be empty")
    if not all(isinstance(choice, str) and choice for choice in choices):
        raise ReplayMenuAdapterError("legal menu contains a non-string or empty choice")
    if len(set(choices)) != len(choices):
        raise ReplayMenuAdapterError("legal menu contains duplicate choices")

    if label.get("identity_complete") is not True:
        return MenuMatch(
            status="abstain",
            reason="incomplete-replay-label",
            matched_choice=None,
            matched_index=None,
            candidates=(),
            candidate_indices=(),
        )

    label_by_slot = _validate_joint_label(label, side=side)
    parsed = tuple(parse_legal_choice(choice) for choice in choices)
    matches: list[tuple[int, str, tuple[ParsedCommand, ...]]] = []
    for index, (choice, commands) in enumerate(zip(choices, parsed, strict=True)):
        if any(command.kind in {"wait", "team"} for command in commands):
            continue
        if _choice_matches_label(label_by_slot, commands, party_species=party):
            matches.append((index, choice, commands))

    if not matches:
        return MenuMatch(
            status="abstain",
            reason="observed-action-not-in-legal-menu",
            matched_choice=None,
            matched_index=None,
            candidates=(),
            candidate_indices=(),
        )
    if len(matches) == 1:
        index, choice, _ = matches[0]
        return MenuMatch(
            status="matched",
            reason=None,
            matched_choice=choice,
            matched_index=index,
            candidates=(choice,),
            candidate_indices=(index,),
        )

    dimensions = _ambiguity_dimensions(match[2] for match in matches)
    if dimensions == ("selected-target",):
        reason = "selected-target-ambiguous"
    elif dimensions == ("switch-slot",):
        reason = "switch-slot-ambiguous"
    elif dimensions == ("gimmick-variant",):
        reason = "gimmick-variant-ambiguous"
    else:
        reason = "multiple-legal-commands-match-observation"

    return MenuMatch(
        status="abstain",
        reason=reason,
        matched_choice=None,
        matched_index=None,
        candidates=tuple(match[1] for match in matches),
        candidate_indices=tuple(match[0] for match in matches),
        ambiguity_dimensions=dimensions,
    )


def adapt_replay_decision_to_policy_example(
    *,
    replay_id: str,
    game_group: str,
    decision: dict[str, Any],
    side: str,
    legal_choices: Iterable[str],
    party_species: Iterable[str],
    menu_authority: str,
    showdown_revision: str,
) -> dict[str, Any]:
    """Create an auditable policy row or an auditable abstention.

    The menu must already have been enumerated by pinned Showdown. This function
    verifies the declared authority tag but does not reconstruct missing requests.
    """
    if menu_authority != LEGAL_MENU_AUTHORITY:
        raise ReplayMenuAdapterError(
            "policy examples require pinned-Showdown legal-menu authority"
        )
    if not replay_id or not game_group:
        raise ReplayMenuAdapterError("replay_id and game_group are required")
    if not showdown_revision:
        raise ReplayMenuAdapterError("showdown_revision is required")
    if side not in {"p1", "p2"}:
        raise ReplayMenuAdapterError("side must be p1 or p2")
    if not isinstance(decision, dict):
        raise ReplayMenuAdapterError("decision must be an object")

    public_state = decision.get("public_state")
    joint_actions = decision.get("joint_actions")
    if not isinstance(public_state, dict):
        raise ReplayMenuAdapterError("decision has no public_state")
    if not isinstance(joint_actions, dict) or not isinstance(joint_actions.get(side), dict):
        raise ReplayMenuAdapterError("decision has no joint action for requested side")
    turn = decision.get("turn")
    if isinstance(turn, bool) or not isinstance(turn, int) or turn < 1:
        raise ReplayMenuAdapterError("decision has an invalid turn")

    choices = tuple(legal_choices)
    party = tuple(party_species)
    label = joint_actions[side]
    match = match_replay_joint_to_legal_menu(
        label,
        choices,
        side=side,
        party_species=party,
    )

    example = {
        "schema": POLICY_EXAMPLE_SCHEMA,
        "replay_id": replay_id,
        "game_group": game_group,
        "turn": turn,
        "side": side,
        "public_state": copy.deepcopy(public_state),
        "observed_action_identity": copy.deepcopy(label),
        "legal_menu": list(choices),
        "party_species": list(party),
        "menu_provenance": {
            "authority": menu_authority,
            "showdown_revision": showdown_revision,
        },
        "match": match.as_dict(),
        "trainable": match.matched,
        "label_choice": match.matched_choice,
        "label_index": match.matched_index,
    }
    if not match.matched:
        example["abstention"] = {
            "reason": match.reason,
            "candidate_count": len(match.candidates),
            "candidate_indices": list(match.candidate_indices),
            "ambiguity_dimensions": list(match.ambiguity_dimensions),
        }
    return example
