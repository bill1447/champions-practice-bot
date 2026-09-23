"""Persistent public-belief controller for a real Showdown practice session."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
import random
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
from champions_practice.observation_beliefs import (
    BeliefParticle,
    condition_particles,
    public_observation_signature,
    resample_particles,
)
from champions_practice.search_worker import ShowdownSearchWorker


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


class BeliefBattleController:
    """Drive one p1-human/p2-AI session from persistent public belief particles.

    The controller never reads the live session snapshot. The only live-battle input to
    belief maintenance is the sanitized p2 player view. Exact states exist only as
    independently seeded hypothetical particles.
    """

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
        decision_budget_seconds: float = 8.0,
        conditioning_budget_seconds: float = 8.0,
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
        if decision_budget_seconds <= 0 or conditioning_budget_seconds <= 0:
            raise ValueError("budgets must be positive")

        self.worker = worker
        self.battle_format = battle_format
        self.ai_team = ai_team
        self.opponent_priors = opponent_priors
        self.world_limit = world_limit
        self.particles_per_world = particles_per_world
        self.max_particles = max_particles
        self.candidate_limit = candidate_limit
        self.response_limit = response_limit
        self.decision_budget_seconds = decision_budget_seconds
        self.conditioning_budget_seconds = conditioning_budget_seconds
        self.fallback_selector = fallback_selector
        self._rng = random.Random(particle_seed)

        self.session_id: str | None = None
        self.previews: dict[str, list[str]] | None = None
        self.particles: tuple[BeliefParticle, ...] = ()
        self.last_public_view: dict | None = None
        self.preview_mismatch_paths: tuple[str, ...] = ()
        self.degraded = False

    def start(
        self,
        *,
        opponent_team: str,
        p1_name: str = "Practice Player",
        p2_name: str = "Practice AI",
        session_seed: str | None = None,
    ) -> dict:
        if self.session_id is not None:
            raise RuntimeError("controller already has an active session")
        started = self.worker.start_session(
            battle_format=self.battle_format,
            p1_team=opponent_team,
            p2_team=self.ai_team,
            p1_name=p1_name,
            p2_name=p2_name,
            seed=session_seed,
        )
        self.session_id = str(started["session_id"])
        return started

    def _require_session(self) -> str:
        if self.session_id is None:
            raise RuntimeError("controller has no active session")
        return self.session_id

    def _particle_seed(self) -> str:
        values = [self._rng.getrandbits(32) for _ in range(4)]
        return "sodium," + "".join(f"{value:08x}" for value in values)

    def submit_preview(self, *, human_choice: str, ai_choice: str) -> dict:
        session_id = self._require_session()
        self.worker.choose_session(
            session_id,
            p1_choice=human_choice,
            p2_choice=ai_choice,
        )
        view = self.worker.session_view(session_id, side="p2")["view"]
        self.last_public_view = view
        self.previews = {
            "p1": list(view["opponent"]["preview_species"]),
            "p2": [pokemon["species"] for pokemon in view["player"]["team"]],
        }

        belief = build_public_opponent_belief(view)
        worlds = materialize_public_belief_worlds(
            belief,
            self.opponent_priors,
            limit=self.world_limit,
        )
        wanted = public_observation_signature(view)
        particles: list[BeliefParticle] = []

        for world_index, world in enumerate(worlds, 1):
            opponent_preview = preview_choice_for_world(belief, world)
            for rng_index in range(self.particles_per_world):
                state = self.worker.create_state(
                    battle_format=self.battle_format,
                    p1_team=world.team_text,
                    p2_team=self.ai_team,
                    p1_preview=opponent_preview,
                    p2_preview=ai_choice,
                    seed=self._particle_seed(),
                )
                particle_view = self.worker.state_view(
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
                    continue
                particles.append(
                    BeliefParticle(
                        state=state,
                        weight=world.weight / self.particles_per_world,
                        world_id=f"world-{world_index}",
                        history_id=f"rng-{rng_index + 1}",
                    )
                )

        self.particles = resample_particles(
            tuple(particles),
            limit=self.max_particles,
            seed=53,
        )
        self.degraded = not bool(self.particles)
        return view

    def human_legal_choices(self) -> list[str]:
        return self.worker.session_legal_choices(self._require_session(), side="p1")

    def ai_legal_choices(self) -> list[str]:
        return self.worker.session_legal_choices(self._require_session(), side="p2")


    def _run_with_deadline(
        self,
        operation: Callable[[ShowdownSearchWorker], T],
        *,
        timeout_seconds: float,
    ) -> tuple[T | None, bool]:
        """Run hypothetical work off-session and abort its worker on timeout."""
        worker = ShowdownSearchWorker(self.worker.project_root)
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(operation, worker)
        timed_out = False
        try:
            return future.result(timeout=timeout_seconds), False
        except FutureTimeoutError:
            timed_out = True
            worker.abort()
            return None, True
        finally:
            if not timed_out:
                worker.close()
            executor.shutdown(wait=False, cancel_futures=True)

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

    def choose_ai_action(self) -> BeliefDecision:
        started = perf_counter()
        legal_live = self.ai_legal_choices()
        if not legal_live:
            raise RuntimeError("AI has no legal live-session choices")
        if self.degraded or not self.particles:
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

        def run_search(worker: ShowdownSearchWorker):
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

        try:
            result, timed_out = self._run_with_deadline(
                run_search,
                timeout_seconds=self.decision_budget_seconds,
            )
            if timed_out or result is None:
                return self._fallback_decision(
                    legal_live,
                    started=started,
                    reason="belief-search-deadline",
                )

            pruning, search = result
            elapsed = perf_counter() - started
            if search.chosen.choice not in legal_live:
                return self._fallback_decision(
                    legal_live,
                    started=started,
                    reason="search-choice-not-live-legal",
                )
            return BeliefDecision(
                choice=search.chosen.choice,
                mode="belief-search",
                particle_count=len(self.particles),
                candidate_count=len(search.evaluated_choices),
                branch_count=(
                    pruning.screening_branch_count
                    + search.response_screening_branch_count
                    + search.branch_count
                ),
                elapsed_seconds=elapsed,
            )
        except (RuntimeError, ValueError) as error:
            return self._fallback_decision(
                legal_live,
                started=started,
                reason=f"search-error:{type(error).__name__}",
            )

    def resolve_turn(
        self,
        *,
        human_choice: str,
        decision: BeliefDecision,
    ) -> BeliefTurnUpdate:
        session_id = self._require_session()
        particles_before = len(self.particles)

        self.worker.choose_session(
            session_id,
            p1_choice=human_choice,
            p2_choice=decision.choice,
        )
        view = self.worker.session_view(session_id, side="p2")["view"]
        self.last_public_view = view

        conditioning_started = perf_counter()

        def run_conditioning(worker: ShowdownSearchWorker):
            return condition_particles(
                worker,
                particles=self.particles,
                ai_side="p2",
                ai_choice=decision.choice,
                actual_public_view=view,
                previews=self.previews,
            )

        update, timed_out = self._run_with_deadline(
            run_conditioning,
            timeout_seconds=self.conditioning_budget_seconds,
        )
        conditioning_seconds = perf_counter() - conditioning_started

        if timed_out or update is None:
            self.particles = ()
            self.degraded = True
            generated = 0
            matched = 0
        elif update.particles:
            self.particles = resample_particles(
                update.particles,
                limit=self.max_particles,
                seed=int(view.get("turn", 0)) + 53,
            )
            self.degraded = False
            generated = update.generated
            matched = update.matched
        else:
            self.particles = ()
            self.degraded = True
            generated = update.generated
            matched = update.matched

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

    def close(self) -> None:
        if self.session_id is None:
            return
        self.worker.close_session(self.session_id)
        self.session_id = None
