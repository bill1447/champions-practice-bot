"""Persistent public-belief controller for a real Showdown practice session."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from enum import Enum
import random
import secrets
from threading import RLock
from time import perf_counter
from typing import Callable, TypeVar

from champions_practice.belief_search import (
    ExactBeliefWorldState,
    search_exact_belief_turn,
    shortlist_belief_candidates,
)
from champions_practice.belief_worlds import (
    PublicSetPriorCatalog,
    materialize_public_belief_worlds,
    preview_choice_for_world,
)
from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.recommendations import SCREENING_RNG_SEEDS
from champions_practice.observation_beliefs import (
    BeliefParticle,
    ParticleUpdate,
    condition_particles,
    public_observation_signature,
    public_opponent_moves_fully_observed,
    resample_particles_by_world,
)
from champions_practice.search_worker import HypotheticalSearchWorker, ShowdownSearchWorker
from champions_practice.strategy import assess_strategic_position, generate_strategic_plans
from champions_practice.strategy_evidence import (
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


@dataclass(frozen=True)
class SealedDecisionReady:
    token: str


class SealedTurnState(str, Enum):
    NEW = "new"
    PREVIEW = "preview"
    IDLE = "idle"
    COMPUTING = "computing"
    LOCKED = "locked"
    SUBMITTING = "submitting"
    RESOLVED = "resolved"
    FAILED = "failed"
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


@dataclass(frozen=True)
class _EngineObservationSnapshot:
    last_public_view: dict | None
    particles: tuple[BeliefParticle, ...]
    pending_observations: tuple[
        tuple[str, dict[str, object] | None, dict],
        ...,
    ]
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
        rng_sample_batches: tuple[int, ...] = (2, 4),
        recovery_rng_sample_batches: tuple[int, ...] = (4, 8),
        observed_action_rng_multiplier: int = 16,
        particle_seed: int = 53,
        fallback_selector: FallbackSelector = choose_public_fallback,
    ):
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
        if not rng_sample_batches or any(count <= 0 for count in rng_sample_batches):
            raise ValueError("rng_sample_batches must contain positive counts")
        if not recovery_rng_sample_batches or any(
            count <= 0 for count in recovery_rng_sample_batches
        ):
            raise ValueError("recovery_rng_sample_batches must contain positive counts")
        if observed_action_rng_multiplier <= 0:
            raise ValueError("observed_action_rng_multiplier must be positive")

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
        self.rng_sample_batches = rng_sample_batches
        self.recovery_rng_sample_batches = recovery_rng_sample_batches
        self.observed_action_rng_multiplier = observed_action_rng_multiplier
        self.fallback_selector = fallback_selector
        self._rng = random.Random(particle_seed)

        self.previews: dict[str, list[str]] | None = None
        self.particles: tuple[BeliefParticle, ...] = ()
        self.last_public_view: dict | None = None
        self.preview_mismatch_paths: tuple[str, ...] = ()
        self.preview_mismatch_values: tuple[tuple[str, object, object], ...] = ()
        self.pending_observations: list[
            tuple[str, dict[str, object] | None, dict]
        ] = []
        self.degraded = False

    def _particle_seed(self) -> str:
        values = [self._rng.getrandbits(32) for _ in range(4)]
        return "sodium," + "".join(f"{value:08x}" for value in values)

    def initialize_preview(
        self,
        *,
        view: dict,
        ai_choice: str,
    ) -> dict:
        """Initialize belief particles from the sanitized p2 post-preview view."""
        self.last_public_view = view
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

        with HypotheticalSearchWorker(self.project_root) as worker:
            for world_index, world in enumerate(worlds, 1):
                opponent_preview = preview_choice_for_world(belief, world)
                for rng_index in range(self.particles_per_world):
                    state = worker.create_state(
                        battle_format=self.battle_format,
                        p1_team=world.team_text,
                        p2_team=particle_ai_team,
                        p1_preview=opponent_preview,
                        p2_preview=ai_choice,
                        seed=self._particle_seed(),
                    )
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
                    particles.append(
                        BeliefParticle(
                            state=state,
                            weight=world.weight / self.particles_per_world,
                            world_id=f"world-{world_index}",
                            history_id=f"rng-{rng_index + 1}",
                        )
                    )

        self.particles = resample_particles_by_world(
            tuple(particles),
            limit=self.max_particles,
            seed=53,
        )
        self.degraded = not bool(self.particles)
        return view

    def _run_until_deadline(
        self,
        operation: Callable[[HypotheticalSearchWorker], T],
        *,
        deadline: float,
        cleanup_reserve_seconds: float = 0.25,
    ) -> tuple[T | None, bool]:
        """Run hypothetical work inside one absolute startup/work/cleanup deadline."""
        if perf_counter() >= deadline:
            return None, True

        worker = HypotheticalSearchWorker(self.project_root)
        remaining = deadline - perf_counter()
        if remaining <= cleanup_reserve_seconds:
            worker.abort(timeout_seconds=max(0.0, remaining))
            return None, True

        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(operation, worker)
        result: T | None = None
        timed_out = False
        try:
            result = future.result(
                timeout=max(
                    0.0,
                    deadline - perf_counter() - cleanup_reserve_seconds,
                )
            )
        except FutureTimeoutError:
            timed_out = True
        finally:
            worker.abort(
                timeout_seconds=max(
                    0.0,
                    min(cleanup_reserve_seconds, deadline - perf_counter()),
                )
            )
            executor.shutdown(wait=False, cancel_futures=True)

        if timed_out or perf_counter() > deadline:
            return None, True
        return result, False

    def _condition_adaptive(
        self,
        worker: HypotheticalSearchWorker,
        *,
        particles: tuple[BeliefParticle, ...],
        ai_choice: str,
        view: dict,
        previous_view: dict[str, object] | None = None,
        batches: tuple[int, ...],
    ) -> ParticleUpdate:
        generated = 0
        deduplicated = 0
        multiplier = (
            self.observed_action_rng_multiplier
            if public_opponent_moves_fully_observed(
                view,
                previous_public_view=previous_view,
            )
            else 1
        )
        for sample_count in batches:
            effective_count = sample_count * multiplier
            seeds = tuple(self._particle_seed() for _ in range(effective_count))
            update = condition_particles(
                worker,
                particles=particles,
                ai_side="p2",
                ai_choice=ai_choice,
                actual_public_view=view,
                previous_public_view=previous_view,
                rng_seeds=seeds,
                previews=self.previews,
            )
            generated += update.generated
            deduplicated += update.deduplicated
            if update.particles:
                return ParticleUpdate(
                    particles=update.particles,
                    generated=generated,
                    matched=update.matched,
                    deduplicated=deduplicated,
                )
        return ParticleUpdate((), generated, 0, deduplicated)

    def _recover_pending(self, *, deadline: float | None = None) -> bool:
        if not self.pending_observations:
            return bool(self.particles)

        starting_particles = self.particles
        pending = tuple(self.pending_observations)

        def recover(worker: HypotheticalSearchWorker):
            particles = starting_particles
            for ai_choice, previous_view, view in pending:
                update = self._condition_adaptive(
                    worker,
                    particles=particles,
                    ai_choice=ai_choice,
                    view=view,
                    previous_view=previous_view,
                    batches=self.recovery_rng_sample_batches,
                )
                if not update.particles:
                    return None
                particles = resample_particles_by_world(
                    update.particles,
                    limit=self.max_particles,
                    seed=int(view.get("turn", 0)) + 155,
                )
            return particles

        recovery_deadline = perf_counter() + self.conditioning_budget_seconds
        if deadline is not None:
            recovery_deadline = min(recovery_deadline, deadline)
        recovered, timed_out = self._run_until_deadline(
            recover,
            deadline=recovery_deadline,
        )
        if timed_out or not recovered:
            return False

        self.particles = recovered
        self.pending_observations.clear()
        self.degraded = False
        return True

    def _fallback_decision(
        self,
        legal_choices: list[str],
        *,
        started: float,
        reason: str,
    ) -> BeliefDecision:
        return BeliefDecision(
            choice=self.fallback_selector(legal_choices),
            mode="fallback",
            particle_count=len(self.particles),
            candidate_count=0,
            branch_count=0,
            elapsed_seconds=perf_counter() - started,
            fallback_reason=reason,
        )

    def choose_ai_action(
        self,
        *,
        legal_live: list[str],
    ) -> BeliefDecision:
        started = perf_counter()
        decision_deadline = started + self.decision_budget_seconds
        if not legal_live:
            raise RuntimeError("AI has no legal live-session choices")
        if self.degraded:
            if not self._recover_pending(deadline=decision_deadline):
                return self._fallback_decision(
                    legal_live,
                    started=started,
                    reason="belief-recovery-pending",
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

        def run_baseline(worker: HypotheticalSearchWorker):
            pruning = shortlist_belief_candidates(
                worker,
                worlds=worlds,
                side="p2",
                candidate_limit=self.candidate_limit,
                reference_limit=1,
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
            strategic_probe_count: int = 0,
            strategic_branch_count: int = 0,
        ) -> BeliefDecision:
            diagnostics = search_diagnostics(search)
            return BeliefDecision(
                choice=search.chosen.choice,
                mode="belief-search",
                particle_count=len(self.particles),
                candidate_count=len(search.evaluated_choices),
                branch_count=(
                    tactical_branch_count(pruning, search)
                    + strategic_branch_count
                ),
                elapsed_seconds=perf_counter() - started,
                strategic_probe_count=strategic_probe_count,
                strategic_branch_count=strategic_branch_count,
                strategic_rng_sample_count=(
                    len(self.strategic_rng_seeds)
                    if strategic_probe_count
                    else 0
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
        if self.last_public_view is None:
            return decision_from_baseline(
                baseline_pruning,
                baseline_search,
            )

        if perf_counter() >= decision_deadline:
            return decision_from_baseline(
                baseline_pruning,
                baseline_search,
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
            )

        try:
            augmentation, strategy_timed_out = self._run_until_deadline(
                run_strategy_augmentation,
                deadline=decision_deadline,
            )
        except (RuntimeError, ValueError):
            return decision_from_baseline(
                baseline_pruning,
                baseline_search,
            )

        if strategy_timed_out or augmentation is None:
            return decision_from_baseline(
                baseline_pruning,
                baseline_search,
            )

        (
            final_search,
            selected,
            probe_count,
            strategic_branch_count,
        ) = augmentation

        if final_search is None or selected is None:
            return decision_from_baseline(
                baseline_pruning,
                baseline_search,
                strategic_probe_count=probe_count,
                strategic_branch_count=strategic_branch_count,
            )

        if final_search.chosen.choice not in legal_live:
            return decision_from_baseline(
                baseline_pruning,
                baseline_search,
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
            branch_count=baseline_branches + strategic_branch_count,
            elapsed_seconds=perf_counter() - started,
            strategic_plan=(
                selected_probe.plan.name
                if plan_aligned
                else None
            ),
            strategic_probe_count=probe_count,
            strategic_branch_count=strategic_branch_count,
            strategic_rng_sample_count=len(self.strategic_rng_seeds),
            **diagnostics,
        )

    def observe_public_turn(
        self,
        *,
        decision: BeliefDecision,
        view: dict,
    ) -> BeliefTurnUpdate:
        """Condition the posterior on a sanitized p2 public observation."""
        particles_before = len(self.particles)
        previous_view = self.last_public_view
        self.last_public_view = view

        conditioning_started = perf_counter()

        if self.pending_observations:
            self.pending_observations.append(
                (decision.choice, previous_view, view)
            )
            update = None
            timed_out = False
            conditioning_seconds = perf_counter() - conditioning_started
            self.degraded = True
            generated = 0
            matched = 0
        else:
            def run_conditioning(worker: HypotheticalSearchWorker):
                return self._condition_adaptive(
                    worker,
                    particles=self.particles,
                    ai_choice=decision.choice,
                    view=view,
                    previous_view=previous_view,
                    batches=self.rng_sample_batches,
                )

            update, timed_out = self._run_until_deadline(
                run_conditioning,
                deadline=(
                    conditioning_started
                    + self.conditioning_budget_seconds
                ),
            )
            conditioning_seconds = perf_counter() - conditioning_started

            if timed_out or update is None:
                self.pending_observations.append(
                    (decision.choice, previous_view, view)
                )
                self.degraded = True
                generated = 0
                matched = 0
            elif update.particles:
                self.particles = resample_particles_by_world(
                    update.particles,
                    limit=self.max_particles,
                    seed=int(view.get("turn", 0)) + 53,
                )
                self.degraded = False
                generated = update.generated
                matched = update.matched
            else:
                self.pending_observations.append(
                    (decision.choice, previous_view, view)
                )
                self.degraded = True
                generated = update.generated
                matched = 0

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
        self._pre_submit_signature: dict | None = None

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
            degraded=self._engine.degraded,
        )

    def _restore_engine_snapshot(
        self,
        snapshot: _EngineObservationSnapshot,
    ) -> None:
        self._engine.last_public_view = snapshot.last_public_view
        self._engine.particles = snapshot.particles
        self._engine.pending_observations = list(snapshot.pending_observations)
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
                raise RuntimeError("battle has already been started")
            started = self._worker.start_session(
                battle_format=self._battle_format,
                p1_team=opponent_team,
                p2_team=self._ai_team,
                p1_name=p1_name,
                p2_name=p2_name,
                seed=session_seed,
            )
            self._session_id = str(started["session_id"])
            self._turn_state = SealedTurnState.PREVIEW

    def submit_preview(
        self,
        *,
        human_choice: str,
        ai_choice: str,
    ) -> None:
        with self._state_lock:
            if self._turn_state is not SealedTurnState.PREVIEW:
                raise RuntimeError("battle is not awaiting preview choices")
            session_id = self._require_session()
            self._worker.choose_session(
                session_id,
                p1_choice=human_choice,
                p2_choice=ai_choice,
            )
            view = self._worker.session_view(session_id, side="p2")["view"]
            self._engine.initialize_preview(
                view=view,
                ai_choice=ai_choice,
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
        with self._state_lock:
            if self._turn_state in {
                SealedTurnState.TERMINAL,
                SealedTurnState.CLOSED,
            }:
                return []
            return self._worker.session_legal_choices(
                self._require_session(),
                side="p1",
            )

    def _ai_legal_choices(self) -> list[str]:
        return self._worker.session_legal_choices(
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
            decision = self._engine.choose_ai_action(
                legal_live=self._ai_legal_choices(),
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
        legal = self._worker.session_legal_choices(
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
            if self._turn_state is not SealedTurnState.FAILED:
                raise RuntimeError(
                    "cannot reconcile failed turn while state is "
                    f"{self._turn_state.value}"
                )
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
                    self._turn_state = SealedTurnState.FAILED
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

        if session_id is not None:
            self._worker.close_session(session_id)
        self._worker.close()


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
        rng_sample_batches: tuple[int, ...] = (2, 4),
        recovery_rng_sample_batches: tuple[int, ...] = (4, 8),
        observed_action_rng_multiplier: int = 16,
        particle_seed: int = 53,
        fallback_selector: FallbackSelector = choose_public_fallback,
    ):
        worker = ShowdownSearchWorker(project_root)
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
            rng_sample_batches=rng_sample_batches,
            recovery_rng_sample_batches=recovery_rng_sample_batches,
            observed_action_rng_multiplier=observed_action_rng_multiplier,
            particle_seed=particle_seed,
            fallback_selector=fallback_selector,
        )
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

    def __enter__(self) -> "SealedBattleFacade":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

