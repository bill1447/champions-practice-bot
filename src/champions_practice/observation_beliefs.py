"""Observation-conditioned exact belief particles."""

from __future__ import annotations

import copy
from contextvars import ContextVar
import json
import math
import random
from collections import Counter
from dataclasses import dataclass
from itertools import product
from typing import Any, Iterable

from .search_worker import FORCED_WAIT_CHOICE, ShowdownSearchWorker
from .showdown_public_catalog import MEGA_ITEM_IDS, TRANSFORM_ITEM_SPECIES_IDS


_REJECTION_AUDIT: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    'conditioning_rejection_audit', default=None
)

def _audit_rejection(**values: Any) -> None:
    sink = _REJECTION_AUDIT.get()
    if sink is not None and len(sink) < 10000:
        sink.append(values)



def _audit_active_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Small pre-branch native snapshot; audit only, never conditioning input."""
    sides = state.get("sides", ())
    if not isinstance(sides, list):
        return []
    active: list[dict[str, Any]] = []
    for side_index, side in enumerate(sides[:2]):
        if not isinstance(side, dict):
            continue
        for pokemon_index, pokemon in enumerate(side.get("pokemon", ())):
            if not isinstance(pokemon, dict) or not pokemon.get("isActive"):
                continue
            active.append({
                "side": f"p{side_index + 1}",
                "pokemon_index": pokemon_index,
                "species": str(pokemon.get("species", "")),
                "hp": pokemon.get("hp"),
                "maxhp": pokemon.get("maxhp"),
                "status": pokemon.get("status"),
                "item": pokemon.get("item"),
                "boosts": dict(pokemon.get("boosts") or {}),
            })
    return active


def _audit_public_value(value: Any) -> Any:
    """Bound diagnostic field sizes; preserve exact numeric HP and boosts."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:200]
    if isinstance(value, (list, dict)):
        rendered = json.dumps(value, sort_keys=True, default=str)
        return rendered[:200]
    return str(value)[:200]


@dataclass(frozen=True)
class BeliefParticle:
    state: dict[str, Any]
    weight: float
    world_id: str = ""
    history_id: str = ""
    p1_member_lineage: tuple[int, ...] = ()
    p2_member_lineage: tuple[int, ...] = ()


@dataclass(frozen=True)
class StructuralMismatchExample:
    world_id: str
    path: str
    actual: Any
    simulated: Any
    opponent_choice: str
    rng_seed: str | None


@dataclass(frozen=True)
class ParticleUpdate:
    particles: tuple[BeliefParticle, ...]
    generated: int
    matched: int
    deduplicated: int
    stochastic_only_mismatches: int = 0
    structural_mismatches: int = 0
    matched_world_ids: tuple[str, ...] = ()
    sampled_unresolved_world_ids: tuple[str, ...] = ()
    exhaustively_excluded_world_ids: tuple[str, ...] = ()
    unsupported_public_evidence: tuple[str, ...] = ()
    structural_mismatch_paths: tuple[tuple[str, int], ...] = ()
    structural_mismatch_worlds: tuple[tuple[str, int], ...] = ()
    structural_mismatch_examples: tuple[StructuralMismatchExample, ...] = ()
    finite_reachability_witnesses: int = 0
    finite_reachability_disproofs: int = 0
    finite_reachability_unresolved: int = 0
    finite_reachability_leaves: int = 0


def _champions_public_hp_bucket(value: object) -> object:
    """Project an opponent HP percentage through pinned Champions visibility.

    Pinned Champions Showdown exposes non-fainted opposing HP as
    floor(100 * hp / maxhp), with a floor of 1 for any positive HP. Public
    views should already contain that integer bucket. This normalization also
    makes a precise fallback projection interval-aware without relaxing exact
    own-side HP.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    numeric = float(value)
    if not math.isfinite(numeric):
        return value
    if numeric <= 0:
        return 0
    return max(1, math.floor(numeric))


def _normalize_opponent_public_hp(view: dict[str, Any]) -> None:
    opponent = view.get("opponent")
    if not isinstance(opponent, dict):
        return
    for key in ("active", "revealed"):
        entries = opponent.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or "hp_percent" not in entry:
                continue
            entry["hp_percent"] = _champions_public_hp_bucket(
                entry["hp_percent"]
            )


def public_observation_signature(view: dict[str, Any]) -> str:
    """Return a stable signature for mechanically relevant public information.

    Reconstructed Showdown states may use different display names from the live
    session. Names do not affect the battle state, so normalize a winner to its
    player/opponent role and remove cosmetic names before comparing observations.

    Opponent HP is compared at the pinned Champions public bucket rather than a
    precise hidden percentage. Own-side HP, the authoritative request, and
    quantitative public event conditions remain exact.
    """
    normalized = copy.deepcopy(view)
    # The selected opponent command history is evidence used to prune replay
    # candidates, not part of the resulting-state projection. In contrast, both
    # public_execution_delta and public_event_delta are authoritative public
    # transition evidence. The former distinguishes selected commands from what
    # actually executed/failed/was prevented; the latter preserves ordered,
    # quantitative mechanics transitions even when later effects erase them from
    # the reduced final board.
    normalized.pop("opponent_last_actions", None)
    _normalize_opponent_public_hp(normalized)
    player = normalized.get("player")
    opponent = normalized.get("opponent")
    player_name = player.get("name") if isinstance(player, dict) else None
    opponent_name = opponent.get("name") if isinstance(opponent, dict) else None

    winner = normalized.get("winner")
    if isinstance(winner, str):
        if winner == player_name:
            normalized["winner"] = "player"
        elif winner == opponent_name:
            normalized["winner"] = "opponent"

    if isinstance(player, dict):
        player.pop("name", None)
    if isinstance(opponent, dict):
        opponent.pop("name", None)

    request = normalized.get("request")
    if isinstance(request, dict):
        request_side = request.get("side")
        if isinstance(request_side, dict):
            request_side.pop("name", None)

    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def _public_diff_paths(
    left: object,
    right: object,
    path: str = "$",
    *,
    limit: int = 64,
) -> tuple[str, ...]:
    """Return public-view leaf paths that differ, bounded for diagnostics."""
    if type(left) is not type(right):
        return (path,)
    if isinstance(left, dict):
        paths: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}"
            if key not in left or key not in right:
                paths.append(child)
            else:
                paths.extend(
                    _public_diff_paths(
                        left[key],
                        right[key],
                        child,
                        limit=max(0, limit - len(paths)),
                    )
                )
            if len(paths) >= limit:
                break
        return tuple(paths[:limit])
    if isinstance(left, list):
        if len(left) != len(right):
            return (f"{path}.length",)
        paths: list[str] = []
        for index, (left_item, right_item) in enumerate(
            zip(left, right, strict=True)
        ):
            paths.extend(
                _public_diff_paths(
                    left_item,
                    right_item,
                    f"{path}[{index}]",
                    limit=max(0, limit - len(paths)),
                )
            )
            if len(paths) >= limit:
                break
        return tuple(paths[:limit])
    return () if left == right else (path,)


def _public_diff_details(
    left: object,
    right: object,
    path: str = "$",
    *,
    limit: int = 64,
) -> tuple[tuple[str, Any, Any], ...]:
    """Return bounded public-view differences with representative values."""
    if type(left) is not type(right):
        return ((path, left, right),)
    if isinstance(left, dict):
        details: list[tuple[str, Any, Any]] = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}"
            if key not in left:
                details.append((child, "<missing>", right[key]))
            elif key not in right:
                details.append((child, left[key], "<missing>"))
            else:
                details.extend(
                    _public_diff_details(
                        left[key],
                        right[key],
                        child,
                        limit=max(0, limit - len(details)),
                    )
                )
            if len(details) >= limit:
                break
        return tuple(details[:limit])
    if isinstance(left, list):
        if len(left) != len(right):
            return ((f"{path}.length", len(left), len(right)),)
        details: list[tuple[str, Any, Any]] = []
        for index, (left_item, right_item) in enumerate(
            zip(left, right, strict=True)
        ):
            details.extend(
                _public_diff_details(
                    left_item,
                    right_item,
                    f"{path}[{index}]",
                    limit=max(0, limit - len(details)),
                )
            )
            if len(details) >= limit:
                break
        return tuple(details[:limit])
    return () if left == right else ((path, left, right),)


def public_observation_mismatch_details(
    actual_view: dict[str, Any],
    simulated_view: dict[str, Any],
) -> tuple[tuple[str, Any, Any], ...]:
    """Compare normalized public observations and retain representative values."""
    actual = json.loads(public_observation_signature(actual_view))
    simulated = json.loads(public_observation_signature(simulated_view))
    return _public_diff_details(actual, simulated)


def _top_counter_items(
    counter: Counter[str],
    *,
    limit: int = 16,
) -> tuple[tuple[str, int], ...]:
    return tuple(
        sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit]
    )


def public_observation_mismatch_paths(
    actual_view: dict[str, Any],
    simulated_view: dict[str, Any],
) -> tuple[str, ...]:
    """Compare normalized public observations without treating action history as state."""
    actual = json.loads(public_observation_signature(actual_view))
    simulated = json.loads(public_observation_signature(simulated_view))
    return _public_diff_paths(actual, simulated)


def is_stochastic_observation_path(path: str) -> bool:
    """Return whether a mismatch is plausibly an outcome/RNG-dependent leaf.

    This is classification only. Interval-compatible opponent HP is normalized
    before this boundary; other stochastic-only mismatches do not survive
    conditioning merely because they are classified here.
    """
    leaf = path.rsplit(".", 1)[-1]
    if leaf in {"hp", "hp_percent", "condition", "status", "fainted"}:
        return True
    return ".boosts." in path


def classify_public_observation_mismatch(
    actual_view: dict[str, Any],
    simulated_view: dict[str, Any],
) -> tuple[str, tuple[str, ...]]:
    """Classify a non-exact branch as stochastic-only or structural."""
    paths = public_observation_mismatch_paths(actual_view, simulated_view)
    if not paths:
        return "exact", ()
    if all(is_stochastic_observation_path(path) for path in paths):
        return "stochastic-only", paths
    return "structural", paths


def _state_key(state: dict[str, Any]) -> str:
    return json.dumps(state, sort_keys=True, separators=(",", ":"))


def identity_member_lineage(
    state: dict[str, Any],
    side: str,
) -> tuple[int, ...]:
    if side not in {"p1", "p2"}:
        raise ValueError("side must be p1 or p2")
    sides = state.get("sides")
    side_index = 0 if side == "p1" else 1
    if (
        not isinstance(sides, list)
        or len(sides) <= side_index
        or not isinstance(sides[side_index], dict)
        or not isinstance(sides[side_index].get("pokemon"), list)
    ):
        raise ValueError("particle state is missing side Pokemon for member lineage")
    return tuple(range(len(sides[side_index]["pokemon"])))


def particle_member_lineage(
    particle: BeliefParticle,
    side: str,
    *,
    require_tracked: bool = False,
) -> tuple[int, ...]:
    if side not in {"p1", "p2"}:
        raise ValueError("side must be p1 or p2")
    lineage = (
        particle.p1_member_lineage
        if side == "p1"
        else particle.p2_member_lineage
    )
    identity = identity_member_lineage(particle.state, side)
    if not lineage:
        if require_tracked:
            raise ValueError("belief particle is missing tracked member lineage")
        return identity
    if (
        len(lineage) != len(identity)
        or len(set(lineage)) != len(lineage)
        or set(lineage) != set(identity)
    ):
        raise ValueError("belief particle has invalid member lineage")
    return lineage


def compose_branch_member_lineage(
    particle: BeliefParticle,
    *,
    child_state: dict[str, Any],
    raw_lineage: object,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Compose worker branch lineage onto the particle's stable roster identity."""
    return _compose_branch_member_lineage(
        particle,
        child_state=child_state,
        raw_lineage=raw_lineage,
    )


def _particle_key(particle: BeliefParticle) -> str:
    return json.dumps(
        {
            "state": particle.state,
            "p1_member_lineage": particle.p1_member_lineage,
            "p2_member_lineage": particle.p2_member_lineage,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _compose_branch_member_lineage(
    particle: BeliefParticle,
    *,
    child_state: dict[str, Any],
    raw_lineage: object,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    tracking_active = bool(
        particle.p1_member_lineage or particle.p2_member_lineage
    )
    if raw_lineage is None:
        if tracking_active:
            raise RuntimeError(
                "particle branch omitted required stable member lineage"
            )
        return (), ()
    if not isinstance(raw_lineage, dict):
        raise RuntimeError("particle branch returned invalid member lineage")

    composed: list[tuple[int, ...]] = []
    for side in ("p1", "p2"):
        values = raw_lineage.get(side)
        parent = particle_member_lineage(particle, side)
        child_identity = identity_member_lineage(child_state, side)
        if (
            not isinstance(values, list)
            or len(values) != len(child_identity)
            or not all(isinstance(value, int) for value in values)
            or len(set(values)) != len(values)
            or set(values) != set(range(len(parent)))
        ):
            raise RuntimeError("particle branch returned invalid member lineage")
        composed.append(tuple(parent[value] for value in values))
    return composed[0], composed[1]


def _id(value: object) -> str:
    return "".join(
        character for character in str(value).lower() if character.isalnum()
    )


def _public_action_fingerprint(
    view: dict[str, Any] | None,
) -> tuple[tuple[int | None, int, str, str, int | None], ...]:
    """Collect fresh public opponent command evidence.

    Direct selected moves and pre-resolution selected switches come from the
    channel-sanitized opponent action ledger. A move prevented before execution
    may appear only in public_execution_delta as a visible cant/attempted_move.
    No sealed submitted command is consulted.
    """
    if not isinstance(view, dict):
        return ()

    by_slot: dict[
        tuple[int | None, int],
        tuple[str, str, int | None] | None,
    ] = {}

    def add_action(
        *,
        turn: int | None,
        slot: int,
        kind: str,
        value: object,
        target: int | None = None,
    ) -> None:
        if slot <= 0 or kind not in {"move", "switch"}:
            return
        action_value = _id(value)
        if not action_value:
            return
        key = (turn, slot)
        incoming = (kind, action_value, target)
        previous = by_slot.get(key)
        if key not in by_slot:
            by_slot[key] = incoming
            return
        if previous is None:
            return
        previous_kind, previous_value, previous_target = previous
        if previous_kind != kind or previous_value != action_value:
            by_slot[key] = None
            return
        if (
            kind == "move"
            and previous_target is not None
            and target is not None
            and previous_target != target
        ):
            by_slot[key] = None
            return
        by_slot[key] = (
            kind,
            action_value,
            previous_target if previous_target is not None else target,
        )

    values = view.get("opponent_last_actions")
    if isinstance(values, list):
        for value in values:
            if not isinstance(value, dict):
                continue
            turn = value.get("turn")
            slot = value.get("slot")
            target = value.get("target")
            if turn is not None and not isinstance(turn, int):
                continue
            if not isinstance(slot, int):
                continue
            if target is not None and not isinstance(target, int):
                continue

            switch_species = value.get("switch_species")
            if isinstance(switch_species, str) and switch_species:
                add_action(
                    turn=turn,
                    slot=slot,
                    kind="switch",
                    value=switch_species,
                )
                continue
            add_action(
                turn=turn,
                slot=slot,
                kind="move",
                value=value.get("move"),
                target=target,
            )

    execution = view.get("public_execution_delta")
    if isinstance(execution, dict):
        turn = execution.get("turn")
        if turn is not None and not isinstance(turn, int):
            turn = None
        actions = execution.get("actions")
        if isinstance(actions, list):
            for action in actions:
                if not isinstance(action, dict):
                    continue
                if action.get("side") != "opponent":
                    continue
                slot = action.get("slot")
                if not isinstance(slot, int):
                    continue
                outcome = action.get("outcome")
                move = None
                if (
                    outcome == "executed"
                    and action.get("source") == "selected"
                ):
                    move = action.get("move")
                elif outcome == "prevented":
                    move = action.get("attempted_move")
                if not isinstance(move, str) or not move:
                    continue
                add_action(
                    turn=turn,
                    slot=slot,
                    kind="move",
                    value=move,
                    target=None,
                )

    actions = []
    for (turn, slot), value in by_slot.items():
        if value is None:
            continue
        kind, action_value, target = value
        actions.append((turn, slot, kind, action_value, target))
    return tuple(
        sorted(
            actions,
            key=lambda value: (
                -1 if value[0] is None else value[0],
                value[1],
                value[2],
                value[3],
                -99 if value[4] is None else value[4],
            ),
        )
    )


def _fresh_public_action_fingerprint(
    view: dict[str, Any],
    *,
    previous_public_view: dict[str, Any] | None = None,
) -> tuple[tuple[int | None, int, str, str, int | None], ...]:
    current = _public_action_fingerprint(view)
    if previous_public_view is not None:
        previous = _public_action_fingerprint(previous_public_view)
        if current == previous:
            return ()
    return current


def _observed_opponent_actions(
    view: dict[str, Any],
    *,
    previous_public_view: dict[str, Any] | None = None,
) -> tuple[tuple[int, str, str, int | None], ...]:
    return tuple(
        (slot, kind, value, target)
        for _, slot, kind, value, target in _fresh_public_action_fingerprint(
            view,
            previous_public_view=previous_public_view,
        )
    )


_TRANSFORMATION_COMMANDS = ("mega", "megax", "megay", "ultra")
_MEGA_COMMANDS = ("mega", "megax", "megay")
_MEGA_CAPABLE_SPECIES = frozenset(
    species
    for item_id in MEGA_ITEM_IDS
    for species in TRANSFORM_ITEM_SPECIES_IDS.get(item_id, ())
)


def _public_view_side_id(
    view: dict[str, Any],
    *,
    fallback_view: dict[str, Any] | None = None,
) -> str | None:
    for candidate in (view, fallback_view):
        if not isinstance(candidate, dict):
            continue
        request = candidate.get("request")
        if not isinstance(request, dict):
            continue
        side = request.get("side")
        if not isinstance(side, dict):
            continue
        side_id = side.get("id")
        if side_id in {"p1", "p2"}:
            return side_id
    return None


def _public_opponent_transform_requirements(
    view: dict[str, Any],
    *,
    previous_public_view: dict[str, Any] | None = None,
) -> dict[int, tuple[str, ...]] | None:
    """Return public command-modifier requirements by opponent active slot.

    An empty mapping is authoritative evidence that no opponent slot transformed
    on the observed action turn. None means the public projection cannot safely
    align transformation events with that turn, so callers must fail open.

    -mega proves Mega Evolution but does not itself prove which Showdown command
    token selected it in every supported ruleset. Keep mega/megax/megay as a
    public-equivalent family and let the particle-local legal-choice validator
    resolve the exact command. -burst maps to ultra.
    """
    actions = _fresh_public_action_fingerprint(
        view,
        previous_public_view=previous_public_view,
    )
    turns = {turn for turn, *_ in actions if turn is not None}
    if len(turns) != 1:
        return None
    action_turn = next(iter(turns))

    view_side = _public_view_side_id(
        view,
        fallback_view=previous_public_view,
    )
    if view_side is None:
        return None
    opponent_side = "p2" if view_side == "p1" else "p1"

    delta = view.get("public_event_delta")
    if not isinstance(delta, dict):
        return None
    if delta.get("turn") != action_turn:
        return None
    unsupported = delta.get("unsupported")
    if unsupported not in (None, []) and unsupported != ():
        return None
    events = delta.get("events")
    if not isinstance(events, list):
        return None

    requirements: dict[int, tuple[str, ...]] = {}
    for event in events:
        if not isinstance(event, list) or not event:
            continue
        event_name = event[0]
        if event_name not in {"-mega", "-burst"}:
            continue
        if len(event) < 2 or not isinstance(event[1], str):
            return None
        actor = event[1]
        if len(actor) != 3 or actor[:2] not in {"p1", "p2"}:
            return None
        slot_letter = actor[2]
        if not ("a" <= slot_letter <= "z"):
            return None
        if actor[:2] != opponent_side:
            continue

        slot = ord(slot_letter) - ord("a") + 1
        allowed = _MEGA_COMMANDS if event_name == "-mega" else ("ultra",)
        previous = requirements.get(slot)
        if previous is not None and previous != allowed:
            return None
        requirements[slot] = allowed

    return requirements


def observed_public_actions(
    view: dict[str, Any],
    *,
    previous_public_view: dict[str, Any] | None = None,
) -> tuple[tuple[int, str, str, int | None], ...]:
    """Return fresh public semantic opponent actions by active slot."""
    return _observed_opponent_actions(
        view,
        previous_public_view=previous_public_view,
    )


def _public_active_species_id(
    view: dict[str, Any],
    *,
    slot: int,
) -> str | None:
    opponent = view.get("opponent")
    active = opponent.get("active") if isinstance(opponent, dict) else None
    if not isinstance(active, list) or slot <= 0 or slot > len(active):
        return None
    member = active[slot - 1]
    if not isinstance(member, dict):
        return None
    species = member.get("species")
    return _id(species) if isinstance(species, str) and species else None


def _partial_public_transform_requirements(
    view: dict[str, Any],
    *,
    actions: tuple[tuple[int, str, str, int | None], ...],
    previous_public_view: dict[str, Any] | None = None,
) -> dict[int, tuple[str, ...]] | None:
    """Return per-observed-slot transform constraints for partial action evidence.

    Positive public transformation events constrain the corresponding observed
    move slot directly. Absence of a transformation event is used only when the
    public active species is itself Mega-capable. That narrow gate keeps
    unrelated partial-action recovery behavior unchanged while preventing an
    ordinary public Gardevoir move from being replayed as a Mega command.

    None means event/action alignment is not publicly provable, so callers fail
    open and apply no transformation pruning.
    """
    aligned = _public_opponent_transform_requirements(
        view,
        previous_public_view=previous_public_view,
    )
    if aligned is None:
        return None

    requirements: dict[int, tuple[str, ...]] = {}
    for slot, kind, _value, _target in actions:
        if kind != "move":
            continue
        allowed = aligned.get(slot)
        if allowed is not None:
            requirements[slot] = allowed
            continue
        species = _public_active_species_id(view, slot=slot)
        if species in _MEGA_CAPABLE_SPECIES:
            requirements[slot] = ()
    return requirements


def _state_party_species(
    state: dict[str, Any],
    *,
    side: str,
    party_slot: int,
) -> str | None:
    if side not in {"p1", "p2"} or party_slot <= 0:
        return None
    sides = state.get("sides")
    side_index = 0 if side == "p1" else 1
    if (
        not isinstance(sides, list)
        or len(sides) <= side_index
        or not isinstance(sides[side_index], dict)
    ):
        return None
    pokemon = sides[side_index].get("pokemon")
    if not isinstance(pokemon, list) or party_slot > len(pokemon):
        return None
    member = pokemon[party_slot - 1]
    if not isinstance(member, dict):
        return None
    set_data = member.get("set")
    if not isinstance(set_data, dict):
        return None
    species = set_data.get("species")
    return _id(species) if isinstance(species, str) and species else None


def _choice_matches_observed_actions(
    choice: str,
    actions: tuple[tuple[int, str, str, int | None], ...],
    *,
    state: dict[str, Any] | None = None,
    side: str | None = None,
    transform_requirements: dict[int, tuple[str, ...]] | None = None,
) -> bool:
    commands = [command.strip().split() for command in choice.split(",")]
    for slot, kind, action_value, observed_target in actions:
        if slot > len(commands):
            return False
        tokens = commands[slot - 1]
        if len(tokens) < 2:
            return False

        if kind == "move":
            if tokens[0] != "move" or _id(tokens[1]) != action_value:
                return False
            command_target = next(
                (
                    int(token)
                    for token in tokens[2:]
                    if token.lstrip("+-").isdigit()
                ),
                None,
            )
            if (
                observed_target is not None
                and command_target is not None
                and command_target != observed_target
            ):
                return False

            if (
                transform_requirements is not None
                and slot in transform_requirements
            ):
                transform_tokens = [
                    token
                    for token in tokens[2:]
                    if token in _TRANSFORMATION_COMMANDS
                ]
                if len(transform_tokens) > 1:
                    return False
                command_transform = (
                    transform_tokens[0] if transform_tokens else None
                )
                allowed = transform_requirements[slot]
                if allowed:
                    if command_transform not in allowed:
                        return False
                elif command_transform is not None:
                    return False
            continue

        if kind == "switch":
            if tokens[0] != "switch" or not tokens[1].isdigit():
                return False
            if state is None or side is None:
                return False
            species = _state_party_species(
                state,
                side=side,
                party_slot=int(tokens[1]),
            )
            if species != action_value:
                return False
            continue

        return False
    return True


def _filter_responses_by_public_actions(
    responses: tuple[str, ...],
    actual_public_view: dict[str, Any],
    *,
    previous_public_view: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    side: str | None = None,
    fail_open: bool = True,
) -> tuple[str, ...]:
    actions = _observed_opponent_actions(
        actual_public_view,
        previous_public_view=previous_public_view,
    )
    if not actions:
        return responses
    transform_requirements = _partial_public_transform_requirements(
        actual_public_view,
        actions=actions,
        previous_public_view=previous_public_view,
    )
    filtered = tuple(
        response
        for response in responses
        if _choice_matches_observed_actions(
            response,
            actions,
            state=state,
            side=side,
            transform_requirements=transform_requirements,
        )
    )
    if filtered or not fail_open:
        return filtered
    # Public parsing is an optimization, not a posterior-deletion rule. Species
    # disguises and other ambiguous projections may prevent exact switch-index
    # resolution; in that case preserve the candidate set.
    return responses


def filter_choices_by_public_actions(
    responses: tuple[str, ...],
    actual_public_view: dict[str, Any],
    *,
    previous_public_view: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    side: str | None = None,
    fail_open: bool = True,
) -> tuple[str, ...]:
    """Filter exact commands against fresh public move/switch evidence."""
    return _filter_responses_by_public_actions(
        responses,
        actual_public_view,
        previous_public_view=previous_public_view,
        state=state,
        side=side,
        fail_open=fail_open,
    )


def _public_actions_cover_active_slots(
    actual_public_view: dict[str, Any],
    *,
    previous_public_view: dict[str, Any] | None = None,
) -> bool:
    actions = _observed_opponent_actions(
        actual_public_view,
        previous_public_view=previous_public_view,
    )
    opponent = actual_public_view.get("opponent")
    active = opponent.get("active") if isinstance(opponent, dict) else None
    if not isinstance(active, list) or not active:
        return False
    expected_slots = set(range(1, len(active) + 1))
    return {slot for slot, _, _, _ in actions} == expected_slots


def _observed_joint_move_candidates(
    actual_public_view: dict[str, Any],
    *,
    previous_public_view: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    actions = _observed_opponent_actions(
        actual_public_view,
        previous_public_view=previous_public_view,
    )
    if not _public_actions_cover_active_slots(
        actual_public_view,
        previous_public_view=previous_public_view,
    ):
        return ()
    if any(kind != "move" for _, kind, _, _ in actions):
        return ()

    transform_requirements = _public_opponent_transform_requirements(
        actual_public_view,
        previous_public_view=previous_public_view,
    )

    per_slot: list[tuple[str, ...]] = []
    for slot, _kind, move_id, target in actions:
        bases = [f"move {move_id}"]
        if target is not None and target != -slot:
            bases.append(f"move {move_id} {target:+d}")

        variants = []
        for base in bases:
            if transform_requirements is None:
                variants.append(base)
                variants.extend(
                    f"{base} {event}"
                    for event in _TRANSFORMATION_COMMANDS
                )
                continue

            allowed = transform_requirements.get(slot, ())
            if not allowed:
                variants.append(base)
                continue
            variants.extend(f"{base} {event}" for event in allowed)
        per_slot.append(tuple(dict.fromkeys(variants)))

    return tuple(
        ", ".join(commands)
        for commands in product(*per_slot)
    )


def observed_joint_move_candidates(
    actual_public_view: dict[str, Any],
    *,
    previous_public_view: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    """Return bounded joint commands when every public action is a move."""
    return _observed_joint_move_candidates(
        actual_public_view,
        previous_public_view=previous_public_view,
    )


def public_opponent_moves_fully_observed(
    view: dict[str, Any],
    *,
    previous_public_view: dict[str, Any] | None = None,
) -> bool:
    """Return whether every opponent slot has a fresh selected move."""
    return bool(
        _observed_joint_move_candidates(
            view,
            previous_public_view=previous_public_view,
        )
    )


def public_opponent_actions_fully_observed(
    view: dict[str, Any],
    *,
    previous_public_view: dict[str, Any] | None = None,
) -> bool:
    """Return whether every opponent slot has fresh public move/switch evidence."""
    return _public_actions_cover_active_slots(
        view,
        previous_public_view=previous_public_view,
    )


def _normalize(particles: Iterable[BeliefParticle]) -> tuple[BeliefParticle, ...]:
    particles = tuple(particles)
    total = sum(particle.weight for particle in particles)
    if total <= 0:
        return ()
    return tuple(
        BeliefParticle(
            state=particle.state,
            weight=particle.weight / total,
            world_id=particle.world_id,
            history_id=particle.history_id,
            p1_member_lineage=particle.p1_member_lineage,
            p2_member_lineage=particle.p2_member_lineage,
        )
        for particle in particles
    )


def resample_particles(
    particles: tuple[BeliefParticle, ...],
    *,
    limit: int,
    seed: int = 0,
) -> tuple[BeliefParticle, ...]:
    """Bound a posterior with deterministic systematic resampling.

    Resampling operates only on already-conditioned particles. It never consults
    the live battle state or hidden opponent information.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")

    normalized = _normalize(particles)
    if len(normalized) <= limit:
        return normalized

    rng = random.Random(seed)
    step = 1.0 / limit
    target = rng.random() * step
    index = 0
    cumulative = normalized[0].weight
    counts: dict[str, tuple[BeliefParticle, int]] = {}

    for sample_index in range(limit):
        position = target + sample_index * step
        while position > cumulative and index < len(normalized) - 1:
            index += 1
            cumulative += normalized[index].weight
        particle = normalized[index]
        key = _particle_key(particle)
        previous = counts.get(key)
        if previous is None:
            counts[key] = (particle, 1)
        else:
            counts[key] = (previous[0], previous[1] + 1)

    return tuple(
        BeliefParticle(
            state=particle.state,
            weight=count / limit,
            world_id=particle.world_id,
            history_id=particle.history_id,
            p1_member_lineage=particle.p1_member_lineage,
            p2_member_lineage=particle.p2_member_lineage,
        )
        for particle, count in counts.values()
    )


def resample_particles_by_world(
    particles: tuple[BeliefParticle, ...],
    *,
    limit: int,
    seed: int = 0,
) -> tuple[BeliefParticle, ...]:
    """Bound particles while preserving surviving hidden-world diversity."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    normalized = _normalize(particles)
    if len(normalized) <= limit:
        return normalized

    groups: dict[str, list[BeliefParticle]] = {}
    for particle in normalized:
        key = particle.world_id or "<unlabeled>"
        groups.setdefault(key, []).append(particle)

    if len(groups) > limit:
        return resample_particles(normalized, limit=limit, seed=seed)

    masses = {
        key: sum(particle.weight for particle in group)
        for key, group in groups.items()
    }
    slots = {key: 1 for key in groups}
    remaining = limit - len(groups)
    if remaining > 0:
        total_mass = sum(masses.values())
        raw = {
            key: remaining * masses[key] / total_mass
            for key in groups
        }
        for key in groups:
            slots[key] += int(raw[key])
        leftover = limit - sum(slots.values())
        order = sorted(
            groups,
            key=lambda key: (-(raw[key] - int(raw[key])), -masses[key], key),
        )
        for key in order[:leftover]:
            slots[key] += 1

    sampled: list[BeliefParticle] = []
    for offset, key in enumerate(sorted(groups)):
        group = tuple(groups[key])
        group_mass = masses[key]
        local = _normalize(group)
        chosen = resample_particles(
            local,
            limit=slots[key],
            seed=seed + offset + 1,
        )
        sampled.extend(
            BeliefParticle(
                state=particle.state,
                weight=particle.weight * group_mass,
                world_id=particle.world_id,
                history_id=particle.history_id,
                p1_member_lineage=particle.p1_member_lineage,
                p2_member_lineage=particle.p2_member_lineage,
            )
            for particle in chosen
        )
    return _normalize(sampled)


def _unsupported_public_transition_evidence(
    view: dict[str, Any],
) -> tuple[str, ...]:
    delta = view.get("public_event_delta")
    if not isinstance(delta, dict):
        return ()
    values = delta.get("unsupported")
    if not isinstance(values, list):
        return ()
    return tuple(value for value in values if isinstance(value, str) and value)



def _has_aligned_public_damage_difference(
    actual_view: dict[str, Any],
    simulated_view: dict[str, Any],
) -> bool:
    """Require public evidence for an actual damage-roll disagreement.

    This only gates an extra positive-witness search. A failed or skipped probe
    cannot establish mechanical impossibility, and no reduced-view mismatch is
    ever accepted without a complete exact Showdown successor witness.
    """
    actual_delta = actual_view.get("public_event_delta")
    simulated_delta = simulated_view.get("public_event_delta")
    if not isinstance(actual_delta, dict) or not isinstance(simulated_delta, dict):
        return False
    if actual_delta.get("turn") != simulated_delta.get("turn"):
        return False
    actual_events = actual_delta.get("events")
    simulated_events = simulated_delta.get("events")
    if not isinstance(actual_events, list) or not isinstance(simulated_events, list):
        return False
    return any(
        isinstance(actual, list)
        and isinstance(simulated, list)
        and len(actual) >= 3
        and len(simulated) >= 3
        and actual[0] == simulated[0] == "-damage"
        and actual[1] == simulated[1]
        and actual[2] != simulated[2]
        for actual, simulated in zip(actual_events, simulated_events)
    )


def _find_exact_damage_bucket_witness(
    worker: ShowdownSearchWorker,
    *,
    state: dict[str, Any],
    branch: dict[str, Any],
    wanted: str,
) -> tuple[dict[str, Any] | None, int]:
    """Probe the pinned 16 discrete randomizer buckets for one exact successor.

    Non-damage RNG decisions remain on the supplied sampled path; hence a miss
    is INCONCLUSIVE, not an exhaustive disproof of the hidden world. A hit is
    admitted only when the entire sanitized observation matches, including
    ordered events, crits, hit counts, HP, and the exact request.
    """
    probes = [{**branch, "damage_bucket": bucket} for bucket in range(16)]
    outcomes = worker.branch_many(state=state, branches=probes)
    if len(outcomes) != len(probes):
        raise RuntimeError("damage-roll probe returned incomplete branch results")
    for bucket, outcome in enumerate(outcomes):
        if (
            outcome.get("damage_bucket") != bucket
            or not isinstance(outcome.get("damage_roll_calls"), int)
            or isinstance(outcome.get("damage_roll_calls"), bool)
            or outcome["damage_roll_calls"] < 1
        ):
            continue
        child = outcome.get("state")
        if not isinstance(child, dict):
            raise RuntimeError("damage-roll witness omitted exact successor state")
        view = outcome.get("view")
        if not isinstance(view, dict):
            raise RuntimeError("damage-roll witness omitted public projection")
        if public_observation_signature(view) == wanted:
            return outcome, len(outcomes)
    return None, len(outcomes)



def _sampled_hp_envelope_compatible(
    actual_view: dict[str, Any],
    sampled_views: tuple[dict[str, Any], ...],
) -> bool:
    """Conservative HP envelope evidence from pinned Showdown outcomes.

    This is not an exhaustive proof across critical-hit or other RNG paths.
    Non-HP public fields must agree across a sampled successor and observation.
    Only HP values may vary, and each observed HP must lie in the sampled
    minimum/maximum envelope. This never authorizes a native successor.
    """
    if not sampled_views:
        return False

    def flatten(value: Any, path: str = "$") -> dict[str, Any]:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, child in value.items():
                result.update(flatten(child, f"{path}.{key}"))
            return result
        if isinstance(value, list):
            result = {f"{path}.length": len(value)}
            for index, child in enumerate(value):
                result.update(flatten(child, f"{path}[{index}]"))
            return result
        return {path: value}

    actual = flatten(json.loads(public_observation_signature(actual_view)))
    samples = [
        flatten(json.loads(public_observation_signature(view)))
        for view in sampled_views
    ]
    comparable: list[dict[str, Any]] = []
    for sample in samples:
        if sample.keys() != actual.keys():
            continue
        compatible = True
        for path, expected in actual.items():
            if path.endswith((".hp", ".hp_percent")):
                continue
            if sample[path] != expected:
                compatible = False
                break
        if compatible:
            comparable.append(sample)
    if not comparable:
        return False
    hp_paths = [
        path for path in actual
        if path.endswith((".hp", ".hp_percent"))
    ]
    if not hp_paths:
        return False
    for path in hp_paths:
        expected = actual[path]
        samples_at_path = [sample[path] for sample in comparable]
        if isinstance(expected, bool) or not isinstance(expected, (int, float)):
            if any(value != expected for value in samples_at_path):
                return False
            continue
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in samples_at_path
        ):
            return False
        if not min(samples_at_path) <= expected <= max(samples_at_path):
            return False
    return True


def _source_world_id(particle: BeliefParticle, index: int) -> str:
    """Stable source-hypothesis label for sampled-conditioning diagnostics."""
    return particle.world_id or particle.history_id or f"particle-{index}"


def merge_sampled_world_witnesses(
    starting_particles: tuple[BeliefParticle, ...],
    witnessed_particles: tuple[BeliefParticle, ...],
) -> tuple[BeliefParticle, ...]:
    """Merge cross-batch witnesses without changing prior hidden-world mass."""
    prior_mass: dict[str, float] = {}
    starting_history: list[tuple[str, str]] = []
    for index, particle in enumerate(starting_particles):
        world_id = _source_world_id(particle, index)
        prior_mass[world_id] = prior_mass.get(world_id, 0.0) + particle.weight
        if particle.history_id:
            starting_history.append((world_id, particle.history_id))

    grouped: dict[str, dict[str, tuple[BeliefParticle, float]]] = {}
    for particle in witnessed_particles:
        world_id = particle.world_id
        if not world_id and particle.history_id:
            candidates = [
                (source_world_id, history_id)
                for source_world_id, history_id in starting_history
                if particle.history_id == history_id
                or particle.history_id.startswith(history_id + "|")
            ]
            if candidates:
                world_id = max(candidates, key=lambda item: len(item[1]))[0]
        if not world_id or world_id not in prior_mass:
            continue
        key = _particle_key(particle)
        world_group = grouped.setdefault(world_id, {})
        previous = world_group.get(key)
        if previous is None:
            world_group[key] = (particle, particle.weight)
        else:
            world_group[key] = (previous[0], previous[1] + particle.weight)

    if set(grouped) != set(prior_mass):
        return ()

    merged: list[BeliefParticle] = []
    for world_id in sorted(grouped):
        descendants = grouped[world_id]
        sampled_mass = sum(weight for _particle, weight in descendants.values())
        if sampled_mass <= 0:
            return ()
        world_mass = prior_mass[world_id]
        for particle, sampled_weight in descendants.values():
            merged.append(
                BeliefParticle(
                    state=particle.state,
                    weight=world_mass * sampled_weight / sampled_mass,
                    world_id=particle.world_id,
                    history_id=particle.history_id,
                    p1_member_lineage=particle.p1_member_lineage,
                    p2_member_lineage=particle.p2_member_lineage,
                )
            )

    return _normalize(merged)


def _publicly_seen_species(view: dict[str, Any]) -> set[str]:
    opponent = view.get("opponent")
    if not isinstance(opponent, dict):
        return set()
    revealed = opponent.get("revealed")
    if not isinstance(revealed, list):
        return set()
    return {
        _id(str(entry.get("species", "")))
        for entry in revealed
        if isinstance(entry, dict)
        and entry.get("seen") is True
        and _id(str(entry.get("species", "")))
    }


def _particle_selected_species(
    particle: BeliefParticle,
    *,
    ai_side: str,
) -> set[str] | None:
    sides = particle.state.get("sides")
    opponent_index = 1 if ai_side == "p1" else 0
    if (
        not isinstance(sides, list)
        or len(sides) <= opponent_index
        or not isinstance(sides[opponent_index], dict)
    ):
        return None
    pokemon = sides[opponent_index].get("pokemon")
    if not isinstance(pokemon, list) or not pokemon:
        return None

    species: set[str] = set()
    for mon in pokemon:
        if not isinstance(mon, dict):
            return None
        set_data = mon.get("set")
        if not isinstance(set_data, dict):
            return None
        value = _id(str(set_data.get("species") or set_data.get("name") or ""))
        if not value:
            return None
        species.add(value)
    return species


def _public_roster_exhaustive_exclusions(
    particles: tuple[BeliefParticle, ...],
    *,
    ai_side: str,
    actual_public_view: dict[str, Any],
) -> tuple[set[int], tuple[str, ...]]:
    """Exclude worlds contradicted by public bring-four membership evidence.

    The public producer marks a preview-roster species as seen only after a
    channel-visible switch/drag/replace event. Once seen, that species must be one
    of the four Pokemon selected in any compatible exact world. This fact is
    deterministic and RNG-independent, so it is valid exhaustive negative
    evidence rather than a sampled miss.
    """
    seen_species = _publicly_seen_species(actual_public_view)
    if not seen_species:
        return set(), ()

    incompatible_indexes: set[int] = set()
    world_members: dict[str, list[int]] = {}
    for index, particle in enumerate(particles):
        world_id = _source_world_id(particle, index)
        world_members.setdefault(world_id, []).append(index)
        selected = _particle_selected_species(particle, ai_side=ai_side)
        if selected is not None and not seen_species.issubset(selected):
            incompatible_indexes.add(index)

    excluded_worlds = tuple(
        sorted(
            world_id
            for world_id, indexes in world_members.items()
            if indexes and all(index in incompatible_indexes for index in indexes)
        )
    )
    return incompatible_indexes, excluded_worlds


def condition_particles(
    worker: ShowdownSearchWorker,
    *,
    particles: tuple[BeliefParticle, ...],
    ai_side: str,
    ai_choice: str,
    actual_public_view: dict[str, Any],
    previous_public_view: dict[str, Any] | None = None,
    opponent_choices: dict[str, tuple[str, ...]] | None = None,
    rng_seeds: tuple[str | None, ...] = (None,),
    previews: dict[str, list[str]] | None = None,
    damage_probe_limit: int = 1,
) -> ParticleUpdate:
    # A damage-roll witness is an optional positive-evidence probe, not a
    # prerequisite for ordinary exact sampled conditioning. Its bounded work
    # must never scale silently with particles * responses * RNG samples.
    if (
        isinstance(damage_probe_limit, bool)
        or not isinstance(damage_probe_limit, int)
        or damage_probe_limit < 0
    ):
        raise ValueError("damage_probe_limit must be a nonnegative integer")
    if ai_side not in {"p1", "p2"}:
        raise ValueError("ai_side must be p1 or p2")
    if ai_choice == "":
        raise ValueError(
            "raw empty AI choice is ambiguous; "
            f"use {FORCED_WAIT_CHOICE!r} for a forced wait"
        )
    if not particles:
        _audit_rejection(stage='input', outcome='no-particles')
        return ParticleUpdate((), 0, 0, 0)

    source_world_ids = tuple(
        _source_world_id(particle, index)
        for index, particle in enumerate(particles)
    )

    # A public mechanics event that the worker cannot canonicalize is evidence
    # that our exact-match predicate is incomplete. Never silently accept a
    # particle by comparing only the reduced board in that case; force the
    # persistent engine down its degraded/recovery path instead.
    unsupported = _unsupported_public_transition_evidence(actual_public_view)
    if unsupported:
        _audit_rejection(stage='public-evidence', outcome='unsupported', details=list(unsupported))
        return ParticleUpdate(
            (),
            generated=0,
            matched=0,
            deduplicated=0,
            structural_mismatches=1,
            sampled_unresolved_world_ids=tuple(sorted(set(source_world_ids))),
            unsupported_public_evidence=unsupported,
        )

    opponent_side = "p2" if ai_side == "p1" else "p1"
    wanted = public_observation_signature(actual_public_view)
    survivors: list[BeliefParticle] = []
    generated = 0
    matched = 0
    stochastic_only_mismatches = 0
    structural_mismatches = 0
    structural_mismatch_paths: Counter[str] = Counter()
    structural_mismatch_worlds: Counter[str] = Counter()
    structural_mismatch_examples: list[StructuralMismatchExample] = []
    structural_example_keys: set[tuple[str, str]] = set()
    matched_source_world_ids: set[str] = set()
    damage_probed_responses: set[tuple[int, str]] = set()
    damage_probes_used = 0

    observed_candidates = _observed_joint_move_candidates(
        actual_public_view,
        previous_public_view=previous_public_view,
    )
    (
        roster_incompatible_indexes,
        roster_excluded_world_ids,
    ) = _public_roster_exhaustive_exclusions(
        particles,
        ai_side=ai_side,
        actual_public_view=actual_public_view,
    )

    _audit_rejection(stage='conditioning-start', particles=len(particles), ai_choice=ai_choice, observed_turn=actual_public_view.get('turn'), rng_samples=len(rng_seeds), seen_actions=list(observed_candidates))
    for particle_index, particle in enumerate(particles):
        source_world_id = _source_world_id(particle, particle_index)
        if particle_index in roster_incompatible_indexes:
            _audit_rejection(stage='roster', particle=particle_index, world=source_world_id, outcome='exhaustive-public-roster-exclusion')
            continue
        responses: tuple[str, ...]
        validator = getattr(worker, "validate_choices", None)

        if (
            opponent_choices is None
            and observed_candidates
            and callable(validator)
        ):
            validated = tuple(
                validator(
                    state=particle.state,
                    side=opponent_side,
                    candidates=list(observed_candidates),
                )
            )
            if validated:
                responses = validated
            else:
                responses = tuple(
                    worker.legal_choices(state=particle.state, side=opponent_side)
                )
        else:
            legal_responses = tuple(
                worker.legal_choices(state=particle.state, side=opponent_side)
            )
            if opponent_choices is None:
                responses = legal_responses
            else:
                requested = opponent_choices.get(particle.world_id)
                if requested is None:
                    responses = legal_responses
                else:
                    legal_set = set(legal_responses)
                    responses = tuple(
                        response for response in requested if response in legal_set
                    )

        responses = _filter_responses_by_public_actions(
            tuple(responses),
            actual_public_view,
            previous_public_view=previous_public_view,
            state=particle.state,
            side=opponent_side,
        )
        if not responses:
            _audit_rejection(stage='response-filter', particle=particle_index, world=source_world_id, outcome='zero-eligible-responses')
            continue
        _audit_rejection(stage='responses', particle=particle_index, world=source_world_id, count=len(responses), responses=list(responses))

        branch_count = len(responses) * len(rng_seeds)
        branch_weight = particle.weight / branch_count
        branches = []
        identities = []
        for response in responses:
            for rng_seed in rng_seeds:
                branch = {
                    "p1_choice": ai_choice if ai_side == "p1" else response,
                    "p2_choice": ai_choice if ai_side == "p2" else response,
                    "include_state": True,
                    "view_side": ai_side,
                }
                if previews is not None:
                    branch["previews"] = previews
                if rng_seed is not None:
                    branch["rng_seed"] = rng_seed
                branches.append(branch)
                identities.append((response, rng_seed))

        resolved = worker.branch_many(state=particle.state, branches=branches)
        generated += len(resolved)
        for result, identity, original_branch in zip(
            resolved, identities, branches, strict=True
        ):
            response, rng_seed = identity
            state = result.get("state")
            if not isinstance(state, dict):
                raise RuntimeError("particle branch did not return exact state")
            view = result.get("view")
            if not isinstance(view, dict):
                view = worker.state_view(
                    state=state,
                    side=ai_side,
                    previews=previews,
                )
            if public_observation_signature(view) != wanted:
                mismatch_kind, mismatch_paths = classify_public_observation_mismatch(actual_public_view, view)
                if _REJECTION_AUDIT.get() is not None:
                    mismatches = public_observation_mismatch_details(
                        actual_public_view, view,
                    )
                    _audit_rejection(
                        stage="sampled-branch",
                        particle=particle_index,
                        world=source_world_id,
                        opponent_choice=response,
                        rng_sample=identities.index(identity),
                        outcome="sample-mismatch-unresolved",
                        mismatch_kind=mismatch_kind,
                        mismatch_paths=list(mismatch_paths)[:12],
                        first_value_differences=[
                            {
                                "path": path,
                                "actual": _audit_public_value(actual),
                                "simulated": _audit_public_value(simulated),
                            }
                            for path, actual, simulated in mismatches[:8]
                        ],
                        candidate_start_active=_audit_active_state(particle.state),
                    )
                # The first sampled damage value cannot disprove the world.
                # Replay this exact action pair across the pinned finite
                # randomizer domain once per particle/response. Install only
                # a *concrete* replay whose complete public view is exact.
                damage_key = (particle_index, response)
                if (
                    damage_probes_used < damage_probe_limit
                    and damage_key not in damage_probed_responses
                    and _has_aligned_public_damage_difference(
                        actual_public_view, view
                    )
                ):
                    damage_probed_responses.add(damage_key)
                    damage_probes_used += 1
                    witness, examined = _find_exact_damage_bucket_witness(
                        worker,
                        state=particle.state,
                        branch=original_branch,
                        wanted=wanted,
                    )
                    generated += examined
                    _audit_rejection(stage='damage-probe', particle=particle_index, world=source_world_id, opponent_choice=response, attempted=examined, outcome='positive-witness' if witness is not None else 'unresolved-no-witness')
                    if witness is not None:
                        child_state = witness["state"]
                        matched += 1
                        matched_source_world_ids.add(source_world_id)
                        rng_label = "native" if rng_seed is None else rng_seed
                        bucket = witness["damage_bucket"]
                        history = (
                            f"{particle.history_id}|{response}|"
                            f"{rng_label}|damage-bucket-{bucket}"
                        ).strip("|")
                        p1_lineage, p2_lineage = _compose_branch_member_lineage(
                            particle,
                            child_state=child_state,
                            raw_lineage=witness.get("member_lineage"),
                        )
                        survivors.append(
                            BeliefParticle(
                                state=child_state,
                                weight=branch_weight,
                                world_id=particle.world_id,
                                history_id=history,
                                p1_member_lineage=p1_lineage,
                                p2_member_lineage=p2_lineage,
                            )
                        )
                        continue

                kind, paths = classify_public_observation_mismatch(
                    actual_public_view,
                    view,
                )
                if kind == "stochastic-only":
                    stochastic_only_mismatches += 1
                else:
                    structural_mismatches += 1
                    structural_mismatch_paths.update(paths)
                    structural_mismatch_worlds[source_world_id] += 1
                    if len(structural_mismatch_examples) < 8:
                        for path, actual, simulated in (
                            public_observation_mismatch_details(
                                actual_public_view,
                                view,
                            )
                        ):
                            key = (source_world_id, path)
                            if key in structural_example_keys:
                                continue
                            structural_example_keys.add(key)
                            structural_mismatch_examples.append(
                                StructuralMismatchExample(
                                    world_id=source_world_id,
                                    path=path,
                                    actual=actual,
                                    simulated=simulated,
                                    opponent_choice=response,
                                    rng_seed=rng_seed,
                                )
                            )
                            if len(structural_mismatch_examples) >= 8:
                                break
                continue
            _audit_rejection(stage='sampled-branch', particle=particle_index, world=source_world_id, opponent_choice=response, outcome='exact-public-match')
            matched += 1
            matched_source_world_ids.add(source_world_id)
            rng_label = "native" if rng_seed is None else rng_seed
            history = f"{particle.history_id}|{response}|{rng_label}".strip("|")
            p1_lineage, p2_lineage = _compose_branch_member_lineage(
                particle,
                child_state=state,
                raw_lineage=result.get("member_lineage"),
            )
            survivors.append(
                BeliefParticle(
                    state=state,
                    weight=branch_weight,
                    world_id=particle.world_id,
                    history_id=history,
                    p1_member_lineage=p1_lineage,
                    p2_member_lineage=p2_lineage,
                )
            )

    merged: dict[str, BeliefParticle] = {}
    for particle in survivors:
        key = _particle_key(particle)
        previous = merged.get(key)
        if previous is None:
            merged[key] = particle
        else:
            merged[key] = BeliefParticle(
                state=previous.state,
                weight=previous.weight + particle.weight,
                world_id=previous.world_id or particle.world_id,
                history_id=previous.history_id,
                p1_member_lineage=previous.p1_member_lineage,
                p2_member_lineage=previous.p2_member_lineage,
            )

    posterior = _normalize(merged.values())
    _audit_rejection(stage='conditioning-summary', generated=generated, matched=matched, survivors=len(posterior), stochastic_misses=stochastic_only_mismatches, structural_misses=structural_mismatches)
    all_world_ids = set(source_world_ids)
    return ParticleUpdate(
        particles=posterior,
        generated=generated,
        matched=matched,
        deduplicated=len(survivors) - len(posterior),
        stochastic_only_mismatches=stochastic_only_mismatches,
        structural_mismatches=structural_mismatches,
        matched_world_ids=tuple(sorted(matched_source_world_ids)),
        sampled_unresolved_world_ids=tuple(
            sorted(
                all_world_ids
                - matched_source_world_ids
                - set(roster_excluded_world_ids)
            )
        ),
        exhaustively_excluded_world_ids=roster_excluded_world_ids,
        structural_mismatch_paths=_top_counter_items(
            structural_mismatch_paths
        ),
        structural_mismatch_worlds=_top_counter_items(
            structural_mismatch_worlds
        ),
        structural_mismatch_examples=tuple(structural_mismatch_examples),
    )
