"""Persistent public-belief controller for a real Showdown practice session."""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from copy import deepcopy
from contextvars import copy_context
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import random
import secrets
from threading import Event, RLock
from time import perf_counter
from typing import Callable, TypeVar

from champions_practice.belief_search import (
    ExactBeliefWorldState,
    _protect_chain_slots,
    search_exact_belief_turn,
    shortlist_belief_candidates,
)
from champions_practice.belief_worlds import (
    PublicSetPriorCatalog,
    materialize_public_belief_worlds,
    preview_choice_for_world,
)
from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.current_state_proposals import build_current_state_set_proposals
from champions_practice.present_rebase import build_present_rebase
from champions_practice.public_scaffold_bootstrap import bootstrap_public_current_scaffolds
from champions_practice.rolling_public_checkpoints import validate_public_bootstrap_checkpoint
from champions_practice.recommendations import FINAL_RNG_SEEDS, SCREENING_RNG_SEEDS
from champions_practice.recovery import RecoveryOpeningAuthority
from champions_practice.observation_beliefs import (
    BeliefParticle,
    ParticleUpdate,
    StructuralMismatchExample,
    compose_branch_member_lineage,
    condition_particles,
    identity_member_lineage,
    filter_choices_by_public_actions,
    merge_sampled_world_witnesses,
    observed_joint_move_candidates,
    public_observation_signature,
    public_opponent_actions_fully_observed,
    resample_particles_by_world,
)
from champions_practice.reachability import (
    finite_public_transition_reachability,
)


from champions_practice.search_worker import (
    FORCED_WAIT_CHOICE,
    HypotheticalSearchWorker,
    ShowdownRequestError,
    ShowdownSearchWorker,
    ShowdownWorkerTimeout,
)
from champions_practice.strategy import assess_strategic_position, generate_strategic_plans
from champions_practice.strategy_evidence import (
    ProtectedTacticalEvidence,
    filter_supported_plans,
    prepare_shared_strategic_responses,
    probe_strategic_plan,
    select_supported_plan,
)
from champions_practice.strategy_tactics import (
    choice_matches_guidance,
    guidance_from_plan,
)


FallbackSelector = Callable[[list[str]], str]
T = TypeVar("T")

_STATIC_RECOVERY_HISTORY_LIMIT = 512
_FINITE_FRONTIER_EXHAUSTED = "<finite-positive-frontier-exhausted>"


@dataclass(frozen=True)
class _RecoveryAuthorityObservation:
    ai_choice: str
    previous_public_view: dict
    public_view: dict



def _choice_repeats_protect(
    choice: str,
    protect_chain_slots: tuple[int, ...],
) -> bool:
    commands = [command.strip().split() for command in choice.split(",")]
    for slot in protect_chain_slots:
        index = slot - 1
        if index < 0 or index >= len(commands):
            continue
        tokens = commands[index]
        if len(tokens) >= 2 and tokens[0] == "move" and tokens[1] == "protect":
            return True
    return False


def _protect_risk_choices(
    search,
    protect_chain_slots: tuple[int, ...],
    *,
    alternative_limit: int = 2,
) -> tuple[str, ...]:
    chosen = search.chosen.choice
    if not _choice_repeats_protect(chosen, protect_chain_slots):
        return ()
    alternatives = [
        candidate.choice
        for candidate in search.ranking
        if not _choice_repeats_protect(candidate.choice, protect_chain_slots)
    ]
    if not alternatives:
        return ()
    return tuple([chosen, *alternatives[:alternative_limit]])




@dataclass(frozen=True)
class BeliefDecision:
    choice: str
    mode: str
    particle_count: int
    candidate_count: int
    branch_count: int
    elapsed_seconds: float
    fallback_reason: str | None = None
    strategic_plan: str | None = None
    strategic_probe_count: int = 0
    strategic_branch_count: int = 0
    strategic_rng_sample_count: int = 0
    worst_response: str | None = None
    worst_world_score: float | None = None
    weighted_score: float | None = None
    searched_responses: tuple[str, ...] = ()
    evaluated_choices: tuple[str, ...] = ()
    candidate_scores: tuple[tuple[str, float, float], ...] = ()
    own_speed_diagnostics: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class CollapseDifference:
    path: str
    actual: object
    simulated: object


@dataclass(frozen=True)
class CollapseBranchDiagnostic:
    world_id: str
    mismatch_count: int
    differences: tuple[CollapseDifference, ...]


@dataclass(frozen=True)
class CollapseWorldDiagnostic:
    world_id: str
    human_choice_legal: bool
    generated_branches: int
    closest_mismatch_count: int | None
    closest_paths: tuple[str, ...]


@dataclass(frozen=True)
class BeliefCollapseDiagnostic:
    summary: str
    elapsed_seconds: float
    budget_exhausted: bool
    generated_branches: int
    exact_matches: int
    worlds_tested: int
    legal_worlds: int
    illegal_worlds: int
    common_mismatch_paths: tuple[tuple[str, int], ...] = ()
    closest_branches: tuple[CollapseBranchDiagnostic, ...] = ()
    worlds: tuple[CollapseWorldDiagnostic, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class FiniteSeedCursorDiagnostic:
    path_sha256: str
    next_attempt: int


@dataclass(frozen=True)
class FiniteFrontierDiagnostic:
    world_id: str
    history_id: str
    human_choice: str
    token_sha256: str | None
    schema: str | None
    pending_paths: int
    materialization_jobs: int
    seed_cursors: tuple[FiniteSeedCursorDiagnostic, ...] = ()
    exhausted: bool = False
    parse_error: str | None = None


@dataclass(frozen=True)
class RecoveryRetryDiagnostic:
    pending_observations: int
    prefix_count_before: int
    prefix_count_after: int
    worker_attempts: int
    returned_updates: int
    deadline_timeouts: int
    finite_progress_callbacks: int
    finite_progress_changes: int
    seed_cursor_advanced: bool
    continuation_changed: bool
    continuation_persisted: bool
    elapsed_seconds: float
    frontiers_before: tuple[FiniteFrontierDiagnostic, ...] = ()
    frontiers_after: tuple[FiniteFrontierDiagnostic, ...] = ()


@dataclass(frozen=True)
class BeliefRecoveryDiagnostic:
    reason: str
    observation_turn: int
    observation_sha256: str
    observed_opponent_actions: tuple[str, ...]
    particles_before: int
    worlds_before: int
    generated_branches: int
    sampled_matches: int
    stochastic_only_mismatches: int
    structural_mismatches: int
    structural_mismatch_paths: tuple[tuple[str, int], ...]
    structural_mismatch_worlds: tuple[tuple[str, int], ...]
    structural_mismatch_examples: tuple[StructuralMismatchExample, ...]
    sampled_matched_worlds: int
    sampled_unresolved_worlds: int
    exhaustively_excluded_worlds: int
    recovery_candidates_remaining: int
    recovery_worlds_remaining: int
    finite_reachability_witnesses: int = 0
    finite_reachability_disproofs: int = 0
    finite_reachability_unresolved: int = 0
    finite_reachability_leaves: int = 0
    unsupported_public_evidence: tuple[str, ...] = ()
    recovery_retry: RecoveryRetryDiagnostic | None = None
    error: str | None = None


@dataclass(frozen=True)
class SealedDecisionReady:
    token: str


class SealedTurnState(str, Enum):
    NEW = "new"
    STARTING = "starting"
    PREVIEW = "preview"
    PREVIEW_SUBMITTING = "preview_submitting"
    IDLE = "idle"
    COMPUTING = "computing"
    LOCKED = "locked"
    SUBMITTING = "submitting"
    RESOLVED = "resolved"
    FAILED = "failed"
    UNKNOWN = "unknown"
    RESTART_REQUIRED = "restart_required"
    TERMINAL = "terminal"
    CLOSED = "closed"


@dataclass(frozen=True)
class SealedTurnResult:
    decision: BeliefDecision
    public_view: dict
    particles_before: int
    particles_after: int
    generated_branches: int
    matched_branches: int
    conditioning_seconds: float
    conditioning_over_budget: bool
    degraded: bool
    terminal: bool
    winner: str | None
    finite_reachability_witnesses: int = 0
    finite_reachability_disproofs: int = 0
    finite_reachability_unresolved: int = 0
    finite_reachability_leaves: int = 0
    collapse_diagnostic: BeliefCollapseDiagnostic | None = None
    recovery_diagnostic: BeliefRecoveryDiagnostic | None = None
    recovery_retry_diagnostic: RecoveryRetryDiagnostic | None = None


@dataclass(frozen=True)
class _EngineObservationSnapshot:
    last_public_view: dict | None
    particles: tuple[BeliefParticle, ...]
    pending_observations: tuple[
        tuple[str, dict[str, object] | None, dict],
        ...,
    ]
    pending_recovery_prefix_particles: tuple[BeliefParticle, ...]
    pending_recovery_prefix_count: int
    pending_recovery_witnesses: tuple[BeliefParticle, ...]
    pending_recovery_excluded_world_ids: tuple[str, ...]
    pending_recovery_witness_window: int
    pending_recovery_finite_frontiers: tuple[
        tuple[str, str, str, str],
        ...,
    ]
    recovery_authority_root_particles: tuple[BeliefParticle, ...]
    recovery_opening_authorities: tuple[RecoveryOpeningAuthority, ...]
    recovery_authority_root_public_view: dict | None
    recovery_authority_history: tuple[_RecoveryAuthorityObservation, ...]
    recovery_authority_history_complete: bool
    degraded: bool


@dataclass(frozen=True)
class BeliefTurnUpdate:
    decision: BeliefDecision
    public_view: dict
    particles_before: int
    particles_after: int
    generated_branches: int
    matched_branches: int
    conditioning_seconds: float
    conditioning_over_budget: bool
    degraded: bool
    finite_reachability_witnesses: int = 0
    finite_reachability_disproofs: int = 0
    finite_reachability_unresolved: int = 0
    finite_reachability_leaves: int = 0
    recovery_diagnostic: BeliefRecoveryDiagnostic | None = None
    recovery_retry_diagnostic: RecoveryRetryDiagnostic | None = None


def _particle_world_key(particle: BeliefParticle, index: int) -> str:
    return particle.world_id or particle.history_id or f"particle-{index}"


def _particle_world_keys(
    particles: tuple[BeliefParticle, ...],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                _particle_world_key(particle, index)
                for index, particle in enumerate(particles)
            }
        )
    )


def _particle_history_key(particle: BeliefParticle) -> str:
    if particle.history_id:
        return particle.history_id
    return hashlib.sha256(
        json.dumps(
            particle.state,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _has_resumable_finite_frontier(
    particles: tuple[BeliefParticle, ...],
    finite_continuations: dict[tuple[str, str, str], str] | None,
) -> bool:
    if not finite_continuations:
        return False
    particle_keys = {
        (
            _particle_world_key(particle, index),
            _particle_history_key(particle),
        )
        for index, particle in enumerate(particles)
    }
    return any(
        token != _FINITE_FRONTIER_EXHAUSTED
        and (world_id, history_id) in particle_keys
        for (world_id, history_id, _human_choice), token
        in finite_continuations.items()
    )


def _finite_frontier_diagnostics(
    frontiers: dict[tuple[str, str, str], str],
) -> tuple[FiniteFrontierDiagnostic, ...]:
    diagnostics: list[FiniteFrontierDiagnostic] = []
    for (world_id, history_id, human_choice), token in sorted(
        frontiers.items()
    ):
        if token == _FINITE_FRONTIER_EXHAUSTED:
            diagnostics.append(
                FiniteFrontierDiagnostic(
                    world_id=world_id,
                    history_id=history_id,
                    human_choice=human_choice,
                    token_sha256=None,
                    schema=None,
                    pending_paths=0,
                    materialization_jobs=0,
                    exhausted=True,
                )
            )
            continue

        token_sha256 = hashlib.sha256(token.encode("utf-8")).hexdigest()
        schema: str | None = None
        pending_paths = 0
        materialization_jobs = 0
        seed_cursors: list[FiniteSeedCursorDiagnostic] = []
        parse_error: str | None = None
        try:
            payload = json.loads(token)
            if not isinstance(payload, dict):
                raise ValueError("continuation payload is not an object")
            raw_schema = payload.get("schema")
            if isinstance(raw_schema, str):
                schema = raw_schema
            pending = payload.get("pending")
            if isinstance(pending, list):
                pending_paths = len(pending)
            materializations = payload.get("materializations")
            if isinstance(materializations, list):
                materialization_jobs = len(materializations)
                for materialization in materializations:
                    if not isinstance(materialization, dict):
                        continue
                    path = materialization.get("path")
                    next_attempt = materialization.get("next_attempt")
                    if (
                        not isinstance(path, list)
                        or isinstance(next_attempt, bool)
                        or not isinstance(next_attempt, int)
                        or next_attempt < 0
                    ):
                        continue
                    path_sha256 = hashlib.sha256(
                        json.dumps(
                            path,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()
                    seed_cursors.append(
                        FiniteSeedCursorDiagnostic(
                            path_sha256=path_sha256,
                            next_attempt=next_attempt,
                        )
                    )
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            parse_error = f"{type(error).__name__}: {error}"

        diagnostics.append(
            FiniteFrontierDiagnostic(
                world_id=world_id,
                history_id=history_id,
                human_choice=human_choice,
                token_sha256=token_sha256,
                schema=schema,
                pending_paths=pending_paths,
                materialization_jobs=materialization_jobs,
                seed_cursors=tuple(seed_cursors),
                parse_error=parse_error,
            )
        )
    return tuple(diagnostics)


def _finite_cursor_map(
    diagnostics: tuple[FiniteFrontierDiagnostic, ...],
) -> dict[tuple[str, str, str, str], int]:
    cursors: dict[tuple[str, str, str, str], int] = {}
    for frontier in diagnostics:
        for cursor in frontier.seed_cursors:
            cursors[
                (
                    frontier.world_id,
                    frontier.history_id,
                    frontier.human_choice,
                    cursor.path_sha256,
                )
            ] = cursor.next_attempt
    return cursors


def _finite_cursor_advanced(
    before: tuple[FiniteFrontierDiagnostic, ...],
    after: tuple[FiniteFrontierDiagnostic, ...],
) -> bool:
    before_cursors = _finite_cursor_map(before)
    after_cursors = _finite_cursor_map(after)
    return any(
        next_attempt > before_cursors.get(key, 0)
        for key, next_attempt in after_cursors.items()
    )


def _finite_frontier_changed(
    before: tuple[FiniteFrontierDiagnostic, ...],
    after: tuple[FiniteFrontierDiagnostic, ...],
) -> bool:
    def fingerprints(
        values: tuple[FiniteFrontierDiagnostic, ...],
    ) -> tuple[tuple[str, str, str, str | None, bool], ...]:
        return tuple(
            (
                value.world_id,
                value.history_id,
                value.human_choice,
                value.token_sha256,
                value.exhausted,
            )
            for value in values
        )

    return fingerprints(before) != fingerprints(after)


def _observation_action_strings(view: dict) -> tuple[str, ...]:
    raw = view.get("opponent_last_actions")
    if not isinstance(raw, list):
        return ()
    return tuple(
        json.dumps(value, sort_keys=True, separators=(",", ":"))
        for value in raw
        if isinstance(value, dict)
    )


def _recovery_diagnostic(
    *,
    reason: str,
    view: dict,
    particles_before: tuple[BeliefParticle, ...],
    update: ParticleUpdate | None,
    recovery_candidates: tuple[BeliefParticle, ...],
    recovery_retry: RecoveryRetryDiagnostic | None = None,
    error: str | None = None,
) -> BeliefRecoveryDiagnostic:
    signature = public_observation_signature(view)
    before_worlds = _particle_world_keys(particles_before)
    remaining_worlds = _particle_world_keys(recovery_candidates)
    return BeliefRecoveryDiagnostic(
        reason=reason,
        observation_turn=int(view.get("turn", 0)),
        observation_sha256=hashlib.sha256(signature.encode("utf-8")).hexdigest(),
        observed_opponent_actions=_observation_action_strings(view),
        particles_before=len(particles_before),
        worlds_before=len(before_worlds),
        generated_branches=update.generated if update is not None else 0,
        sampled_matches=update.matched if update is not None else 0,
        stochastic_only_mismatches=(
            update.stochastic_only_mismatches if update is not None else 0
        ),
        structural_mismatches=(
            update.structural_mismatches if update is not None else 0
        ),
        structural_mismatch_paths=(
            update.structural_mismatch_paths if update is not None else ()
        ),
        structural_mismatch_worlds=(
            update.structural_mismatch_worlds if update is not None else ()
        ),
        structural_mismatch_examples=(
            update.structural_mismatch_examples if update is not None else ()
        ),
        finite_reachability_witnesses=(
            update.finite_reachability_witnesses if update is not None else 0
        ),
        finite_reachability_disproofs=(
            update.finite_reachability_disproofs if update is not None else 0
        ),
        finite_reachability_unresolved=(
            update.finite_reachability_unresolved if update is not None else 0
        ),
        finite_reachability_leaves=(
            update.finite_reachability_leaves if update is not None else 0
        ),
        sampled_matched_worlds=(
            len(update.matched_world_ids) if update is not None else 0
        ),
        sampled_unresolved_worlds=(
            len(update.sampled_unresolved_world_ids)
            if update is not None
            else len(before_worlds)
        ),
        exhaustively_excluded_worlds=(
            len(update.exhaustively_excluded_world_ids)
            if update is not None
            else 0
        ),
        recovery_candidates_remaining=len(recovery_candidates),
        recovery_worlds_remaining=len(remaining_worlds),
        unsupported_public_evidence=(
            update.unsupported_public_evidence if update is not None else ()
        ),
        recovery_retry=recovery_retry,
        error=error,
    )


def _fallback_score(choice: str) -> tuple[int, int, str]:
    """Prefer conservative legal commands without hidden opponent information."""
    score = 0
    moves = 0
    for command in choice.split(","):
        tokens = command.strip().split()
        if not tokens:
            continue
        if tokens[0] == "move":
            moves += 1
            score += 4
            if len(tokens) > 1 and tokens[1] in {
                "protect",
                "detect",
                "followme",
                "wideguard",
                "trickroom",
                "imprison",
            }:
                score += 2
            if any(token.startswith("-") and token[1:].isdigit() for token in tokens[2:]):
                score -= 8
        elif tokens[0] == "switch":
            score += 1
    if choice.count("move protect") >= 2:
        score -= 2
    return score, moves, choice


def choose_public_fallback(choices: list[str]) -> str:
    if not choices:
        raise ValueError("fallback requires at least one legal choice")
    return max(choices, key=_fallback_score)


def _id(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _species_from_team_header(header: str) -> str:
    name = header.split(" @ ", 1)[0].strip()
    if name.endswith(" (M)") or name.endswith(" (F)"):
        name = name[:-4]
    if name.endswith(")") and " (" in name:
        return name.rsplit(" (", 1)[1][:-1]
    return name


def _pin_known_team_genders(team_text: str, request: dict) -> str:
    """Pin our publicly known own-side genders into hypothetical team text."""
    side = request.get("side")
    if not isinstance(side, dict):
        return team_text
    request_pokemon = side.get("pokemon")
    if not isinstance(request_pokemon, list):
        return team_text

    genders: dict[str, str] = {}
    for pokemon in request_pokemon:
        if not isinstance(pokemon, dict):
            continue
        details = pokemon.get("details")
        if not isinstance(details, str):
            continue
        tokens = [token.strip() for token in details.split(",")]
        if not tokens:
            continue
        species = tokens[0]
        gender = next((token for token in tokens[1:] if token in {"M", "F"}), None)
        if gender is not None:
            genders[_id(species)] = gender

    if not genders:
        return team_text

    sections = team_text.strip().split("\n\n")
    pinned: list[str] = []
    for section in sections:
        lines = section.splitlines()
        if not lines:
            continue
        species_id = _id(_species_from_team_header(lines[0]))
        gender = genders.get(species_id)
        if gender is not None:
            header = lines[0]
            if " @ " in header:
                identity, item = header.split(" @ ", 1)
                item_suffix = f" @ {item}"
            else:
                identity = header
                item_suffix = ""
            if identity.endswith(" (M)") or identity.endswith(" (F)"):
                identity = identity[:-4]
            lines[0] = f"{identity} ({gender}){item_suffix}"
        pinned.append("\n".join(lines))
    return "\n\n".join(pinned) + "\n"


def _value_at_path(root: object, path: str) -> object:
    current = root
    index = 1
    while index < len(path):
        char = path[index]
        if char == ".":
            index += 1
            start = index
            while index < len(path) and path[index] not in ".[":
                index += 1
            key = path[start:index]
            if not isinstance(current, dict):
                return "<not-dict>"
            current = current.get(key, "<missing>")
            continue
        if char == "[":
            end = path.find("]", index)
            if end < 0:
                return "<bad-path>"
            try:
                item_index = int(path[index + 1:end])
            except ValueError:
                return "<bad-index>"
            if not isinstance(current, list) or item_index >= len(current):
                return "<missing>"
            current = current[item_index]
            index = end + 1
            continue
        index += 1
    return current


def _public_diff_paths(left: object, right: object, path: str = "$") -> tuple[str, ...]:
    """Return a compact set of public-view paths whose values differ."""
    if type(left) is not type(right):
        return (path,)
    if isinstance(left, dict):
        paths: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}"
            if key not in left or key not in right:
                paths.append(child)
            else:
                paths.extend(_public_diff_paths(left[key], right[key], child))
            if len(paths) >= 12:
                break
        return tuple(paths[:12])
    if isinstance(left, list):
        if len(left) != len(right):
            return (f"{path}.length",)
        paths: list[str] = []
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
            paths.extend(_public_diff_paths(left_item, right_item, f"{path}[{index}]"))
            if len(paths) >= 12:
                break
        return tuple(paths[:12])
    return () if left == right else (path,)


def _normalized_public_observation(view: dict) -> object:
    return json.loads(public_observation_signature(view))


def _collapse_differences(
    actual: object,
    simulated: object,
) -> tuple[CollapseDifference, ...]:
    return tuple(
        CollapseDifference(
            path=path,
            actual=_value_at_path(actual, path),
            simulated=_value_at_path(simulated, path),
        )
        for path in _public_diff_paths(actual, simulated)
    )


def _hp_only_differences(
    differences: tuple[CollapseDifference, ...],
) -> bool:
    if not differences:
        return False
    return all(
        difference.path.endswith(".hp")
        or difference.path.endswith(".hp_percent")
        or difference.path.endswith(".condition")
        for difference in differences
    )


def _validate_decision_configuration(
    *,
    world_limit: int,
    particles_per_world: int,
    max_particles: int,
    candidate_limit: int,
    response_limit: int,
    strategic_plan_limit: int,
    strategic_candidate_limit: int,
    strategic_response_limit: int,
    strategic_rng_seeds: tuple[str, ...],
    decision_budget_seconds: float,
    conditioning_budget_seconds: float,
    collapse_debug_budget_seconds: float,
    rng_sample_batches: tuple[int, ...],
    recovery_rng_sample_batches: tuple[int, ...],
    observed_action_rng_multiplier: int,
) -> None:
    if world_limit <= 0:
        raise ValueError("world_limit must be positive")
    if particles_per_world <= 0:
        raise ValueError("particles_per_world must be positive")
    if max_particles <= 0:
        raise ValueError("max_particles must be positive")
    if candidate_limit <= 0 or response_limit <= 0:
        raise ValueError("search limits must be positive")
    if strategic_plan_limit <= 0:
        raise ValueError("strategic_plan_limit must be positive")
    if strategic_candidate_limit <= 0 or strategic_response_limit <= 0:
        raise ValueError("strategic probe limits must be positive")
    if not strategic_rng_seeds:
        raise ValueError("strategic_rng_seeds must not be empty")
    if decision_budget_seconds <= 0 or conditioning_budget_seconds <= 0:
        raise ValueError("budgets must be positive")
    if collapse_debug_budget_seconds <= 0:
        raise ValueError("collapse_debug_budget_seconds must be positive")
    if not rng_sample_batches or any(count <= 0 for count in rng_sample_batches):
        raise ValueError("rng_sample_batches must contain positive counts")
    if not recovery_rng_sample_batches or any(
        count <= 0 for count in recovery_rng_sample_batches
    ):
        raise ValueError("recovery_rng_sample_batches must contain positive counts")
    if observed_action_rng_multiplier <= 0:
        raise ValueError("observed_action_rng_multiplier must be positive")


class BeliefDecisionEngine:
    """Choose p2 actions from sanitized public views and hypothetical exact states.

    This engine owns no live-session worker or session identifier. Its inputs are the AI's
    public player view, the AI's currently legal live choices, and a restricted hypothetical
    worker capability that exposes no persistent-session operations.
    """

    def __init__(
        self,
        project_root,
        *,
        battle_format: str,
        ai_team: str,
        opponent_priors: PublicSetPriorCatalog,
        world_limit: int = 8,
        particles_per_world: int = 1,
        max_particles: int = 8,
        candidate_limit: int = 4,
        response_limit: int = 4,
        strategic_plan_limit: int = 2,
        strategic_candidate_limit: int = 3,
        strategic_response_limit: int = 2,
        strategic_rng_seeds: tuple[str, ...] = SCREENING_RNG_SEEDS,
        decision_budget_seconds: float = 8.0,
        conditioning_budget_seconds: float = 8.0,
        collapse_debug_budget_seconds: float = 15.0,
        rng_sample_batches: tuple[int, ...] = (2, 4),
        recovery_rng_sample_batches: tuple[int, ...] = (4, 8),
        observed_action_rng_multiplier: int = 16,
        particle_seed: int = 53,
        fallback_selector: FallbackSelector = choose_public_fallback,
    ):
        _validate_decision_configuration(
            world_limit=world_limit,
            particles_per_world=particles_per_world,
            max_particles=max_particles,
            candidate_limit=candidate_limit,
            response_limit=response_limit,
            strategic_plan_limit=strategic_plan_limit,
            strategic_candidate_limit=strategic_candidate_limit,
            strategic_response_limit=strategic_response_limit,
            strategic_rng_seeds=strategic_rng_seeds,
            decision_budget_seconds=decision_budget_seconds,
            conditioning_budget_seconds=conditioning_budget_seconds,
            collapse_debug_budget_seconds=collapse_debug_budget_seconds,
            rng_sample_batches=rng_sample_batches,
            recovery_rng_sample_batches=recovery_rng_sample_batches,
            observed_action_rng_multiplier=observed_action_rng_multiplier,
        )

        self.project_root = project_root
        self.battle_format = battle_format
        self.ai_team = ai_team
        self.opponent_priors = opponent_priors
        self.world_limit = world_limit
        self.particles_per_world = particles_per_world
        self.max_particles = max_particles
        self.candidate_limit = candidate_limit
        self.response_limit = response_limit
        self.strategic_plan_limit = strategic_plan_limit
        self.strategic_candidate_limit = strategic_candidate_limit
        self.strategic_response_limit = strategic_response_limit
        self.strategic_rng_seeds = strategic_rng_seeds
        self.decision_budget_seconds = decision_budget_seconds
        self.conditioning_budget_seconds = conditioning_budget_seconds
        self.collapse_debug_budget_seconds = collapse_debug_budget_seconds
        self.rng_sample_batches = rng_sample_batches
        self.recovery_rng_sample_batches = recovery_rng_sample_batches
        self.observed_action_rng_multiplier = observed_action_rng_multiplier
        self.fallback_selector = fallback_selector
        self._rng = random.Random(particle_seed)

        self.previews: dict[str, list[str]] | None = None
        # Fresh public-only rebasing never consumes stale recovery particles.
        self._public_ai_preview_choice: str | None = None
        self._public_rebase_attempted_signatures: set[str] = set()
        # Fresh per-decision worlds are disposable. Only the public ledger persists.
        self.last_public_world_failure_reason: str | None = None
        self.last_own_speed_diagnostics: tuple[dict[str, object], ...] = ()
        self.particles: tuple[BeliefParticle, ...] = ()
        self.last_public_view: dict | None = None
        # Shadow-only public evidence: never participates in live particle
        # admission, elimination, candidate search, or fallback selection.
        self.public_constraint_ledger: PublicConstraintLedger | None = None
        self.public_constraint_ledger_issue: str | None = None
        self.preview_mismatch_paths: tuple[str, ...] = ()
        self.preview_mismatch_values: tuple[tuple[str, object, object], ...] = ()
        self.pending_observations: list[
            tuple[str, dict[str, object] | None, dict]
        ] = []
        self.pending_recovery_prefix_particles: tuple[BeliefParticle, ...] = ()
        self.pending_recovery_prefix_count = 0
        self.pending_recovery_witnesses: tuple[BeliefParticle, ...] = ()
        self.pending_recovery_excluded_world_ids: tuple[str, ...] = ()
        self.pending_recovery_witness_window = 0
        self.pending_recovery_finite_frontiers: tuple[
            tuple[str, str, str, str],
            ...,
        ] = ()
        self.last_recovery_retry_diagnostic: RecoveryRetryDiagnostic | None = None
        self.recovery_authority_root_particles: tuple[BeliefParticle, ...] = ()
        self.recovery_opening_authorities: tuple[RecoveryOpeningAuthority, ...] = ()
        self.recovery_authority_root_public_view: dict | None = None
        self.recovery_authority_history: list[_RecoveryAuthorityObservation] = []
        self.recovery_authority_history_complete = True
        self.degraded = False

    def _particle_seed(self) -> str:
        values = [self._rng.getrandbits(32) for _ in range(4)]
        return "sodium," + "".join(f"{value:08x}" for value in values)

    def _record_public_constraints(self, view: dict, *, initialize: bool) -> None:
        """Shadow recording must NEVER interrupt authoritative live decisions.

        Producer/ledger contract differences quarantine the ledger and retain
        an explicit reason. Quarantined evidence is forbidden from future rebase
        admission; full validated history must be rebuilt or recording restarted
        with an explicit authority reset, never silently skipped.
        """
        if initialize:
            self.public_constraint_ledger = None
            self.public_constraint_ledger_issue = None
        elif self.public_constraint_ledger_issue is not None:
            return
        try:
            if self.public_constraint_ledger is None:
                self.public_constraint_ledger = PublicConstraintLedger.from_public_view(
                    view
                )
            else:
                self.public_constraint_ledger = self.public_constraint_ledger.advance(
                    view
                )
        except ValueError as error:
            self.public_constraint_ledger = None
            self.public_constraint_ledger_issue = str(error)

    def initialize_preview(
        self,
        *,
        view: dict,
        ai_choice: str,
    ) -> dict:
        """Initialize belief particles from the sanitized p2 post-preview view."""
        # Recording is independent of (and cannot veto) real battle authority.
        self._record_public_constraints(view, initialize=True)
        self.last_public_view = view
        self._public_ai_preview_choice = ai_choice
        self._public_rebase_attempted_signatures.clear()
        self.previews = {
            "p1": list(view["opponent"]["preview_species"]),
            "p2": [pokemon["species"] for pokemon in view["player"]["team"]],
        }

        belief = build_public_opponent_belief(view)
        particle_ai_team = _pin_known_team_genders(
            self.ai_team,
            view.get("request", {}),
        )
        worlds = materialize_public_belief_worlds(
            belief,
            self.opponent_priors,
            limit=self.world_limit,
        )
        wanted = public_observation_signature(view)
        particles: list[BeliefParticle] = []
        opening_by_lineage: dict[
            tuple[str, str],
            RecoveryOpeningAuthority,
        ] = {}

        with HypotheticalSearchWorker(self.project_root) as worker:
            for world_index, world in enumerate(worlds, 1):
                opponent_preview = preview_choice_for_world(belief, world)
                for rng_index in range(self.particles_per_world):
                    opening_seed = self._particle_seed()
                    opening = worker.create_state_with_opening_authority(
                        battle_format=self.battle_format,
                        p1_team=world.team_text,
                        p2_team=particle_ai_team,
                        p1_preview=opponent_preview,
                        p2_preview=ai_choice,
                        seed=opening_seed,
                    )
                    state = opening["state"]
                    particle_view = worker.state_view(
                        state=state,
                        side="p2",
                        previews=self.previews,
                    )
                    if public_observation_signature(particle_view) != wanted:
                        if not self.preview_mismatch_paths:
                            self.preview_mismatch_paths = _public_diff_paths(
                                view,
                                particle_view,
                            )
                            self.preview_mismatch_values = tuple(
                                (
                                    path,
                                    _value_at_path(view, path),
                                    _value_at_path(particle_view, path),
                                )
                                for path in self.preview_mismatch_paths
                            )
                        continue
                    world_id = f"world-{world_index}"
                    history_id = f"rng-{rng_index + 1}"
                    particle_weight = world.weight / self.particles_per_world
                    particles.append(
                        BeliefParticle(
                            state=state,
                            weight=particle_weight,
                            world_id=world_id,
                            history_id=history_id,
                            p1_member_lineage=identity_member_lineage(state, "p1"),
                            p2_member_lineage=identity_member_lineage(state, "p2"),
                        )
                    )
                    opening_by_lineage[(world_id, history_id)] = (
                        RecoveryOpeningAuthority(
                            world_id=world_id,
                            history_id=history_id,
                            battle_format=self.battle_format,
                            p1_team=world.team_text,
                            p2_team=particle_ai_team,
                            p1_name="Search P1",
                            p2_name="Search P2",
                            seed=opening_seed,
                            p1_preview_choice=opponent_preview,
                            p2_preview_choice=ai_choice,
                            p1_root_to_input=opening["preview_lineage"]["p1"],
                            p2_root_to_input=opening["preview_lineage"]["p2"],
                        )
                    )

        self.particles = resample_particles_by_world(
            tuple(particles),
            limit=self.max_particles,
            seed=53,
        )
        self.recovery_authority_root_particles = tuple(
            BeliefParticle(
                state=deepcopy(particle.state),
                weight=particle.weight,
                world_id=particle.world_id,
                history_id=particle.history_id,
                p1_member_lineage=particle.p1_member_lineage,
                p2_member_lineage=particle.p2_member_lineage,
            )
            for particle in self.particles
        )
        retained_opening_authorities: list[RecoveryOpeningAuthority] = []
        for particle in self.particles:
            key = (particle.world_id, particle.history_id)
            opening = opening_by_lineage.get(key)
            if opening is None:
                raise RuntimeError(
                    "retained belief particle lost pre-opening authority lineage"
                )
            retained_opening_authorities.append(opening)
        self.recovery_opening_authorities = tuple(retained_opening_authorities)
        self.recovery_authority_root_public_view = deepcopy(view)
        self.recovery_authority_history.clear()
        self.recovery_authority_history_complete = bool(self.particles)
        self.pending_recovery_prefix_particles = ()
        self.pending_recovery_prefix_count = 0
        self.pending_recovery_witnesses = ()
        self.pending_recovery_excluded_world_ids = ()
        self.pending_recovery_witness_window = 0
        self.pending_recovery_finite_frontiers = ()
        self.degraded = not bool(self.particles)
        return view

    def _run_until_deadline(
        self,
        operation: Callable[[HypotheticalSearchWorker], T],
        *,
        deadline: float,
        cleanup_reserve_seconds: float = 0.25,
    ) -> tuple[T | None, bool]:
        """Run startup, hypothetical work, and cleanup under one absolute deadline."""
        if perf_counter() >= deadline:
            return None, True

        cancelled = Event()
        holder: list[HypotheticalSearchWorker] = []
        holder_lock = RLock()

        def run_lifecycle() -> T | None:
            worker: HypotheticalSearchWorker | None = None
            try:
                worker = HypotheticalSearchWorker(
                    self.project_root,
                    startup_deadline=deadline,
                    request_timeout_seconds=max(
                        0.05,
                        deadline - perf_counter(),
                    ),
                )
                with holder_lock:
                    holder.append(worker)
                if cancelled.is_set() or perf_counter() >= deadline:
                    return None
                return operation(worker)
            finally:
                if worker is not None:
                    worker.abort(
                        timeout_seconds=max(
                            0.0,
                            min(
                                cleanup_reserve_seconds,
                                deadline - perf_counter(),
                            ),
                        )
                    )

        executor = ThreadPoolExecutor(max_workers=1)
        # Carry offline-only audit context into the bounded worker thread.
        # Normal calls retain their empty context and unchanged decisions.
        context = copy_context()
        future = executor.submit(context.run, run_lifecycle)
        timed_out = False
        result: T | None = None
        try:
            result = future.result(
                timeout=max(
                    0.0,
                    deadline - perf_counter() - cleanup_reserve_seconds,
                )
            )
        except (FutureTimeoutError, ShowdownWorkerTimeout):
            timed_out = True
        finally:
            if timed_out or perf_counter() >= deadline:
                cancelled.set()
                with holder_lock:
                    worker = holder[0] if holder else None
                if worker is not None:
                    worker.abort(
                        timeout_seconds=max(
                            0.0,
                            min(
                                cleanup_reserve_seconds,
                                deadline - perf_counter(),
                            ),
                        )
                    )
            executor.shutdown(wait=False, cancel_futures=True)

        if timed_out or perf_counter() > deadline:
            return None, True
        return result, False

    def _condition_finite_public_transition(
        self,
        worker: HypotheticalSearchWorker,
        *,
        particles: tuple[BeliefParticle, ...],
        ai_choice: str,
        view: dict,
        previous_view: dict[str, object] | None,
        preexcluded_worlds: set[str],
        deadline: float | None,
        max_leaves: int = 256,
        witness_rounds: int = 64,
        witness_seed_window: int = 0,
        finite_continuations: dict[
            tuple[str, str, str],
            str,
        ] | None = None,
        finite_progress_callback: Callable[
            [tuple[str, str, str], str | None, bool],
            None,
        ] | None = None,
    ) -> ParticleUpdate:
        """Recover public transitions with concrete Showdown witnesses first.

        Once every opponent action slot is public, positive reachability does not need
        exhaustive stochastic coverage: one concrete Showdown seed is a genuine
        sequential witness. Fresh searches examine those witnesses round-robin
        across worlds using the same deterministic seed stream as collapse
        diagnostics, and immediately replay any discovered seed across the other
        worlds. Recovery callers that already own a resumable finite frontier may
        set witness_rounds=0 so the saved systematic search gets the budget before
        another probabilistic witness window.

        Only worlds still unresolved after concrete witness search are eligible
        for finite-tree negative authority. A world may be excluded only when
        every retained particle and every public command candidate completes an
        exhaustive finite tree with no match. Any timeout, branch cap, unsupported
        RNG path, or other coverage gap remains unresolved.
        """
        public_move_candidates = observed_joint_move_candidates(
            view,
            previous_public_view=previous_view,
        )
        if not public_opponent_actions_fully_observed(
            view,
            previous_public_view=previous_view,
        ):
            return ParticleUpdate(
                (),
                generated=0,
                matched=0,
                deduplicated=0,
                sampled_unresolved_world_ids=_particle_world_keys(particles),
            )

        world_order: list[str] = []
        grouped: dict[str, list[BeliefParticle]] = {}
        for index, particle in enumerate(particles):
            world_id = _particle_world_key(particle, index)
            if world_id not in grouped:
                grouped[world_id] = []
                world_order.append(world_id)
            grouped[world_id].append(particle)

        excluded_worlds = set(preexcluded_worlds)
        witnesses: dict[str, BeliefParticle] = {}
        generated = 0
        finite_disproofs = 0
        finite_unresolved = 0
        finite_leaves = 0
        wanted = public_observation_signature(view)
        seed_basis = 0xC011A95E + int(view.get("turn", 0))
        if witness_seed_window:
            window_material = hashlib.sha256(
                f"{seed_basis}|window:{witness_seed_window}".encode("utf-8")
            ).digest()
            seed_basis = int.from_bytes(window_material[:8], "big")
        local_rng = random.Random(seed_basis)

        def next_seed() -> str:
            values = [local_rng.getrandbits(32) for _ in range(4)]
            return "sodium," + "".join(f"{value:08x}" for value in values)

        validated_cache: dict[
            tuple[str, str],
            tuple[tuple[str, ...], bool],
        ] = {}

        def validated_choices(
            world_id: str,
            particle: BeliefParticle,
        ) -> tuple[tuple[str, ...], bool]:
            key = (world_id, particle.history_id or str(id(particle)))
            cached = validated_cache.get(key)
            if cached is not None:
                return cached

            if public_move_candidates:
                validated = tuple(
                    worker.validate_choices(
                        state=particle.state,
                        side="p1",
                        candidates=list(public_move_candidates),
                    )
                )
                result = (validated, bool(validated))
                validated_cache[key] = result
                return result

            legal = tuple(
                worker.legal_choices(
                    state=particle.state,
                    side="p1",
                )
            )
            filtered = filter_choices_by_public_actions(
                legal,
                view,
                previous_public_view=previous_view,
                state=particle.state,
                side="p1",
                fail_open=False,
            )
            if filtered:
                result = (filtered, True)
            else:
                # A disguise or otherwise ambiguous species projection can make
                # a public switch impossible to map to one party index in this
                # particle. Searching every legal command is still safe for a
                # positive Showdown witness, but it cannot support exhaustive
                # negative authority for that world.
                result = (legal, False)
            validated_cache[key] = result
            return result

        def witness_from_result(
            *,
            world_id: str,
            particle: BeliefParticle,
            result: dict,
            seed: str,
        ) -> BeliefParticle | None:
            state = result.get("state")
            if not isinstance(state, dict):
                return None
            simulated_view = result.get("view")
            if not isinstance(simulated_view, dict):
                simulated_view = worker.state_view(
                    state=state,
                    side="p2",
                    previews=self.previews,
                )
            if public_observation_signature(simulated_view) != wanted:
                return None
            raw_lineage = result.get("member_lineage")
            p1_lineage, p2_lineage = compose_branch_member_lineage(
                particle,
                child_state=state,
                raw_lineage=raw_lineage,
            )
            witness_id = hashlib.sha256(
                (
                    world_id
                    + "|"
                    + seed
                    + "|"
                    + wanted
                ).encode("utf-8")
            ).hexdigest()
            return BeliefParticle(
                state=state,
                weight=particle.weight,
                world_id=world_id,
                history_id=(
                    f"{particle.history_id}|public-witness:sha256:{witness_id}"
                ).strip("|"),
                p1_member_lineage=p1_lineage,
                p2_member_lineage=p2_lineage,
            )

        def try_seed(world_id: str, seed: str) -> bool:
            nonlocal generated
            if world_id in witnesses or world_id in excluded_worlds:
                return world_id in witnesses
            for particle in grouped[world_id]:
                choices, _actions_exact = validated_choices(world_id, particle)
                if not choices:
                    continue
                branches = [
                    {
                        "p1_choice": human_choice,
                        "p2_choice": ai_choice,
                        "include_state": True,
                        "view_side": "p2",
                        "rng_seed": seed,
                        **(
                            {"previews": self.previews}
                            if self.previews is not None
                            else {}
                        ),
                    }
                    for human_choice in choices
                ]
                resolved = worker.branch_many(
                    state=particle.state,
                    branches=branches,
                )
                generated += len(resolved)
                for result in resolved:
                    witness = witness_from_result(
                        world_id=world_id,
                        particle=particle,
                        result=result,
                        seed=seed,
                    )
                    if witness is not None:
                        witnesses[world_id] = witness
                        return True
            return False

        # This reproduces the successful collapse-debug search but uses only the
        # channel-reconstructed public command. Two seeds per world keeps calls
        # small; a seed that witnesses one world is immediately replayed across
        # every other unresolved world before generating more randomness.
        rounds = 0
        while rounds < witness_rounds:
            unresolved = [
                world_id
                for world_id in world_order
                if world_id not in witnesses
                and world_id not in excluded_worlds
            ]
            if not unresolved:
                break
            if deadline is not None and perf_counter() >= deadline - 1.0:
                break

            discovered_seed: str | None = None
            for world_id in unresolved:
                for _ in range(2):
                    if deadline is not None and perf_counter() >= deadline - 1.0:
                        break
                    seed = next_seed()
                    if try_seed(world_id, seed):
                        discovered_seed = seed
                        break
                if discovered_seed is not None:
                    break

            if discovered_seed is not None:
                for world_id in world_order:
                    if world_id in witnesses or world_id in excluded_worlds:
                        continue
                    if deadline is not None and perf_counter() >= deadline - 1.0:
                        break
                    try_seed(world_id, discovered_seed)
            rounds += 1

        unresolved_worlds = {
            world_id
            for world_id in world_order
            if world_id not in witnesses
            and world_id not in excluded_worlds
        }

        # Use the finite tree only for unresolved worlds and keep the cap small
        # enough that production cannot spend tens of seconds inside one worker
        # call. Positive witnesses from this phase are still concrete-seed-bound
        # by finite_public_transition_reachability(); negative authority requires
        # exhaustive completion.
        if unresolved_worlds:
            for world_id in world_order:
                if world_id not in unresolved_worlds:
                    continue
                world_unresolved = False
                saw_conclusive_probe = False
                world_witness: BeliefParticle | None = None

                for particle in grouped[world_id]:
                    if deadline is not None and perf_counter() >= deadline - 0.75:
                        world_unresolved = True
                        break
                    choices, actions_exact = validated_choices(
                        world_id,
                        particle,
                    )
                    if not choices:
                        world_unresolved = True
                        continue
                    if not actions_exact:
                        world_unresolved = True
                        continue

                    particle_all_disproved = True
                    particle_key = _particle_history_key(particle)
                    for human_choice in choices:
                        if deadline is not None and perf_counter() >= deadline - 0.75:
                            world_unresolved = True
                            particle_all_disproved = False
                            break
                        progress_key = (
                            world_id,
                            particle_key,
                            human_choice,
                        )
                        continuation = (
                            finite_continuations.get(progress_key)
                            if finite_continuations is not None
                            else None
                        )
                        if continuation == _FINITE_FRONTIER_EXHAUSTED:
                            particle_all_disproved = False
                            world_unresolved = True
                            continue

                        probe = finite_public_transition_reachability(
                            worker,
                            state=particle.state,
                            side="p2",
                            p1_choice=human_choice,
                            p2_choice=ai_choice,
                            expected_public_view=view,
                            previews=self.previews,
                            max_leaves=max_leaves,
                            continuation_token=continuation,
                        )
                        finite_leaves += probe.leaves_examined
                        if probe.evidence.establishes_reachability:
                            if finite_progress_callback is not None:
                                finite_progress_callback(
                                    progress_key,
                                    None,
                                    False,
                                )
                            assert probe.child_state is not None
                            assert probe.member_lineage is not None
                            p1_lineage, p2_lineage = compose_branch_member_lineage(
                                particle,
                                child_state=probe.child_state,
                                raw_lineage=probe.member_lineage,
                            )
                            witness_id = probe.evidence.witness_ids[0]
                            world_witness = BeliefParticle(
                                state=probe.child_state,
                                weight=particle.weight,
                                world_id=particle.world_id,
                                history_id=(
                                    f"{particle.history_id}|finite:{witness_id}"
                                ).strip("|"),
                                p1_member_lineage=p1_lineage,
                                p2_member_lineage=p2_lineage,
                            )
                            saw_conclusive_probe = True
                            break
                        if probe.evidence.establishes_impossibility:
                            if continuation is not None:
                                raise RuntimeError(
                                    "resumed finite search produced negative authority"
                                )
                            if finite_progress_callback is not None:
                                finite_progress_callback(
                                    progress_key,
                                    None,
                                    False,
                                )
                            saw_conclusive_probe = True
                            continue
                        if finite_progress_callback is not None:
                            if probe.continuation_token is not None:
                                finite_progress_callback(
                                    progress_key,
                                    probe.continuation_token,
                                    False,
                                )
                            elif probe.positive_frontier_exhausted:
                                finite_progress_callback(
                                    progress_key,
                                    None,
                                    True,
                                )
                        particle_all_disproved = False
                        world_unresolved = True

                    if world_witness is not None:
                        break
                    if not particle_all_disproved:
                        world_unresolved = True

                if world_witness is not None:
                    witnesses[world_id] = world_witness
                    unresolved_worlds.discard(world_id)
                    continue
                if saw_conclusive_probe and not world_unresolved:
                    excluded_worlds.add(world_id)
                    unresolved_worlds.discard(world_id)
                    finite_disproofs += 1
                else:
                    finite_unresolved += 1

        authoritative_particles = tuple(
            particle
            for index, particle in enumerate(particles)
            if _particle_world_key(particle, index) not in excluded_worlds
        )
        if (
            authoritative_particles
            and not unresolved_worlds
            and set(witnesses)
            == {
                _particle_world_key(particle, index)
                for index, particle in enumerate(authoritative_particles)
            }
        ):
            merged = merge_sampled_world_witnesses(
                authoritative_particles,
                tuple(witnesses.values()),
            )
            if merged:
                return ParticleUpdate(
                    particles=merged,
                    generated=generated + finite_leaves,
                    matched=len(witnesses),
                    deduplicated=0,
                    matched_world_ids=tuple(sorted(witnesses)),
                    sampled_unresolved_world_ids=(),
                    exhaustively_excluded_world_ids=tuple(
                        sorted(excluded_worlds)
                    ),
                    finite_reachability_witnesses=len(witnesses),
                    finite_reachability_disproofs=finite_disproofs,
                    finite_reachability_unresolved=0,
                    finite_reachability_leaves=finite_leaves,
                )

        return ParticleUpdate(
            (),
            generated=generated + finite_leaves,
            matched=len(witnesses),
            deduplicated=0,
            matched_world_ids=tuple(sorted(witnesses)),
            sampled_unresolved_world_ids=tuple(sorted(unresolved_worlds)),
            exhaustively_excluded_world_ids=tuple(sorted(excluded_worlds)),
            finite_reachability_witnesses=len(witnesses),
            finite_reachability_disproofs=finite_disproofs,
            finite_reachability_unresolved=max(
                finite_unresolved,
                len(unresolved_worlds),
            ),
            finite_reachability_leaves=finite_leaves,
        )

    def _condition_adaptive(
        self,
        worker: HypotheticalSearchWorker,
        *,
        particles: tuple[BeliefParticle, ...],
        ai_choice: str,
        view: dict,
        previous_view: dict[str, object] | None = None,
        batches: tuple[int, ...],
        deadline: float | None = None,
        witness_seed_window: int = 0,
        progress_callback: Callable[
            [tuple[BeliefParticle, ...], tuple[str, ...]],
            None,
        ] | None = None,
        finite_continuations: dict[
            tuple[str, str, str],
            str,
        ] | None = None,
        finite_progress_callback: Callable[
            [tuple[str, str, str], str | None, bool],
            None,
        ] | None = None,
    ) -> ParticleUpdate:
        generated = 0
        matched = 0
        deduplicated = 0
        stochastic_only_mismatches = 0
        structural_mismatches = 0
        structural_mismatch_paths: Counter[str] = Counter()
        structural_mismatch_worlds: Counter[str] = Counter()
        structural_mismatch_examples: list[StructuralMismatchExample] = []
        structural_example_keys: set[tuple[str, str]] = set()
        required_worlds = set(_particle_world_keys(particles))
        sampled_matched_worlds: set[str] = set()
        witnessed_particles: list[BeliefParticle] = []
        exhaustive_exclusions: set[str] = set()
        unsupported_public_evidence: set[str] = set()
        finite_public_actions = public_opponent_actions_fully_observed(
            view,
            previous_public_view=previous_view,
        )
        multiplier = (
            self.observed_action_rng_multiplier
            if finite_public_actions
            else 1
        )
        resume_finite_first = (
            finite_public_actions
            and _has_resumable_finite_frontier(
                particles,
                finite_continuations,
            )
        )

        def report_progress(update: ParticleUpdate) -> None:
            if progress_callback is None:
                return
            if not update.particles and not update.exhaustively_excluded_world_ids:
                return
            progress_callback(
                tuple(update.particles),
                tuple(update.exhaustively_excluded_world_ids),
            )

        def aggregate_diagnostics(update: ParticleUpdate) -> None:
            structural_mismatch_paths.update(
                dict(update.structural_mismatch_paths)
            )
            structural_mismatch_worlds.update(
                dict(update.structural_mismatch_worlds)
            )
            for example in update.structural_mismatch_examples:
                key = (example.world_id, example.path)
                if key in structural_example_keys:
                    continue
                structural_example_keys.add(key)
                if len(structural_mismatch_examples) < 8:
                    structural_mismatch_examples.append(example)

        def update_kwargs() -> dict:
            return {
                "structural_mismatch_paths": tuple(
                    sorted(
                        structural_mismatch_paths.items(),
                        key=lambda item: (-item[1], item[0]),
                    )[:16]
                ),
                "structural_mismatch_worlds": tuple(
                    sorted(
                        structural_mismatch_worlds.items(),
                        key=lambda item: (-item[1], item[0]),
                    )[:16]
                ),
                "structural_mismatch_examples": tuple(
                    structural_mismatch_examples
                ),
            }

        # A sampled witness may advance a hypothesis; a sampled miss may not
        # eliminate one. Fresh observations draw bounded chunks until every
        # still-authoritative starting world has a witness. Once recovery has a
        # live finite continuation for these particles, skip this probabilistic
        # prepass and spend the retry budget advancing that saved frontier.
        # Structural diagnostics accumulate across fresh sampled batches so a
        # collapse explains itself rather than reporting only a count.
        sampling_batches = () if resume_finite_first else batches
        for sample_count in sampling_batches:
            for sample_index in range(multiplier):
                unresolved = (
                    required_worlds
                    - sampled_matched_worlds
                    - exhaustive_exclusions
                )
                if not unresolved:
                    break
                if (
                    deadline is not None
                    and perf_counter() >= deadline - 0.5
                ):
                    return ParticleUpdate(
                        (),
                        generated,
                        matched,
                        deduplicated,
                        stochastic_only_mismatches,
                        structural_mismatches,
                        matched_world_ids=tuple(sorted(sampled_matched_worlds)),
                        sampled_unresolved_world_ids=tuple(sorted(unresolved)),
                        exhaustively_excluded_world_ids=tuple(
                            sorted(exhaustive_exclusions)
                        ),
                        unsupported_public_evidence=tuple(
                            sorted(unsupported_public_evidence)
                        ),
                        **update_kwargs(),
                    )

                seeds = tuple(
                    self._particle_seed() for _ in range(sample_count)
                )
                # Ordinary sampling must get its full cheap attempt before
                # triggering expensive 16-way damage replay. Reserve at most
                # one optional positive-witness probe for the last multiplier
                # pass, and only when there is budget and zero sampled worlds.
                # The remaining cases continue through existing finite recovery.
                damage_probe_limit = int(
                    finite_public_actions
                    and sample_index == multiplier - 1
                    and not sampled_matched_worlds
                    and (
                        deadline is None
                        or perf_counter() < deadline - 2.0
                    )
                )
                update = condition_particles(
                    worker,
                    particles=particles,
                    ai_side="p2",
                    ai_choice=ai_choice,
                    actual_public_view=view,
                    previous_public_view=previous_view,
                    rng_seeds=seeds,
                    previews=self.previews,
                    damage_probe_limit=damage_probe_limit,
                )
                generated += update.generated
                matched += update.matched
                deduplicated += update.deduplicated
                stochastic_only_mismatches += update.stochastic_only_mismatches
                structural_mismatches += update.structural_mismatches
                aggregate_diagnostics(update)
                report_progress(update)
                update_matched_worlds = set(update.matched_world_ids)
                if not update_matched_worlds and update.particles:
                    update_matched_worlds = set(
                        _particle_world_keys(update.particles)
                    )
                sampled_matched_worlds.update(update_matched_worlds)
                witnessed_particles.extend(update.particles)
                exhaustive_exclusions.update(
                    update.exhaustively_excluded_world_ids
                )
                unsupported_public_evidence.update(
                    update.unsupported_public_evidence
                )

                installable_worlds = required_worlds - exhaustive_exclusions
                if installable_worlds.issubset(sampled_matched_worlds):
                    authoritative_particles = tuple(
                        particle
                        for index, particle in enumerate(particles)
                        if _particle_world_key(particle, index)
                        not in exhaustive_exclusions
                    )
                    merged = merge_sampled_world_witnesses(
                        authoritative_particles,
                        tuple(witnessed_particles),
                    )
                    if merged:
                        return ParticleUpdate(
                            particles=merged,
                            generated=generated,
                            matched=matched,
                            deduplicated=deduplicated,
                            stochastic_only_mismatches=stochastic_only_mismatches,
                            structural_mismatches=structural_mismatches,
                            matched_world_ids=tuple(
                                sorted(sampled_matched_worlds)
                            ),
                            sampled_unresolved_world_ids=(),
                            exhaustively_excluded_world_ids=tuple(
                                sorted(exhaustive_exclusions)
                            ),
                            unsupported_public_evidence=tuple(
                                sorted(unsupported_public_evidence)
                            ),
                            **update_kwargs(),
                        )

            # Once a complete public joint command is available, a full sampled
            # pass with zero world witnesses has already served its screening
            # purpose. Do not spend the remaining conditioning budget repeating
            # the same probabilistic miss; reserve it for finite Showdown
            # reachability below. Partial sampled coverage still gets later
            # batches because those witnesses can cheaply complete the posterior.
            if (
                finite_public_actions
                and not sampled_matched_worlds
                and structural_mismatches > 0
                and not unsupported_public_evidence
            ):
                break

        unresolved = required_worlds - sampled_matched_worlds - exhaustive_exclusions

        if (
            unresolved
            and finite_public_actions
            and not sampled_matched_worlds
            and not unsupported_public_evidence
            and (deadline is None or perf_counter() < deadline - 0.5)
        ):
            finite_source_particles = tuple(
                particle
                for index, particle in enumerate(particles)
                if _particle_world_key(particle, index) in unresolved
            )
            finite = self._condition_finite_public_transition(
                worker,
                particles=finite_source_particles,
                ai_choice=ai_choice,
                view=view,
                previous_view=previous_view,
                preexcluded_worlds=set(),
                deadline=deadline,
                witness_seed_window=witness_seed_window,
                witness_rounds=0 if resume_finite_first else 64,
                finite_continuations=finite_continuations,
                finite_progress_callback=finite_progress_callback,
            )
            report_progress(finite)
            exhaustive_exclusions.update(
                finite.exhaustively_excluded_world_ids
            )
            finite_matched_worlds = set(finite.matched_world_ids)
            combined_matched_worlds = (
                sampled_matched_worlds | finite_matched_worlds
            )
            installable_worlds = required_worlds - exhaustive_exclusions

            if (
                finite.particles
                and installable_worlds.issubset(combined_matched_worlds)
            ):
                authoritative_particles = tuple(
                    particle
                    for index, particle in enumerate(particles)
                    if _particle_world_key(particle, index)
                    not in exhaustive_exclusions
                )
                merged = merge_sampled_world_witnesses(
                    authoritative_particles,
                    (
                        *tuple(witnessed_particles),
                        *finite.particles,
                    ),
                )
                if merged:
                    return ParticleUpdate(
                        particles=merged,
                        generated=generated + finite.generated,
                        matched=matched + finite.matched,
                        deduplicated=deduplicated + finite.deduplicated,
                        stochastic_only_mismatches=stochastic_only_mismatches,
                        structural_mismatches=structural_mismatches,
                        matched_world_ids=tuple(
                            sorted(combined_matched_worlds)
                        ),
                        sampled_unresolved_world_ids=(),
                        exhaustively_excluded_world_ids=tuple(
                            sorted(exhaustive_exclusions)
                        ),
                        unsupported_public_evidence=tuple(
                            sorted(unsupported_public_evidence)
                        ),
                        finite_reachability_witnesses=(
                            finite.finite_reachability_witnesses
                        ),
                        finite_reachability_disproofs=(
                            finite.finite_reachability_disproofs
                        ),
                        finite_reachability_unresolved=0,
                        finite_reachability_leaves=(
                            finite.finite_reachability_leaves
                        ),
                        **update_kwargs(),
                    )

            unresolved = (
                required_worlds
                - combined_matched_worlds
                - exhaustive_exclusions
            )
            return ParticleUpdate(
                (),
                generated + finite.generated,
                matched + finite.matched,
                deduplicated + finite.deduplicated,
                stochastic_only_mismatches,
                structural_mismatches,
                matched_world_ids=tuple(
                    sorted(combined_matched_worlds)
                ),
                sampled_unresolved_world_ids=tuple(sorted(unresolved)),
                exhaustively_excluded_world_ids=tuple(
                    sorted(exhaustive_exclusions)
                ),
                unsupported_public_evidence=tuple(
                    sorted(unsupported_public_evidence)
                ),
                finite_reachability_witnesses=(
                    finite.finite_reachability_witnesses
                ),
                finite_reachability_disproofs=(
                    finite.finite_reachability_disproofs
                ),
                finite_reachability_unresolved=(
                    finite.finite_reachability_unresolved
                ),
                finite_reachability_leaves=(
                    finite.finite_reachability_leaves
                ),
                **update_kwargs(),
            )

        return ParticleUpdate(
            (),
            generated,
            matched,
            deduplicated,
            stochastic_only_mismatches,
            structural_mismatches,
            matched_world_ids=tuple(sorted(sampled_matched_worlds)),
            sampled_unresolved_world_ids=tuple(sorted(unresolved)),
            exhaustively_excluded_world_ids=tuple(sorted(exhaustive_exclusions)),
            unsupported_public_evidence=tuple(sorted(unsupported_public_evidence)),
            **update_kwargs(),
        )

    def _record_recovery_authority_observation(
        self,
        *,
        ai_choice: str,
        previous_view: dict[str, object] | None,
        view: dict,
    ) -> None:
        if not self.recovery_authority_history_complete:
            return
        if (
            not isinstance(previous_view, dict)
            or self.recovery_authority_root_public_view is None
        ):
            self.recovery_authority_history_complete = False
            self.recovery_authority_history.clear()
            return
        if len(self.recovery_authority_history) >= _STATIC_RECOVERY_HISTORY_LIMIT:
            self.recovery_authority_history_complete = False
            self.recovery_authority_history.clear()
            return
        self.recovery_authority_history.append(
            _RecoveryAuthorityObservation(
                ai_choice=ai_choice,
                previous_public_view=deepcopy(previous_view),
                public_view=deepcopy(view),
            )
        )

    def _promote_pending_to_recovery_authority(
        self,
        pending: tuple[
            tuple[str, dict[str, object] | None, dict],
            ...,
        ],
    ) -> None:
        for ai_choice, previous_view, view in pending:
            self._record_recovery_authority_observation(
                ai_choice=ai_choice,
                previous_view=previous_view,
                view=view,
            )

    def _discard_decision_hypotheses(self) -> None:
        """Discard simulator hypotheses, NEVER the independent public ledger.

        This is not collapse recovery. A new search decision will sample fresh
        possible worlds from its own current public checkpoint. No old battle
        trajectory, RNG seed, particle identity, or queued history is retained.
        """
        self.particles = ()
        self.pending_observations.clear()
        self._clear_pending_recovery_progress()
        self.recovery_authority_root_particles = ()
        self.recovery_opening_authorities = ()
        self.recovery_authority_root_public_view = None
        self.recovery_authority_history.clear()
        self.recovery_authority_history_complete = False

    def _clear_pending_recovery_progress(self) -> None:
        self.pending_recovery_prefix_particles = ()
        self.pending_recovery_prefix_count = 0
        self.pending_recovery_witnesses = ()
        self.pending_recovery_excluded_world_ids = ()
        self.pending_recovery_witness_window = 0
        self.pending_recovery_finite_frontiers = ()

    def _retry_pending_with_more_rng(
        self,
        *,
        deadline: float | None = None,
    ) -> bool:
        """Resume public-only recovery without discarding proven prefix work.

        Recovery progress has three layers:

        * a completed prefix of pending observations, represented by exact
          Showdown-produced particles after that prefix;
        * concrete witnesses / exhaustive exclusions already established for
          the next pending observation; and
        * positive-only finite stochastic frontiers that can resume witness
          search without granting partial traversal negative authority.

        Neither a sampled miss nor a timeout creates exclusion authority. A
        later retry spends its budget only on unresolved worlds, unfinished
        finite witness frontiers, and observations after the completed prefix.
        """
        retry_started = perf_counter()
        self.last_recovery_retry_diagnostic = None
        if not self.pending_observations:
            self._clear_pending_recovery_progress()
            return bool(self.particles)

        pending = tuple(self.pending_observations)
        if (
            self.pending_recovery_prefix_count < 0
            or self.pending_recovery_prefix_count > len(pending)
            or (
                self.pending_recovery_prefix_count > 0
                and not self.pending_recovery_prefix_particles
            )
        ):
            self._clear_pending_recovery_progress()

        prefix_count = self.pending_recovery_prefix_count
        prefix_particles = (
            self.pending_recovery_prefix_particles
            if self.pending_recovery_prefix_particles
            else self.particles
        )
        recovery_deadline = perf_counter() + self.conditioning_budget_seconds
        if deadline is not None:
            recovery_deadline = min(recovery_deadline, deadline)

        progress_lock = RLock()
        witness_cache: dict[tuple[str, str], BeliefParticle] = {}
        excluded_worlds = set(self.pending_recovery_excluded_world_ids)
        finite_frontier_cache: dict[
            tuple[str, str, str],
            str,
        ] = {
            (world_id, history_id, human_choice): token
            for world_id, history_id, human_choice, token
            in self.pending_recovery_finite_frontiers
        }
        retry_prefix_count_before = prefix_count
        frontier_tokens_before = dict(finite_frontier_cache)
        worker_attempts = 0
        returned_updates = 0
        deadline_timeouts = 0
        finite_progress_callbacks = 0
        finite_progress_changes = 0

        def witness_key(particle: BeliefParticle) -> tuple[str, str]:
            return particle.world_id, _particle_history_key(particle)

        for particle in self.pending_recovery_witnesses:
            witness_cache[witness_key(particle)] = particle

        def record_progress(
            witnesses: tuple[BeliefParticle, ...],
            exclusions: tuple[str, ...],
        ) -> None:
            with progress_lock:
                for particle in witnesses:
                    witness_cache.setdefault(witness_key(particle), particle)
                excluded_worlds.update(exclusions)

        def record_finite_progress(
            key: tuple[str, str, str],
            continuation: str | None,
            exhausted: bool,
        ) -> None:
            nonlocal finite_progress_callbacks, finite_progress_changes
            with progress_lock:
                finite_progress_callbacks += 1
                previous = finite_frontier_cache.get(key)
                if exhausted:
                    updated = _FINITE_FRONTIER_EXHAUSTED
                    finite_frontier_cache[key] = updated
                elif continuation is None:
                    updated = None
                    finite_frontier_cache.pop(key, None)
                else:
                    updated = continuation
                    finite_frontier_cache[key] = updated
                if previous != updated:
                    finite_progress_changes += 1

        def snapshot_progress() -> tuple[
            tuple[BeliefParticle, ...],
            tuple[str, ...],
        ]:
            with progress_lock:
                return (
                    tuple(witness_cache.values()),
                    tuple(sorted(excluded_worlds)),
                )

        def snapshot_finite_frontiers() -> dict[
            tuple[str, str, str],
            str,
        ]:
            with progress_lock:
                return dict(finite_frontier_cache)

        def save_progress() -> None:
            witnesses, exclusions = snapshot_progress()
            finite_frontiers = snapshot_finite_frontiers()
            self.pending_recovery_prefix_particles = prefix_particles
            self.pending_recovery_prefix_count = prefix_count
            self.pending_recovery_witnesses = witnesses
            self.pending_recovery_excluded_world_ids = exclusions
            self.pending_recovery_finite_frontiers = tuple(
                (*key, token)
                for key, token in sorted(finite_frontiers.items())
            )

        def finalize_retry(completed: bool) -> bool:
            persisted = {
                (world_id, history_id, human_choice): token
                for world_id, history_id, human_choice, token
                in self.pending_recovery_finite_frontiers
            }
            frontiers_before = _finite_frontier_diagnostics(
                frontier_tokens_before
            )
            frontiers_after = _finite_frontier_diagnostics(persisted)
            self.last_recovery_retry_diagnostic = RecoveryRetryDiagnostic(
                pending_observations=len(pending),
                prefix_count_before=retry_prefix_count_before,
                prefix_count_after=self.pending_recovery_prefix_count,
                worker_attempts=worker_attempts,
                returned_updates=returned_updates,
                deadline_timeouts=deadline_timeouts,
                finite_progress_callbacks=finite_progress_callbacks,
                finite_progress_changes=finite_progress_changes,
                seed_cursor_advanced=_finite_cursor_advanced(
                    frontiers_before,
                    frontiers_after,
                ),
                continuation_changed=_finite_frontier_changed(
                    frontiers_before,
                    frontiers_after,
                ),
                continuation_persisted=any(
                    token != _FINITE_FRONTIER_EXHAUSTED
                    for token in persisted.values()
                ),
                elapsed_seconds=perf_counter() - retry_started,
                frontiers_before=frontiers_before,
                frontiers_after=frontiers_after,
            )
            return completed

        while prefix_count < len(pending):
            if perf_counter() >= recovery_deadline - 0.5:
                save_progress()
                return finalize_retry(False)

            ai_choice, previous_view, view = pending[prefix_count]
            required_worlds = set(_particle_world_keys(prefix_particles))
            witnesses, exclusions = snapshot_progress()
            excluded_worlds_now = set(exclusions)
            witnessed_worlds = set(_particle_world_keys(witnesses))
            installable_worlds = required_worlds - excluded_worlds_now

            def complete_current_observation() -> bool:
                nonlocal prefix_count, prefix_particles
                witnesses_now, exclusions_now = snapshot_progress()
                exclusions_set = set(exclusions_now)
                installable = required_worlds - exclusions_set
                witnessed = set(_particle_world_keys(witnesses_now))
                if not installable or not installable.issubset(witnessed):
                    return False

                authoritative_particles = tuple(
                    particle
                    for index, particle in enumerate(prefix_particles)
                    if _particle_world_key(particle, index) not in exclusions_set
                )
                merged = merge_sampled_world_witnesses(
                    authoritative_particles,
                    witnesses_now,
                )
                if not merged:
                    return False

                prefix_particles = resample_particles_by_world(
                    merged,
                    limit=self.max_particles,
                    seed=int(view.get("turn", 0)) + 155,
                )
                prefix_count += 1
                with progress_lock:
                    witness_cache.clear()
                    excluded_worlds.clear()
                    finite_frontier_cache.clear()
                self.pending_recovery_prefix_particles = prefix_particles
                self.pending_recovery_prefix_count = prefix_count
                self.pending_recovery_witnesses = ()
                self.pending_recovery_excluded_world_ids = ()
                self.pending_recovery_witness_window = 0
                self.pending_recovery_finite_frontiers = ()
                return True

            if (
                installable_worlds
                and installable_worlds.issubset(witnessed_worlds)
                and complete_current_observation()
            ):
                continue

            unresolved_worlds = installable_worlds - witnessed_worlds
            attempt_particles = tuple(
                particle
                for index, particle in enumerate(prefix_particles)
                if _particle_world_key(particle, index) in unresolved_worlds
            )
            if not attempt_particles:
                save_progress()
                return finalize_retry(False)

            finite_snapshot = snapshot_finite_frontiers()
            resume_finite_first = _has_resumable_finite_frontier(
                attempt_particles,
                finite_snapshot,
            )
            witness_seed_window = self.pending_recovery_witness_window
            # Search scheduling only: advancing this cursor never excludes a
            # world or changes belief mass. If a live finite frontier already
            # exists, preserve the concrete-seed window for a future retry and
            # spend this budget advancing the systematic finite search instead.
            if not resume_finite_first:
                self.pending_recovery_witness_window += 1

            def recover_one(worker: HypotheticalSearchWorker) -> ParticleUpdate:
                return self._condition_adaptive(
                    worker,
                    particles=attempt_particles,
                    ai_choice=ai_choice,
                    view=view,
                    previous_view=previous_view,
                    batches=self.recovery_rng_sample_batches,
                    deadline=recovery_deadline,
                    witness_seed_window=witness_seed_window,
                    progress_callback=record_progress,
                    finite_continuations=finite_snapshot,
                    finite_progress_callback=record_finite_progress,
                )

            worker_attempts += 1
            update, timed_out = self._run_until_deadline(
                recover_one,
                deadline=recovery_deadline,
            )
            if timed_out:
                deadline_timeouts += 1
            if update is not None:
                returned_updates += 1
                record_progress(
                    tuple(update.particles),
                    tuple(update.exhaustively_excluded_world_ids),
                )

            if complete_current_observation():
                continue

            save_progress()
            if timed_out or update is None or not update.particles:
                return finalize_retry(False)

            # A nonempty update that did not complete the current observation
            # is still only positive progress. Keep it cached and retry later.
            return finalize_retry(False)

        self.particles = prefix_particles
        self._promote_pending_to_recovery_authority(pending)
        self.pending_observations.clear()
        self._clear_pending_recovery_progress()
        self.degraded = False
        return finalize_retry(True)

    def diagnose_collapse(
        self,
        *,
        particles: tuple[BeliefParticle, ...],
        ai_choice: str,
        resolved_opponent_choice: str,
        previous_view: dict | None,
        view: dict,
    ) -> BeliefCollapseDiagnostic:
        """Explain a zero-match posterior without changing the live belief state."""
        started = perf_counter()
        deadline = started + self.collapse_debug_budget_seconds
        actual = _normalized_public_observation(view)
        local_rng = random.Random(0xC011A95E + int(view.get("turn", 0)))
        path_counts: dict[str, int] = {}
        per_world: dict[str, dict[str, object]] = {}
        closest: list[CollapseBranchDiagnostic] = []
        exact_matches = 0
        generated = 0

        def next_seed() -> str:
            values = [local_rng.getrandbits(32) for _ in range(4)]
            return "sodium," + "".join(f"{value:08x}" for value in values)

        def build_diagnostic(
            *,
            summary: str,
            budget_exhausted: bool,
            error: str | None = None,
        ) -> BeliefCollapseDiagnostic:
            worlds = tuple(
                CollapseWorldDiagnostic(
                    world_id=world_id,
                    human_choice_legal=bool(stats["legal"]),
                    generated_branches=int(stats["generated"]),
                    closest_mismatch_count=(
                        int(stats["closest_count"])
                        if stats["closest_count"] is not None
                        else None
                    ),
                    closest_paths=tuple(stats["closest_paths"]),
                )
                for world_id, stats in sorted(per_world.items())
            )
            legal_worlds = sum(1 for world in worlds if world.human_choice_legal)
            return BeliefCollapseDiagnostic(
                summary=summary,
                elapsed_seconds=perf_counter() - started,
                budget_exhausted=budget_exhausted,
                generated_branches=generated,
                exact_matches=exact_matches,
                worlds_tested=len(worlds) if worlds else len(particles),
                legal_worlds=legal_worlds,
                illegal_worlds=(len(worlds) - legal_worlds) if worlds else 0,
                common_mismatch_paths=tuple(
                    sorted(
                        path_counts.items(),
                        key=lambda item: (-item[1], item[0]),
                    )[:12]
                ),
                closest_branches=tuple(closest),
                worlds=worlds,
                error=error,
            )

        def run(worker: HypotheticalSearchWorker) -> BeliefCollapseDiagnostic:
            nonlocal exact_matches, generated
            legal_particles: list[tuple[str, BeliefParticle]] = []
            validator = getattr(worker, "validate_choices", None)

            for index, particle in enumerate(particles, 1):
                world_id = particle.world_id or particle.history_id or f"particle-{index}"
                if callable(validator):
                    validated = validator(
                        state=particle.state,
                        side="p1",
                        candidates=[resolved_opponent_choice],
                    )
                    legal = resolved_opponent_choice in validated
                else:
                    legal = resolved_opponent_choice in worker.legal_choices(
                        state=particle.state,
                        side="p1",
                    )
                per_world[world_id] = {
                    "legal": legal,
                    "generated": 0,
                    "closest_count": None,
                    "closest_paths": (),
                }
                if legal:
                    legal_particles.append((world_id, particle))

            if not legal_particles:
                return build_diagnostic(
                    summary="resolved-human-choice-illegal-in-all-particles",
                    budget_exhausted=False,
                )

            rounds = 0
            stop = False
            while not stop and rounds < 64:
                for world_id, particle in legal_particles:
                    if perf_counter() >= deadline - 1.0:
                        stop = True
                        break

                    seeds = (next_seed(), next_seed())
                    branches = [
                        {
                            "p1_choice": resolved_opponent_choice,
                            "p2_choice": ai_choice,
                            "include_state": True,
                            "view_side": "p2",
                            "rng_seed": seed,
                            **(
                                {"previews": self.previews}
                                if self.previews is not None
                                else {}
                            ),
                        }
                        for seed in seeds
                    ]
                    resolved = worker.branch_many(
                        state=particle.state,
                        branches=branches,
                    )
                    per_world[world_id]["generated"] = (
                        int(per_world[world_id]["generated"]) + len(resolved)
                    )
                    generated += len(resolved)

                    for result in resolved:
                        state = result.get("state")
                        if not isinstance(state, dict):
                            continue
                        simulated_view = result.get("view")
                        if not isinstance(simulated_view, dict):
                            simulated_view = worker.state_view(
                                state=state,
                                side="p2",
                                previews=self.previews,
                            )
                        simulated = _normalized_public_observation(simulated_view)
                        differences = _collapse_differences(actual, simulated)

                        if not differences:
                            exact_matches += 1
                            closest.insert(
                                0,
                                CollapseBranchDiagnostic(
                                    world_id=world_id,
                                    mismatch_count=0,
                                    differences=(),
                                ),
                            )
                            del closest[5:]
                            stop = True
                            break

                        for difference in differences:
                            path_counts[difference.path] = (
                                path_counts.get(difference.path, 0) + 1
                            )

                        mismatch_count = len(differences)
                        current = per_world[world_id]["closest_count"]
                        if current is None or mismatch_count < int(current):
                            per_world[world_id]["closest_count"] = mismatch_count
                            per_world[world_id]["closest_paths"] = tuple(
                                difference.path for difference in differences
                            )

                        closest.append(
                            CollapseBranchDiagnostic(
                                world_id=world_id,
                                mismatch_count=mismatch_count,
                                differences=differences[:8],
                            )
                        )
                        closest.sort(
                            key=lambda branch: (
                                branch.mismatch_count,
                                branch.world_id,
                                tuple(
                                    difference.path
                                    for difference in branch.differences
                                ),
                            )
                        )
                        del closest[5:]

                    if stop:
                        break
                rounds += 1

            if exact_matches:
                summary = "exact-match-found-with-extra-rng"
            elif closest and _hp_only_differences(closest[0].differences):
                summary = "closest-branch-differs-only-in-hp"
            else:
                summary = "no-exact-match; inspect-public-state-differences"
            return build_diagnostic(
                summary=summary,
                budget_exhausted=(
                    exact_matches == 0
                    and perf_counter() >= deadline - 1.0
                ),
            )

        try:
            diagnostic, timed_out = self._run_until_deadline(
                run,
                deadline=deadline,
                cleanup_reserve_seconds=0.5,
            )
        except Exception as error:
            return build_diagnostic(
                summary="collapse-debug-error",
                budget_exhausted=False,
                error=f"{type(error).__name__}: {error}",
            )

        if diagnostic is not None:
            if timed_out and not diagnostic.budget_exhausted:
                return BeliefCollapseDiagnostic(
                    summary=diagnostic.summary,
                    elapsed_seconds=diagnostic.elapsed_seconds,
                    budget_exhausted=True,
                    generated_branches=diagnostic.generated_branches,
                    exact_matches=diagnostic.exact_matches,
                    worlds_tested=diagnostic.worlds_tested,
                    legal_worlds=diagnostic.legal_worlds,
                    illegal_worlds=diagnostic.illegal_worlds,
                    common_mismatch_paths=diagnostic.common_mismatch_paths,
                    closest_branches=diagnostic.closest_branches,
                    worlds=diagnostic.worlds,
                    error=diagnostic.error,
                )
            return diagnostic

        return build_diagnostic(
            summary="collapse-debug-budget-exhausted",
            budget_exhausted=True,
            error="diagnostic worker did not return before the debug deadline",
        )

    def _fallback_decision(
        self,
        legal_choices: list[str],
        *,
        started: float,
        reason: str,
        own_speed_diagnostics: tuple[dict[str, object], ...] = (),
    ) -> BeliefDecision:
        return BeliefDecision(
            choice=self.fallback_selector(legal_choices),
            mode="fallback",
            particle_count=len(self.particles),
            candidate_count=0,
            branch_count=0,
            elapsed_seconds=perf_counter() - started,
            fallback_reason=reason,
            own_speed_diagnostics=own_speed_diagnostics,
        )

    def _try_first_turn_public_rebase(self, *, deadline: float) -> bool:
        """Try one fresh public-prior witness; never replay a historical backlog.

        The covered domain is strictly the first resolved turn after preview.
        Later midgame positions lack a validated from-present native constructor.
        No result is treated as an exhaustive explanation of opponent sets.
        """
        ledger = self.public_constraint_ledger
        if (
            ledger is None
            or self.public_constraint_ledger_issue is not None
            or len(self.pending_observations) != 1
            or self._public_ai_preview_choice is None
            or self.recovery_authority_root_public_view is None
        ):
            return False
        own_choice, previous, current = self.pending_observations[0]
        opening = self.recovery_authority_root_public_view
        if (
            not isinstance(previous, dict)
            or not isinstance(current, dict)
            or current.get("turn") != 2
            or opening.get("turn") != 1
            or public_observation_signature(previous)
            != public_observation_signature(opening)
            or ledger.current_turn != 2
            or ledger.current_signature in self._public_rebase_attempted_signatures
            or perf_counter() >= deadline - 1.0
        ):
            return False

        # One opportunity per unique public observation. A failed RNG witness
        # or missing catalog set is never proof the real world is impossible.
        self._public_rebase_attempted_signatures.add(ledger.current_signature)
        pinned_ai_team = _pin_known_team_genders(
            self.ai_team, current.get("request", {}),
        )
        try:
            batch = build_current_state_set_proposals(
                ledger=ledger, current_view=current,
                priors=self.opponent_priors, limit=min(self.world_limit, 4),
            )
            if not batch.proposals:
                return False

            def synthesize(worker: HypotheticalSearchWorker) -> tuple[BeliefParticle, ...]:
                report = bootstrap_public_current_scaffolds(
                    worker, opening_view=opening, current_view=current,
                    ledger=ledger, prior_batch=batch,
                    battle_format=self.battle_format, ai_team=pinned_ai_team,
                    ai_preview_choice=self._public_ai_preview_choice,
                    known_own_choice=own_choice,
                    rng_seeds=(self._particle_seed(), self._particle_seed()),
                    max_roots=4, max_opponent_choices=4,
                    max_branches=16, max_witnesses=min(4, self.max_particles),
                )
                by_id = {p.proposal_id: p for p in batch.proposals}
                accepted: list[BeliefParticle] = []
                for witness in report.witnesses:
                    checkpoint = validate_public_bootstrap_checkpoint(
                        worker, witness=witness, ledger=ledger,
                        current_view=current, prior_batch=batch,
                    )
                    if checkpoint is None:
                        continue
                    proposal = by_id[checkpoint.proposal_id]
                    accepted.append(BeliefParticle(
                        state=checkpoint.state,
                        weight=proposal.weight,
                        world_id=checkpoint.proposal_id,
                        history_id="fresh-public-witness",
                        p1_member_lineage=identity_member_lineage(checkpoint.state, "p1"),
                        p2_member_lineage=identity_member_lineage(checkpoint.state, "p2"),
                    ))
                return tuple(accepted)

            candidates, timed_out = self._run_until_deadline(
                synthesize,
                deadline=min(deadline - 0.5, perf_counter() + 3.5),
            )
        except (RuntimeError, ValueError, ShowdownRequestError):
            return False

        if timed_out or not candidates:
            return False
        # Only pinned-native, independently projected positive witnesses enter
        # search. Other unrepresented worlds remain unresolved, not excluded.
        self.particles = resample_particles_by_world(
            candidates, limit=self.max_particles,
            seed=int(current["turn"]) + 829,
        )
        self.pending_observations.clear()
        self._clear_pending_recovery_progress()
        # A successful fresh witness is independent of old ancestry. Public
        # evidence remains in the particle-independent constraint ledger.
        self.recovery_authority_root_particles = ()
        self.recovery_opening_authorities = ()
        self.recovery_authority_root_public_view = None
        self.recovery_authority_history.clear()
        self.recovery_authority_history_complete = False
        self.degraded = False
        return True

    def _try_present_public_rebase(
        self, *, deadline: float, legal_live: list[str],
    ) -> bool:
        """Rebuild a bounded present-turn belief from public constraints only.

        Fresh hypotheses are Showdown-native and exact-request-validated.
        Unknown counterfactual timers/PP are not historical facts and no
        unrepresented opponent world receives negative exclusion authority.
        """
        ledger = self.public_constraint_ledger
        view = self.last_public_view
        self.last_own_speed_diagnostics = ()
        self.last_public_world_failure_reason = "missing-public-checkpoint"
        if ledger is None or self.public_constraint_ledger_issue is not None:
            self.last_public_world_failure_reason = "public-ledger-unavailable"
            return False
        if not isinstance(view, dict) or view.get("turn", 0) < 2:
            return False
        if self._public_ai_preview_choice is None:
            self.last_public_world_failure_reason = "missing-own-preview"
            return False
        if ledger.current_signature in self._public_rebase_attempted_signatures:
            self.last_public_world_failure_reason = "snapshot-already-attempted"
            return False
        if perf_counter() >= deadline - 1.0:
            self.last_public_world_failure_reason = "decision-budget-insufficient"
            return False
        # A failed proposal is never retried for the same public snapshot.
        self._public_rebase_attempted_signatures.add(ledger.current_signature)
        pinned_ai_team = _pin_known_team_genders(
            self.ai_team, view.get("request", {}),
        )

        try:
            def run(worker: HypotheticalSearchWorker):
                return build_present_rebase(
                    worker,
                    ledger=ledger, current_view=view,
                    priors=self.opponent_priors,
                    battle_format=self.battle_format,
                    ai_team=pinned_ai_team,
                    ai_preview_choice=self._public_ai_preview_choice,
                    legal_live=tuple(legal_live),
                    max_roots=min(2, self.world_limit),
                    max_particles=min(4, self.max_particles),
                )

            result, timed_out = self._run_until_deadline(
                run, deadline=min(deadline - 0.5, perf_counter() + 3.5),
            )
        except (RuntimeError, ValueError, ShowdownRequestError) as error:
            self.last_public_world_failure_reason = type(error).__name__
            return False
        if result is not None and not timed_out:
            self.last_own_speed_diagnostics = result.own_speed_diagnostics
        if timed_out or result is None or not result.particles:
            self.last_public_world_failure_reason = (
                "time-budget" if timed_out
                else result.unresolved_reason if result is not None
                else "no-worker-result"
            ) or "no-compatible-public-world"
            return False

        self.last_public_world_failure_reason = None
        self.particles = resample_particles_by_world(
            result.particles,
            limit=self.max_particles,
            seed=int(view["turn"]) + 829,
        )
        self.pending_observations.clear()
        self._clear_pending_recovery_progress()
        self.recovery_authority_root_particles = ()
        self.recovery_opening_authorities = ()
        self.recovery_authority_root_public_view = None
        self.recovery_authority_history.clear()
        self.recovery_authority_history_complete = False
        self.degraded = False
        return True

    def choose_ai_action(
        self,
        *,
        legal_live: list[str],
    ) -> BeliefDecision:
        started = perf_counter()
        decision_deadline = started + self.decision_budget_seconds
        if not legal_live:
            raise RuntimeError("AI has no legal live-session choices")
        # PR #197: new public worlds for EVERY move-phase decision after turn one.
        # A missing particle set is not an injury to be repaired. Prior particles
        # are disposable even if last turn's search succeeded.
        use_current_public_worlds = (
            isinstance(self.last_public_view, dict)
            and self.last_public_view.get("turn", 0) >= 2
            and self._public_ai_preview_choice is not None
        )
        if use_current_public_worlds:
            self._discard_decision_hypotheses()
            if not self._try_present_public_rebase(
                deadline=decision_deadline, legal_live=legal_live,
            ):
                self.degraded = True
                return self._fallback_decision(
                    legal_live, started=started,
                    reason="fresh-public-world:" + (
                        self.last_public_world_failure_reason or "unresolved"
                    ),
                    own_speed_diagnostics=self.last_own_speed_diagnostics,
                )
        elif self.degraded:
            # Legacy recovery is retained for offline diagnostics / older
            # harnesses without a post-preview public checkpoint.
            # First-turn positive public witnesses are the only currently
            # certified fresh rebase domain; later turns fail open to a legal
            # fallback until native present-turn synthesis is validated.
            if not (
                self._try_present_public_rebase(
                    deadline=decision_deadline, legal_live=legal_live,
                )
                or self._try_first_turn_public_rebase(deadline=decision_deadline)
            ):
                # This is no longer a historical-retry queue. Drop stale
                # hypothetical state and queued transitions; the independent
                # public constraint ledger remains authoritative.
                self.pending_observations.clear()
                self._clear_pending_recovery_progress()
                self.particles = ()
                self.recovery_authority_root_particles = ()
                self.recovery_opening_authorities = ()
                self.recovery_authority_root_public_view = None
                self.recovery_authority_history.clear()
                self.recovery_authority_history_complete = False
                return self._fallback_decision(
                    legal_live,
                    started=started,
                    reason="public-rebase-unresolved",
                )
        if not self.particles:
            return self._fallback_decision(
                legal_live,
                started=started,
                reason="belief-degraded",
            )

        worlds = tuple(
            ExactBeliefWorldState(
                state=particle.state,
                weight=particle.weight,
                label=particle.world_id or particle.history_id,
            )
            for particle in self.particles
        )

        def ordered_union(*groups: tuple[str, ...]) -> tuple[str, ...]:
            seen: set[str] = set()
            result: list[str] = []
            for group in groups:
                for choice in group:
                    if choice in seen:
                        continue
                    seen.add(choice)
                    result.append(choice)
            return tuple(result)

        def ordered_rng_union(
            *groups: tuple[str | None, ...],
        ) -> tuple[str | None, ...]:
            seen: set[str | None] = set()
            result: list[str | None] = []
            for group in groups:
                for sample in group:
                    if sample in seen:
                        continue
                    seen.add(sample)
                    result.append(sample)
            return tuple(result)

        def run_baseline(worker: HypotheticalSearchWorker):
            pruning = shortlist_belief_candidates(
                worker,
                worlds=worlds,
                side="p2",
                candidate_limit=self.candidate_limit,
                reference_limit=1,
                allowed_choices=tuple(legal_live),
            )
            search = search_exact_belief_turn(
                worker,
                worlds=worlds,
                side="p2",
                choices=list(pruning.candidate_shortlist),
                response_limit=self.response_limit,
                autonomous_responses=True,
            )
            return pruning, search

        def tactical_branch_count(pruning, search) -> int:
            return (
                pruning.screening_branch_count
                + search.response_screening_branch_count
                + search.branch_count
            )

        def search_diagnostics(search):
            seen: set[str] = set()
            searched_responses: list[str] = []
            for shortlist in getattr(search, "response_shortlists", ()):
                for response in shortlist:
                    if response in seen:
                        continue
                    seen.add(response)
                    searched_responses.append(response)

            worlds = tuple(getattr(search.chosen, "worlds", ()))
            if not worlds:
                return {
                    "worst_response": None,
                    "worst_world_score": None,
                    "weighted_score": getattr(
                        search.chosen,
                        "weighted_score",
                        None,
                    ),
                    "searched_responses": tuple(searched_responses),
                    "evaluated_choices": tuple(
                        getattr(search, "evaluated_choices", ())
                    ),
                    "candidate_scores": tuple(
                        (
                            candidate.choice,
                            candidate.worst_world_score,
                            candidate.weighted_score,
                        )
                        for candidate in getattr(search, "ranking", ())
                        if hasattr(candidate, "worst_world_score")
                        and hasattr(candidate, "weighted_score")
                    ),
                }

            worst_world = min(
                worlds,
                key=lambda outcome: (outcome.worst_score, outcome.label),
            )
            return {
                "worst_response": worst_world.worst_response,
                "worst_world_score": worst_world.worst_score,
                "weighted_score": getattr(
                    search.chosen,
                    "weighted_score",
                    None,
                ),
                "searched_responses": tuple(searched_responses),
                "evaluated_choices": tuple(
                    getattr(search, "evaluated_choices", ())
                ),
                "candidate_scores": tuple(
                    (
                        candidate.choice,
                        candidate.worst_world_score,
                        candidate.weighted_score,
                    )
                    for candidate in getattr(search, "ranking", ())
                ),
            }

        def decision_from_baseline(
            pruning,
            search,
            *,
            tactical_extra_branch_count: int = 0,
            strategic_probe_count: int = 0,
            strategic_branch_count: int = 0,
            strategic_rng_sample_count: int | None = None,
        ) -> BeliefDecision:
            diagnostics = search_diagnostics(search)
            return BeliefDecision(
                choice=search.chosen.choice,
                mode="belief-search",
                particle_count=len(self.particles),
                candidate_count=len(search.evaluated_choices),
                branch_count=(
                    tactical_branch_count(pruning, search)
                    + tactical_extra_branch_count
                    + strategic_branch_count
                ),
                elapsed_seconds=perf_counter() - started,
                strategic_probe_count=strategic_probe_count,
                strategic_branch_count=strategic_branch_count,
                strategic_rng_sample_count=(
                    strategic_rng_sample_count
                    if strategic_rng_sample_count is not None
                    else (
                        len(self.strategic_rng_seeds)
                        if strategic_probe_count
                        else 0
                    )
                ),
                **diagnostics,
            )

        if perf_counter() >= decision_deadline:
            return self._fallback_decision(
                legal_live,
                started=started,
                reason="belief-search-deadline",
            )

        try:
            baseline_result, baseline_timed_out = self._run_until_deadline(
                run_baseline,
                deadline=decision_deadline,
            )
        except (RuntimeError, ValueError) as error:
            return self._fallback_decision(
                legal_live,
                started=started,
                reason=f"search-error:{type(error).__name__}",
            )

        if baseline_timed_out or baseline_result is None:
            return self._fallback_decision(
                legal_live,
                started=started,
                reason="belief-search-deadline",
            )

        baseline_pruning, baseline_search = baseline_result
        if baseline_search.chosen.choice not in legal_live:
            return self._fallback_decision(
                legal_live,
                started=started,
                reason="search-choice-not-live-legal",
            )

        baseline_branches = tactical_branch_count(
            baseline_pruning,
            baseline_search,
        )
        tactical_search = baseline_search
        protected_tactical = ProtectedTacticalEvidence(
            response_shortlists=baseline_search.response_shortlists,
            rng_seeds=baseline_search.rng_samples,
        )
        tactical_extra_branch_count = 0
        protect_risk_branch_count = 0

        protect_chain_slots = tuple(
            sorted(
                {
                    slot
                    for world in worlds
                    for slot in _protect_chain_slots(world.state, "p2")
                }
            )
        )
        protect_risk_choices = _protect_risk_choices(
            baseline_search,
            protect_chain_slots,
        )
        if protect_risk_choices and perf_counter() < decision_deadline:
            def run_protect_risk(worker: HypotheticalSearchWorker):
                return search_exact_belief_turn(
                    worker,
                    worlds=worlds,
                    side="p2",
                    choices=list(protect_risk_choices),
                    rng_seeds=FINAL_RNG_SEEDS,
                    response_shortlists=baseline_search.response_shortlists,
                )

            try:
                protect_risk_search, protect_risk_timed_out = (
                    self._run_until_deadline(
                        run_protect_risk,
                        deadline=decision_deadline,
                    )
                )
            except (RuntimeError, ValueError):
                protect_risk_search = None
                protect_risk_timed_out = False

            if (
                not protect_risk_timed_out
                and protect_risk_search is not None
                and protect_risk_search.chosen.choice in legal_live
            ):
                tactical_search = protect_risk_search
                protected_tactical = ProtectedTacticalEvidence(
                    response_shortlists=protect_risk_search.response_shortlists,
                    rng_seeds=ordered_rng_union(
                        baseline_search.rng_samples,
                        protect_risk_search.rng_samples,
                    ),
                )
                protect_risk_branch_count = (
                    protect_risk_search.response_screening_branch_count
                    + protect_risk_search.branch_count
                )
                tactical_extra_branch_count = (
                    baseline_search.response_screening_branch_count
                    + baseline_search.branch_count
                )
        if self.last_public_view is None:
            return decision_from_baseline(
                baseline_pruning,
                tactical_search,
                tactical_extra_branch_count=tactical_extra_branch_count,
            )

        if perf_counter() >= decision_deadline:
            return decision_from_baseline(
                baseline_pruning,
                tactical_search,
                tactical_extra_branch_count=tactical_extra_branch_count,
            )

        def run_strategy_augmentation(worker: HypotheticalSearchWorker):
            assessment = assess_strategic_position(
                self.last_public_view,
                particles=self.particles,
            )
            plans = filter_supported_plans(
                generate_strategic_plans(assessment, limit=None),
                limit=self.strategic_plan_limit,
            )
            if not plans:
                return None

            plan_contexts = []
            candidate_reference_groups = [
                tuple(baseline_pruning.candidate_shortlist),
            ]
            strategic_branch_count = 0
            for plan in plans:
                guidance = guidance_from_plan(
                    plan,
                    view=self.last_public_view,
                )
                pruning = shortlist_belief_candidates(
                    worker,
                    worlds=worlds,
                    side="p2",
                    candidate_limit=min(
                        self.candidate_limit,
                        self.strategic_candidate_limit,
                    ),
                    reference_limit=1,
                    guidance=guidance,
                    allowed_choices=tuple(legal_live),
                )
                plan_contexts.append((plan, guidance, pruning))
                candidate_reference_groups.append(
                    tuple(pruning.candidate_shortlist)
                )
                strategic_branch_count += pruning.screening_branch_count

            shared_candidate_references = ordered_union(
                *candidate_reference_groups
            )
            # Final tactical authority must not see a weaker opponent-response set
            # than the protected baseline search. Strategy may add candidates, but it
            # cannot regain authority by shrinking the baseline's adversarial coverage.
            shared_responses = prepare_shared_strategic_responses(
                worker,
                worlds=worlds,
                side="p2",
                candidate_references=shared_candidate_references,
                response_limit=self.response_limit,
                rng_seeds=self.strategic_rng_seeds,
                protected=protected_tactical,
            )
            if len(shared_responses.response_shortlists) != len(
                protected_tactical.response_shortlists
            ):
                raise RuntimeError(
                    "strategy response evidence no longer aligns with tactical worlds"
                )
            for protected_responses, shared_world_responses in zip(
                protected_tactical.response_shortlists,
                shared_responses.response_shortlists,
                strict=True,
            ):
                if not set(protected_responses).issubset(shared_world_responses):
                    raise RuntimeError(
                        "strategy response evidence dropped a protected tactical reply"
                    )
            if not set(protected_tactical.rng_seeds).issubset(
                shared_responses.rng_seeds
            ):
                raise RuntimeError(
                    "strategy RNG evidence dropped a protected tactical sample"
                )
            strategic_branch_count += shared_responses.screening_branch_count

            probes = []
            for plan, _, pruning in plan_contexts:
                probe = probe_strategic_plan(
                    worker,
                    worlds=worlds,
                    assessment=assessment,
                    view=self.last_public_view,
                    side="p2",
                    plan=plan,
                    candidate_limit=min(
                        self.candidate_limit,
                        self.strategic_candidate_limit,
                    ),
                    response_limit=min(
                        self.response_limit,
                        self.strategic_response_limit,
                    ),
                    rng_seeds=self.strategic_rng_seeds,
                    shared_responses=shared_responses,
                    prepared_pruning=pruning,
                )
                probes.append(probe)
                strategic_branch_count += (
                    probe.response_screening_branch_count
                    + probe.branch_count
                )

            selected_probe = select_supported_plan(tuple(probes))
            if selected_probe is None:
                return (
                    None,
                    None,
                    len(probes),
                    strategic_branch_count,
                    len(shared_responses.rng_seeds),
                )

            selected_context = next(
                (
                    context
                    for context in plan_contexts
                    if context[0].name == selected_probe.plan.name
                ),
                None,
            )
            if selected_context is None:
                raise RuntimeError(
                    "selected strategic plan has no prepared candidate context"
                )
            _, selected_guidance, selected_pruning = selected_context

            final_choices = ordered_union(
                tuple(baseline_pruning.candidate_shortlist),
                tuple(selected_pruning.candidate_shortlist),
                (selected_probe.chosen.choice,),
            )
            final_search = search_exact_belief_turn(
                worker,
                worlds=worlds,
                side="p2",
                choices=list(final_choices),
                rng_seeds=shared_responses.rng_seeds,
                response_shortlists=shared_responses.response_shortlists,
            )
            strategic_branch_count += (
                final_search.response_screening_branch_count
                + final_search.branch_count
            )
            return (
                final_search,
                (selected_probe, selected_guidance),
                len(probes),
                strategic_branch_count,
                len(shared_responses.rng_seeds),
            )

        try:
            augmentation, strategy_timed_out = self._run_until_deadline(
                run_strategy_augmentation,
                deadline=decision_deadline,
            )
        except (RuntimeError, ValueError):
            return decision_from_baseline(
                baseline_pruning,
                tactical_search,
                tactical_extra_branch_count=tactical_extra_branch_count,
            )

        if strategy_timed_out or augmentation is None:
            return decision_from_baseline(
                baseline_pruning,
                tactical_search,
                tactical_extra_branch_count=tactical_extra_branch_count,
            )

        (
            final_search,
            selected,
            probe_count,
            strategic_branch_count,
            strategic_rng_sample_count,
        ) = augmentation

        if final_search is None or selected is None:
            return decision_from_baseline(
                baseline_pruning,
                tactical_search,
                tactical_extra_branch_count=tactical_extra_branch_count,
                strategic_probe_count=probe_count,
                strategic_branch_count=strategic_branch_count,
                strategic_rng_sample_count=strategic_rng_sample_count,
            )

        if final_search.chosen.choice not in legal_live:
            return decision_from_baseline(
                baseline_pruning,
                tactical_search,
                tactical_extra_branch_count=tactical_extra_branch_count,
                strategic_probe_count=probe_count,
                strategic_branch_count=strategic_branch_count,
            )

        selected_probe, selected_guidance = selected
        probed_candidate = next(
            (
                candidate
                for candidate in selected_probe.ranking
                if candidate.choice == final_search.chosen.choice
            ),
            None,
        )
        plan_aligned = (
            choice_matches_guidance(
                final_search.chosen.choice,
                selected_guidance,
            )
            and probed_candidate is not None
            and probed_candidate.evaluation.robust
        )
        diagnostics = search_diagnostics(final_search)
        return BeliefDecision(
            choice=final_search.chosen.choice,
            mode="belief-search",
            particle_count=len(self.particles),
            candidate_count=len(final_search.evaluated_choices),
            branch_count=(
                baseline_branches
                + protect_risk_branch_count
                + strategic_branch_count
            ),
            elapsed_seconds=perf_counter() - started,
            strategic_plan=(
                selected_probe.plan.name
                if plan_aligned
                else None
            ),
            strategic_probe_count=probe_count,
            strategic_branch_count=strategic_branch_count,
            strategic_rng_sample_count=strategic_rng_sample_count,
            **diagnostics,
        )

    def observe_public_turn(
        self,
        *,
        decision: BeliefDecision,
        view: dict,
    ) -> BeliefTurnUpdate:
        """Condition the posterior on a sanitized p2 public observation."""
        starting_particles = self.particles
        particles_before = len(starting_particles)
        previous_view = self.last_public_view
        # Keeps recording during pending historical recovery, but quarantine
        # any incompatible producer view without changing live tactical behavior.
        self._record_public_constraints(view, initialize=False)
        self.last_public_view = view
        recovery_retry_diagnostic = self.last_recovery_retry_diagnostic
        self.last_recovery_retry_diagnostic = None

        conditioning_started = perf_counter()
        if (
            self._public_ai_preview_choice is not None
            and isinstance(view, dict)
            and view.get("turn", 0) >= 2
        ):
            # No historical conditioning or next-turn recovery backlog.
            # Public constraints have already advanced above. A fresh batch
            # will be built from that checkpoint when the next choice arrives.
            self._discard_decision_hypotheses()
            self.degraded = (
                decision.mode == "fallback"
                or self.public_constraint_ledger_issue is not None
            )
            return BeliefTurnUpdate(
                decision=decision, public_view=view,
                particles_before=particles_before, particles_after=0,
                generated_branches=0, matched_branches=0,
                conditioning_seconds=perf_counter() - conditioning_started,
                conditioning_over_budget=False, degraded=self.degraded,
            )
        conditioning_deadline = (
            conditioning_started + self.conditioning_budget_seconds
        )
        recovery_diagnostic: BeliefRecoveryDiagnostic | None = None

        if self.degraded or self.pending_observations:
            # Once degraded, keep collecting public facts in the independent
            # ledger but NEVER append another history item or condition stale
            # pre-collapse particles. Only the first failure is eligible for
            # the bounded one-turn positive witness at the next decision.
            update = None
            timed_out = False
            conditioning_seconds = perf_counter() - conditioning_started
            self.degraded = True
            generated = 0
            matched = 0
            recovery_diagnostic = _recovery_diagnostic(
                reason="public-rebase-unresolved",
                view=view,
                particles_before=starting_particles,
                update=None,
                recovery_candidates=self.particles,
                recovery_retry=recovery_retry_diagnostic,
            )
        else:
            def run_conditioning(worker: HypotheticalSearchWorker):
                return self._condition_adaptive(
                    worker,
                    particles=starting_particles,
                    ai_choice=decision.choice,
                    view=view,
                    previous_view=previous_view,
                    batches=self.rng_sample_batches,
                    deadline=conditioning_deadline,
                )

            conditioning_error: Exception | None = None
            try:
                update, timed_out = self._run_until_deadline(
                    run_conditioning,
                    deadline=conditioning_deadline,
                )
            except (RuntimeError, ValueError, ShowdownRequestError) as error:
                update = None
                timed_out = False
                conditioning_error = error
            conditioning_seconds = perf_counter() - conditioning_started

            if conditioning_error is not None:
                self.pending_observations.append(
                    (
                        decision.choice,
                        previous_view,
                        view,
                    )
                )
                # Window 0 belonged to the initial conditioning attempt. Any
                # retry must search a fresh concrete-witness window. This is
                # search scheduling only; the miss itself has no authority.
                self.pending_recovery_witness_window = 1
                self.degraded = True
                generated = 0
                matched = 0
                recovery_diagnostic = _recovery_diagnostic(
                    reason="conditioning-error",
                    view=view,
                    particles_before=starting_particles,
                    update=None,
                    recovery_candidates=self.particles,
                    error=(
                        f"{type(conditioning_error).__name__}: "
                        f"{conditioning_error}"
                    ),
                )
            elif timed_out or update is None:
                self.pending_observations.append(
                    (
                        decision.choice,
                        previous_view,
                        view,
                    )
                )
                # Window 0 belonged to the initial conditioning attempt. Any
                # retry must search a fresh concrete-witness window. This is
                # search scheduling only; the miss itself has no authority.
                self.pending_recovery_witness_window = 1
                self.degraded = True
                generated = 0 if update is None else update.generated
                matched = 0 if update is None else update.matched
                recovery_diagnostic = _recovery_diagnostic(
                    reason="conditioning-timeout",
                    view=view,
                    particles_before=starting_particles,
                    update=update,
                    recovery_candidates=self.particles,
                )
            elif update.particles:
                self.particles = resample_particles_by_world(
                    update.particles,
                    limit=self.max_particles,
                    seed=int(view.get("turn", 0)) + 53,
                )
                self._record_recovery_authority_observation(
                    ai_choice=decision.choice,
                    previous_view=previous_view,
                    view=view,
                )
                self.degraded = False
                generated = update.generated
                matched = update.matched
            else:
                self.pending_observations.append(
                    (
                        decision.choice,
                        previous_view,
                        view,
                    )
                )
                # Window 0 belonged to the initial conditioning attempt. Any
                # retry must search a fresh concrete-witness window. This is
                # search scheduling only; the miss itself has no authority.
                self.pending_recovery_witness_window = 1
                self.degraded = True
                generated = update.generated
                matched = update.matched
                if update.unsupported_public_evidence:
                    reason = "unsupported-public-evidence"
                elif update.matched > 0:
                    reason = "partial-world-sampled-match"
                else:
                    reason = "zero-sampled-match"
                recovery_diagnostic = _recovery_diagnostic(
                    reason=reason,
                    view=view,
                    particles_before=starting_particles,
                    update=update,
                    recovery_candidates=self.particles,
                )

        return BeliefTurnUpdate(
            decision=decision,
            public_view=view,
            particles_before=particles_before,
            particles_after=len(self.particles),
            generated_branches=generated,
            matched_branches=matched,
            conditioning_seconds=conditioning_seconds,
            conditioning_over_budget=timed_out,
            degraded=self.degraded,
            finite_reachability_witnesses=(
                update.finite_reachability_witnesses
                if update is not None
                else 0
            ),
            finite_reachability_disproofs=(
                update.finite_reachability_disproofs
                if update is not None
                else 0
            ),
            finite_reachability_unresolved=(
                update.finite_reachability_unresolved
                if update is not None
                else 0
            ),
            finite_reachability_leaves=(
                update.finite_reachability_leaves
                if update is not None
                else 0
            ),
            recovery_diagnostic=recovery_diagnostic,
            recovery_retry_diagnostic=recovery_retry_diagnostic,
        )


class _BeliefBattleCoordinator:
    """Private live-session owner behind the sealed demo facade."""

    def __init__(
        self,
        worker: ShowdownSearchWorker,
        *,
        battle_format: str,
        ai_team: str,
        opponent_priors: PublicSetPriorCatalog,
        world_limit: int = 8,
        particles_per_world: int = 1,
        max_particles: int = 8,
        candidate_limit: int = 4,
        response_limit: int = 4,
        strategic_plan_limit: int = 2,
        strategic_candidate_limit: int = 3,
        strategic_response_limit: int = 2,
        strategic_rng_seeds: tuple[str, ...] = SCREENING_RNG_SEEDS,
        decision_budget_seconds: float = 8.0,
        conditioning_budget_seconds: float = 8.0,
        collapse_debug_budget_seconds: float = 15.0,
        rng_sample_batches: tuple[int, ...] = (2, 4),
        recovery_rng_sample_batches: tuple[int, ...] = (4, 8),
        observed_action_rng_multiplier: int = 16,
        particle_seed: int = 53,
        fallback_selector: FallbackSelector = choose_public_fallback,
    ):
        self._worker = worker
        self._battle_format = battle_format
        self._ai_team = ai_team
        self._session_id: str | None = None
        self._engine = BeliefDecisionEngine(
            worker.project_root,
            battle_format=battle_format,
            ai_team=ai_team,
            opponent_priors=opponent_priors,
            world_limit=world_limit,
            particles_per_world=particles_per_world,
            max_particles=max_particles,
            candidate_limit=candidate_limit,
            response_limit=response_limit,
            strategic_plan_limit=strategic_plan_limit,
            strategic_candidate_limit=strategic_candidate_limit,
            strategic_response_limit=strategic_response_limit,
            strategic_rng_seeds=strategic_rng_seeds,
            decision_budget_seconds=decision_budget_seconds,
            conditioning_budget_seconds=conditioning_budget_seconds,
            collapse_debug_budget_seconds=collapse_debug_budget_seconds,
            rng_sample_batches=rng_sample_batches,
            recovery_rng_sample_batches=recovery_rng_sample_batches,
            observed_action_rng_multiplier=observed_action_rng_multiplier,
            particle_seed=particle_seed,
            fallback_selector=fallback_selector,
        )
        self._state_lock = RLock()
        self._turn_state = SealedTurnState.NEW
        self._sealed_decision: tuple[str, BeliefDecision] | None = None
        self._pending_human_choice: str | None = None
        self._pending_public_view: dict | None = None
        self._pre_submit_signature: str | None = None

    @property
    def turn_state(self) -> SealedTurnState:
        with self._state_lock:
            return self._turn_state

    def _require_session(self) -> str:
        if self._session_id is None:
            raise RuntimeError("battle has no active session")
        return self._session_id

    def _engine_snapshot(self) -> _EngineObservationSnapshot:
        return _EngineObservationSnapshot(
            last_public_view=self._engine.last_public_view,
            particles=self._engine.particles,
            pending_observations=tuple(self._engine.pending_observations),
            pending_recovery_prefix_particles=(
                self._engine.pending_recovery_prefix_particles
            ),
            pending_recovery_prefix_count=(
                self._engine.pending_recovery_prefix_count
            ),
            pending_recovery_witnesses=(
                self._engine.pending_recovery_witnesses
            ),
            pending_recovery_excluded_world_ids=(
                self._engine.pending_recovery_excluded_world_ids
            ),
            pending_recovery_witness_window=(
                self._engine.pending_recovery_witness_window
            ),
            pending_recovery_finite_frontiers=(
                self._engine.pending_recovery_finite_frontiers
            ),
            recovery_authority_root_particles=(
                self._engine.recovery_authority_root_particles
            ),
            recovery_opening_authorities=deepcopy(
                self._engine.recovery_opening_authorities
            ),
            recovery_authority_root_public_view=(
                deepcopy(self._engine.recovery_authority_root_public_view)
            ),
            recovery_authority_history=tuple(
                self._engine.recovery_authority_history
            ),
            recovery_authority_history_complete=(
                self._engine.recovery_authority_history_complete
            ),
            degraded=self._engine.degraded,
        )

    def _restore_engine_snapshot(
        self,
        snapshot: _EngineObservationSnapshot,
    ) -> None:
        self._engine.last_public_view = snapshot.last_public_view
        self._engine.particles = snapshot.particles
        self._engine.pending_observations = list(snapshot.pending_observations)
        self._engine.pending_recovery_prefix_particles = (
            snapshot.pending_recovery_prefix_particles
        )
        self._engine.pending_recovery_prefix_count = (
            snapshot.pending_recovery_prefix_count
        )
        self._engine.pending_recovery_witnesses = (
            snapshot.pending_recovery_witnesses
        )
        self._engine.pending_recovery_excluded_world_ids = (
            snapshot.pending_recovery_excluded_world_ids
        )
        self._engine.pending_recovery_witness_window = (
            snapshot.pending_recovery_witness_window
        )
        self._engine.pending_recovery_finite_frontiers = (
            snapshot.pending_recovery_finite_frontiers
        )
        self._engine.recovery_authority_root_particles = (
            snapshot.recovery_authority_root_particles
        )
        self._engine.recovery_opening_authorities = deepcopy(
            snapshot.recovery_opening_authorities
        )
        self._engine.recovery_authority_root_public_view = deepcopy(
            snapshot.recovery_authority_root_public_view
        )
        self._engine.recovery_authority_history = list(
            snapshot.recovery_authority_history
        )
        self._engine.recovery_authority_history_complete = (
            snapshot.recovery_authority_history_complete
        )
        self._engine.degraded = snapshot.degraded

    def start(
        self,
        *,
        opponent_team: str,
        p1_name: str = "Practice Player",
        p2_name: str = "Practice AI",
        session_seed: str | None = None,
    ) -> None:
        with self._state_lock:
            if self._turn_state is not SealedTurnState.NEW:
                raise RuntimeError(
                    f"cannot start battle while state is {self._turn_state.value}"
                )
            # Claim startup ownership before releasing the coordinator lock.
            # A second caller must never be able to create another live session.
            self._turn_state = SealedTurnState.STARTING

        try:
            started = self._worker.start_session(
                battle_format=self._battle_format,
                p1_team=opponent_team,
                p2_team=self._ai_team,
                p1_name=p1_name,
                p2_name=p2_name,
                seed=session_seed,
            )
            raw_session_id = started.get("session_id")
            if not isinstance(raw_session_id, str) or not raw_session_id:
                raise RuntimeError(
                    "Showdown worker returned an invalid live session identifier"
                )
            session_id = raw_session_id
        except ShowdownWorkerTimeout as error:
            if error.mutating:
                with self._state_lock:
                    if self._turn_state is SealedTurnState.STARTING:
                        self._turn_state = SealedTurnState.CLOSED
                self._worker.abort(timeout_seconds=0.25)
                raise RuntimeError(
                    "live session start timed out with unknown outcome; "
                    "create a new battle"
                ) from error
            with self._state_lock:
                if self._turn_state is SealedTurnState.STARTING:
                    self._turn_state = SealedTurnState.NEW
            raise
        except ShowdownRequestError as error:
            if error.safe_retry:
                with self._state_lock:
                    if self._turn_state is SealedTurnState.STARTING:
                        self._turn_state = SealedTurnState.NEW
                raise
            with self._state_lock:
                if self._turn_state is SealedTurnState.STARTING:
                    self._turn_state = SealedTurnState.CLOSED
            self._worker.abort(timeout_seconds=0.25)
            raise
        except Exception:
            # Any other failure after entering a mutating live request is
            # conservatively treated as ambiguous. Do not permit another
            # start on the same transport.
            with self._state_lock:
                if self._turn_state is SealedTurnState.STARTING:
                    self._turn_state = SealedTurnState.CLOSED
            self._worker.abort(timeout_seconds=0.25)
            raise

        with self._state_lock:
            if self._turn_state is not SealedTurnState.STARTING:
                state = self._turn_state
            else:
                self._session_id = session_id
                self._turn_state = SealedTurnState.PREVIEW
                return

        # close() or another terminal transition won the race after the
        # worker created the session. Never resurrect coordinator ownership.
        cleanup_error: Exception | None = None
        try:
            self._worker.close_session(session_id)
        except Exception as error:
            cleanup_error = error
        finally:
            self._worker.close()
        raise RuntimeError(
            "battle state changed during session startup; "
            f"state is {state.value}"
        ) from cleanup_error

    def _invalidate_preview_session(self) -> None:
        """Abandon a preview-mutated live session that cannot be reconciled."""
        with self._state_lock:
            if self._turn_state is SealedTurnState.PREVIEW_SUBMITTING:
                self._turn_state = SealedTurnState.RESTART_REQUIRED
                self._session_id = None
        self._worker.abort(timeout_seconds=0.25)

    def submit_preview(
        self,
        *,
        human_choice: str,
        ai_choice: str,
    ) -> None:
        with self._state_lock:
            if self._turn_state is not SealedTurnState.PREVIEW:
                raise RuntimeError(
                    "battle is not awaiting preview choices; "
                    f"state is {self._turn_state.value}"
                )
            session_id = self._require_session()
            # Preview choice submission mutates the authoritative live session.
            # Claim it before releasing the lock so only one caller owns it.
            self._turn_state = SealedTurnState.PREVIEW_SUBMITTING

        try:
            self._worker.choose_session(
                session_id,
                p1_choice=human_choice,
                p2_choice=ai_choice,
            )
        except ShowdownWorkerTimeout as error:
            if error.mutating:
                self._invalidate_preview_session()
                raise RuntimeError(
                    "preview submission timed out with unknown outcome; "
                    "restart the battle before submitting again"
                ) from error
            with self._state_lock:
                if self._turn_state is SealedTurnState.PREVIEW_SUBMITTING:
                    self._turn_state = SealedTurnState.PREVIEW
            raise
        except ShowdownRequestError as error:
            if error.safe_retry:
                with self._state_lock:
                    if self._turn_state is SealedTurnState.PREVIEW_SUBMITTING:
                        self._turn_state = SealedTurnState.PREVIEW
            else:
                self._invalidate_preview_session()
            raise
        except Exception:
            self._invalidate_preview_session()
            raise

        try:
            view = self._worker.session_view(session_id, side="p2")["view"]
            self._engine.initialize_preview(
                view=view,
                ai_choice=ai_choice,
            )
        except Exception as error:
            # The live preview mutation already succeeded. Without a verified
            # public observation and initialized belief state, resubmission
            # could double-apply preview. Fail closed and require a new battle.
            self._invalidate_preview_session()
            raise RuntimeError(
                "preview was submitted but post-submit initialization failed; "
                "restart the battle"
            ) from error

        with self._state_lock:
            if self._turn_state is not SealedTurnState.PREVIEW_SUBMITTING:
                raise RuntimeError(
                    "battle state changed during preview submission; "
                    f"state is {self._turn_state.value}"
                )
            self._turn_state = (
                SealedTurnState.TERMINAL
                if bool(view.get("ended"))
                else SealedTurnState.IDLE
            )

    def human_public_view(self) -> dict:
        with self._state_lock:
            session_id = self._require_session()
            return self._worker.session_view(
                session_id,
                side="p1",
            )["view"]

    def human_legal_choices(self) -> list[str]:
        """Return choices derivable from the human side's public request.

        Hidden opponent effects must not be exposed by exact live-state legality
        probing. The worker resolves only Showdown's public fight-button
        uncertainty before returning submit-safe choices.
        """
        with self._state_lock:
            if self._turn_state in {
                SealedTurnState.STARTING,
                SealedTurnState.PREVIEW_SUBMITTING,
                SealedTurnState.FAILED,
                SealedTurnState.UNKNOWN,
                SealedTurnState.RESTART_REQUIRED,
                SealedTurnState.TERMINAL,
                SealedTurnState.CLOSED,
            }:
                return []
            return self._worker.session_public_choices(
                self._require_session(),
                side="p1",
            )

    def _ai_preseal_choices(self) -> list[str]:
        """Return AI choices derived only from its public request.

        This must not validate candidates against the exact live battle: doing so can
        distinguish hidden opponent effects such as Shadow Tag before sealing.
        """
        return self._worker.session_public_choices(
            self._require_session(),
            side="p2",
        )

    def lock_ai_action(self) -> SealedDecisionReady:
        with self._state_lock:
            if self._turn_state is SealedTurnState.TERMINAL:
                raise RuntimeError("battle is already terminal")
            if self._turn_state not in {
                SealedTurnState.IDLE,
                SealedTurnState.RESOLVED,
            }:
                raise RuntimeError(
                    f"cannot lock AI action while state is {self._turn_state.value}"
                )
            self._turn_state = SealedTurnState.COMPUTING

        try:
            legal_live = self._ai_preseal_choices()
            if FORCED_WAIT_CHOICE in legal_live and legal_live != [
                FORCED_WAIT_CHOICE
            ]:
                raise RuntimeError(
                    "forced-wait token must be the only publicly selectable choice"
                )
            if legal_live == [FORCED_WAIT_CHOICE]:
                decision = BeliefDecision(
                    choice=FORCED_WAIT_CHOICE,
                    mode="forced-wait",
                    particle_count=len(self._engine.particles),
                    candidate_count=1,
                    branch_count=0,
                    elapsed_seconds=0.0,
                )
            else:
                decision = self._engine.choose_ai_action(
                    legal_live=legal_live,
                )
            if decision.choice not in legal_live:
                raise RuntimeError(
                    "decision engine returned an action outside the "
                    "publicly selectable set"
                )
            token = secrets.token_urlsafe(18)
        except Exception:
            with self._state_lock:
                if self._turn_state is SealedTurnState.COMPUTING:
                    self._turn_state = SealedTurnState.IDLE
            raise

        with self._state_lock:
            if self._turn_state is not SealedTurnState.COMPUTING:
                raise RuntimeError("sealed turn state changed during AI computation")
            self._sealed_decision = (token, decision)
            self._turn_state = SealedTurnState.LOCKED
            return SealedDecisionReady(token=token)

    def _validate_locked_commit(
        self,
        *,
        token: str,
        human_choice: str,
    ) -> BeliefDecision:
        if self._turn_state is not SealedTurnState.LOCKED:
            raise RuntimeError(
                f"cannot commit human action while state is {self._turn_state.value}"
            )
        if self._sealed_decision is None:
            raise RuntimeError("sealed decision payload is missing")
        expected_token, decision = self._sealed_decision
        if not secrets.compare_digest(token, expected_token):
            raise ValueError("invalid locked-decision token")
        legal = self._worker.session_public_choices(
            self._require_session(),
            side="p1",
        )
        if human_choice not in legal:
            raise ValueError("human choice is not live-session legal")
        return decision

    def _finalize_submitted_turn(
        self,
        *,
        decision: BeliefDecision,
        public_view: dict,
    ) -> SealedTurnResult:
        # Fetch every live-session view needed for the result before mutating belief
        # state. If this read fails, reconciliation can retry without conditioning the
        # same submitted turn twice.
        human_view = self._worker.session_view(
            self._require_session(),
            side="p1",
        )["view"]

        snapshot = self._engine_snapshot()
        try:
            update = self._engine.observe_public_turn(
                decision=decision,
                view=public_view,
            )
        except Exception:
            self._restore_engine_snapshot(snapshot)
            raise

        collapse_diagnostic = None
        if (
            not snapshot.degraded
            and not snapshot.pending_observations
            and update.degraded
            and update.matched_branches == 0
            and self._pending_human_choice is not None
        ):
            collapse_diagnostic = self._engine.diagnose_collapse(
                particles=snapshot.particles,
                ai_choice=decision.choice,
                resolved_opponent_choice=self._pending_human_choice,
                previous_view=snapshot.last_public_view,
                view=public_view,
            )

        terminal = bool(public_view.get("ended"))
        with self._state_lock:
            self._sealed_decision = None
            self._pending_human_choice = None
            self._pending_public_view = None
            self._pre_submit_signature = None
            self._turn_state = (
                SealedTurnState.TERMINAL
                if terminal
                else SealedTurnState.RESOLVED
            )

        return SealedTurnResult(
            decision=decision,
            public_view=human_view,
            particles_before=update.particles_before,
            particles_after=update.particles_after,
            generated_branches=update.generated_branches,
            matched_branches=update.matched_branches,
            conditioning_seconds=update.conditioning_seconds,
            conditioning_over_budget=update.conditioning_over_budget,
            degraded=update.degraded,
            terminal=terminal,
            winner=public_view.get("winner"),
            finite_reachability_witnesses=getattr(
                update, "finite_reachability_witnesses", 0
            ),
            finite_reachability_disproofs=getattr(
                update, "finite_reachability_disproofs", 0
            ),
            finite_reachability_unresolved=getattr(
                update, "finite_reachability_unresolved", 0
            ),
            finite_reachability_leaves=getattr(
                update, "finite_reachability_leaves", 0
            ),
            collapse_diagnostic=collapse_diagnostic,
            recovery_diagnostic=getattr(update, "recovery_diagnostic", None),
            recovery_retry_diagnostic=getattr(
                update,
                "recovery_retry_diagnostic",
                None,
            ),
        )

    def commit_human_action(
        self,
        *,
        token: str,
        human_choice: str,
    ) -> SealedTurnResult:
        with self._state_lock:
            decision = self._validate_locked_commit(
                token=token,
                human_choice=human_choice,
            )
            session_id = self._require_session()
            before = self._worker.session_view(
                session_id,
                side="p2",
            )["view"]
            self._pre_submit_signature = public_observation_signature(before)
            self._pending_human_choice = human_choice
            self._pending_public_view = None
            self._turn_state = SealedTurnState.SUBMITTING

        submission_error: Exception | None = None
        try:
            self._worker.choose_session(
                session_id,
                p1_choice=human_choice,
                p2_choice=decision.choice,
            )
        except ShowdownWorkerTimeout as error:
            if error.mutating:
                with self._state_lock:
                    self._turn_state = SealedTurnState.UNKNOWN
                raise RuntimeError(
                    "live turn submission timed out with unknown outcome; "
                    "reconcile before retrying"
                ) from error
            submission_error = error
        except ShowdownRequestError as error:
            submission_error = error
        except Exception as error:
            submission_error = error

        try:
            public_view = self._worker.session_view(
                session_id,
                side="p2",
            )["view"]
        except Exception:
            with self._state_lock:
                self._turn_state = SealedTurnState.FAILED
            raise

        after_signature = public_observation_signature(public_view)
        if submission_error is not None and after_signature == self._pre_submit_signature:
            if (
                isinstance(submission_error, ShowdownRequestError)
                and submission_error.choice_rejected
            ):
                with self._state_lock:
                    self._sealed_decision = None
                    self._pending_human_choice = None
                    self._pending_public_view = None
                    self._pre_submit_signature = None
                    self._turn_state = SealedTurnState.RESTART_REQUIRED
                detail = submission_error.detail
                raise RuntimeError(
                    "Showdown rejected the sealed joint command; "
                    "the battle is fail-closed and must be restarted. "
                    f"Showdown detail: {detail}"
                ) from submission_error

            with self._state_lock:
                self._pending_human_choice = None
                self._pre_submit_signature = None
                self._turn_state = SealedTurnState.LOCKED
            raise submission_error

        with self._state_lock:
            self._pending_public_view = public_view

        try:
            return self._finalize_submitted_turn(
                decision=decision,
                public_view=public_view,
            )
        except Exception:
            with self._state_lock:
                self._turn_state = SealedTurnState.FAILED
            raise

    def reconcile_failed_turn(
        self,
        *,
        token: str,
    ) -> SealedTurnResult:
        with self._state_lock:
            if self._turn_state not in {
                SealedTurnState.FAILED,
                SealedTurnState.UNKNOWN,
            }:
                raise RuntimeError(
                    "cannot reconcile unresolved turn while state is "
                    f"{self._turn_state.value}"
                )
            reconciliation_state = self._turn_state
            if self._sealed_decision is None:
                raise RuntimeError("failed turn has no retained sealed decision")
            expected_token, decision = self._sealed_decision
            if not secrets.compare_digest(token, expected_token):
                raise ValueError("invalid locked-decision token")
            session_id = self._require_session()
            public_view = self._pending_public_view
            # Claim the reconciliation atomically before any live-session read. A
            # repeated concurrent reconciliation must fail rather than condition twice.
            self._turn_state = SealedTurnState.SUBMITTING

        try:
            if public_view is None:
                public_view = self._worker.session_view(
                    session_id,
                    side="p2",
                )["view"]
        except Exception:
            with self._state_lock:
                if self._turn_state is SealedTurnState.SUBMITTING:
                    self._turn_state = reconciliation_state
            raise

        if (
            self._pre_submit_signature is not None
            and public_observation_signature(public_view)
            == self._pre_submit_signature
        ):
            with self._state_lock:
                self._pending_human_choice = None
                self._pending_public_view = None
                self._pre_submit_signature = None
                self._turn_state = SealedTurnState.LOCKED
            raise RuntimeError(
                "live session did not advance; original sealed action can be retried"
            )

        with self._state_lock:
            self._pending_public_view = public_view

        try:
            return self._finalize_submitted_turn(
                decision=decision,
                public_view=public_view,
            )
        except Exception:
            with self._state_lock:
                if self._turn_state is SealedTurnState.SUBMITTING:
                    self._turn_state = SealedTurnState.FAILED
            raise

    def close(self) -> None:
        with self._state_lock:
            if self._turn_state is SealedTurnState.CLOSED:
                return
            session_id = self._session_id
            self._turn_state = SealedTurnState.CLOSED
            self._sealed_decision = None
            self._pending_human_choice = None
            self._pending_public_view = None
            self._pre_submit_signature = None
            self._session_id = None

        try:
            if session_id is not None:
                self._worker.close_session(session_id)
        finally:
            self._worker.close()

    def abort_transport(self) -> None:
        """Emergency cancellation that does not acquire the coordinator state lock."""
        self._worker.abort(timeout_seconds=0.25)


class SealedBattleFacade:
    """Narrow human-facing API for the playable practice battle."""

    __slots__ = ("__coordinator", "__ai_preview_choice")

    def __init__(
        self,
        *,
        battle_format: str,
        ai_team: str,
        ai_preview_choice: str,
        opponent_priors: PublicSetPriorCatalog,
        project_root=None,
        world_limit: int = 8,
        particles_per_world: int = 1,
        max_particles: int = 8,
        candidate_limit: int = 4,
        response_limit: int = 4,
        strategic_plan_limit: int = 2,
        strategic_candidate_limit: int = 3,
        strategic_response_limit: int = 2,
        strategic_rng_seeds: tuple[str, ...] = SCREENING_RNG_SEEDS,
        decision_budget_seconds: float = 8.0,
        conditioning_budget_seconds: float = 8.0,
        collapse_debug_budget_seconds: float = 15.0,
        rng_sample_batches: tuple[int, ...] = (2, 4),
        recovery_rng_sample_batches: tuple[int, ...] = (4, 8),
        observed_action_rng_multiplier: int = 16,
        particle_seed: int = 53,
        worker_startup_timeout_seconds: float = 10.0,
        live_transport_timeout_seconds: float = 5.0,
        fallback_selector: FallbackSelector = choose_public_fallback,
    ):
        _validate_decision_configuration(
            world_limit=world_limit,
            particles_per_world=particles_per_world,
            max_particles=max_particles,
            candidate_limit=candidate_limit,
            response_limit=response_limit,
            strategic_plan_limit=strategic_plan_limit,
            strategic_candidate_limit=strategic_candidate_limit,
            strategic_response_limit=strategic_response_limit,
            strategic_rng_seeds=strategic_rng_seeds,
            decision_budget_seconds=decision_budget_seconds,
            conditioning_budget_seconds=conditioning_budget_seconds,
            collapse_debug_budget_seconds=collapse_debug_budget_seconds,
            rng_sample_batches=rng_sample_batches,
            recovery_rng_sample_batches=recovery_rng_sample_batches,
            observed_action_rng_multiplier=observed_action_rng_multiplier,
        )
        if worker_startup_timeout_seconds <= 0:
            raise ValueError("worker_startup_timeout_seconds must be positive")
        if live_transport_timeout_seconds <= 0:
            raise ValueError("live_transport_timeout_seconds must be positive")

        worker: ShowdownSearchWorker | None = None
        try:
            worker = ShowdownSearchWorker(
                project_root,
                startup_timeout_seconds=worker_startup_timeout_seconds,
                request_timeout_seconds=live_transport_timeout_seconds,
            )
            self.__coordinator = _BeliefBattleCoordinator(
                worker,
                battle_format=battle_format,
                ai_team=ai_team,
                opponent_priors=opponent_priors,
                world_limit=world_limit,
                particles_per_world=particles_per_world,
                max_particles=max_particles,
                candidate_limit=candidate_limit,
                response_limit=response_limit,
                strategic_plan_limit=strategic_plan_limit,
                strategic_candidate_limit=strategic_candidate_limit,
                strategic_response_limit=strategic_response_limit,
                strategic_rng_seeds=strategic_rng_seeds,
                decision_budget_seconds=decision_budget_seconds,
                conditioning_budget_seconds=conditioning_budget_seconds,
                collapse_debug_budget_seconds=collapse_debug_budget_seconds,
                rng_sample_batches=rng_sample_batches,
                recovery_rng_sample_batches=recovery_rng_sample_batches,
                observed_action_rng_multiplier=observed_action_rng_multiplier,
                particle_seed=particle_seed,
                fallback_selector=fallback_selector,
            )
        except Exception:
            if worker is not None:
                worker.close()
            raise
        self.__ai_preview_choice = ai_preview_choice

    @property
    def turn_state(self) -> SealedTurnState:
        return self.__coordinator.turn_state

    def start(
        self,
        *,
        opponent_team: str,
        p1_name: str = "Practice Player",
        p2_name: str = "Practice AI",
        session_seed: str | None = None,
    ) -> dict:
        self.__coordinator.start(
            opponent_team=opponent_team,
            p1_name=p1_name,
            p2_name=p2_name,
            session_seed=session_seed,
        )
        return self.__coordinator.human_public_view()

    def commit_preview(self, *, human_choice: str) -> dict:
        self.__coordinator.submit_preview(
            human_choice=human_choice,
            ai_choice=self.__ai_preview_choice,
        )
        return self.__coordinator.human_public_view()

    def public_state(self) -> dict:
        return self.__coordinator.human_public_view()

    def legal_human_choices(self) -> tuple[str, ...]:
        return tuple(self.__coordinator.human_legal_choices())

    def lock_ai_action(self) -> SealedDecisionReady:
        return self.__coordinator.lock_ai_action()

    def commit_human_action(
        self,
        *,
        token: str,
        human_choice: str,
    ) -> SealedTurnResult:
        return self.__coordinator.commit_human_action(
            token=token,
            human_choice=human_choice,
        )

    def reconcile_failed_turn(
        self,
        *,
        token: str,
    ) -> SealedTurnResult:
        return self.__coordinator.reconcile_failed_turn(token=token)

    def close(self) -> None:
        self.__coordinator.close()

    def abort_transport(self) -> None:
        """Emergency cancellation for a blocked live worker transport."""
        self.__coordinator.abort_transport()

    def __enter__(self) -> "SealedBattleFacade":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

