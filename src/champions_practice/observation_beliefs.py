"""Observation-conditioned exact belief particles."""

from __future__ import annotations

import copy
import json
import random
from dataclasses import dataclass
from itertools import product
from typing import Any, Iterable

from .search_worker import FORCED_WAIT_CHOICE, ShowdownSearchWorker


@dataclass(frozen=True)
class BeliefParticle:
    state: dict[str, Any]
    weight: float
    world_id: str = ""
    history_id: str = ""
    p1_member_lineage: tuple[int, ...] = ()
    p2_member_lineage: tuple[int, ...] = ()


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


def public_observation_signature(view: dict[str, Any]) -> str:
    """Return a stable signature for mechanically relevant public information.

    Reconstructed Showdown states may use different display names from the live
    session. Names do not affect the battle state, so normalize a winner to its
    player/opponent role and remove cosmetic names before comparing observations.
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

    This is classification only. PR #101 does not yet allow these mismatches to
    survive conditioning; PR #102 can attach mechanics-authoritative reachability
    checks to this boundary.
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
) -> tuple[tuple[int | None, int, str, int | None], ...]:
    if not isinstance(view, dict):
        return ()
    values = view.get("opponent_last_actions")
    if not isinstance(values, list):
        return ()

    actions = []
    for value in values:
        if not isinstance(value, dict):
            continue
        turn = value.get("turn")
        slot = value.get("slot")
        move = value.get("move")
        target = value.get("target")
        if turn is not None and not isinstance(turn, int):
            continue
        if not isinstance(slot, int) or slot <= 0 or not isinstance(move, str):
            continue
        if target is not None and not isinstance(target, int):
            continue
        move_id = _id(move)
        if move_id:
            actions.append((turn, slot, move_id, target))
    return tuple(sorted(actions))


def _observed_opponent_actions(
    view: dict[str, Any],
    *,
    previous_public_view: dict[str, Any] | None = None,
) -> tuple[tuple[int, str, int | None], ...]:
    current = _public_action_fingerprint(view)
    if previous_public_view is not None:
        previous = _public_action_fingerprint(previous_public_view)
        if current == previous:
            return ()
    return tuple((slot, move_id, target) for _, slot, move_id, target in current)


def _choice_matches_observed_actions(
    choice: str,
    actions: tuple[tuple[int, str, int | None], ...],
) -> bool:
    commands = [command.strip().split() for command in choice.split(",")]
    for slot, move_id, observed_target in actions:
        if slot > len(commands):
            return False
        tokens = commands[slot - 1]
        if len(tokens) < 2 or tokens[0] != "move":
            return False
        if _id(tokens[1]) != move_id:
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
    return True


def _filter_responses_by_public_actions(
    responses: tuple[str, ...],
    actual_public_view: dict[str, Any],
    *,
    previous_public_view: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    actions = _observed_opponent_actions(
        actual_public_view,
        previous_public_view=previous_public_view,
    )
    if not actions:
        return responses
    filtered = tuple(
        response
        for response in responses
        if _choice_matches_observed_actions(response, actions)
    )
    # Public action parsing is an optimization, not a posterior-deletion rule.
    # If the parsed evidence cannot be reconciled with the legal set, fail open.
    return filtered or responses


def _observed_joint_move_candidates(
    actual_public_view: dict[str, Any],
    *,
    previous_public_view: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    actions = _observed_opponent_actions(
        actual_public_view,
        previous_public_view=previous_public_view,
    )
    opponent = actual_public_view.get("opponent")
    active = opponent.get("active") if isinstance(opponent, dict) else None
    if not isinstance(active, list) or not active:
        return ()
    expected_slots = set(range(1, len(active) + 1))
    if {slot for slot, _, _ in actions} != expected_slots:
        return ()

    per_slot: list[tuple[str, ...]] = []
    for slot, move_id, target in actions:
        bases = [f"move {move_id}"]
        if target is not None and target != -slot:
            bases.append(f"move {move_id} {target:+d}")

        variants = []
        for base in bases:
            variants.append(base)
            variants.extend(
                f"{base} {event}"
                for event in ("mega", "megax", "megay", "ultra")
            )
        per_slot.append(tuple(dict.fromkeys(variants)))

    return tuple(
        ", ".join(commands)
        for commands in product(*per_slot)
    )


def public_opponent_moves_fully_observed(
    view: dict[str, Any],
    *,
    previous_public_view: dict[str, Any] | None = None,
) -> bool:
    """Return whether every opponent slot produced a fresh direct public move event."""
    return bool(
        _observed_joint_move_candidates(
            view,
            previous_public_view=previous_public_view,
        )
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
) -> ParticleUpdate:
    if ai_side not in {"p1", "p2"}:
        raise ValueError("ai_side must be p1 or p2")
    if ai_choice == "":
        raise ValueError(
            "raw empty AI choice is ambiguous; "
            f"use {FORCED_WAIT_CHOICE!r} for a forced wait"
        )
    if not particles:
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
    matched_source_world_ids: set[str] = set()

    observed_candidates = _observed_joint_move_candidates(
        actual_public_view,
        previous_public_view=previous_public_view,
    )

    for particle_index, particle in enumerate(particles):
        source_world_id = _source_world_id(particle, particle_index)
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
        )
        if not responses:
            continue

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
        for result, identity in zip(resolved, identities, strict=True):
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
                kind, _paths = classify_public_observation_mismatch(
                    actual_public_view,
                    view,
                )
                if kind == "stochastic-only":
                    stochastic_only_mismatches += 1
                else:
                    structural_mismatches += 1
                continue
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
            sorted(all_world_ids - matched_source_world_ids)
        ),
    )
