"""Public-only offline queue-aware history experiment; no live authority."""

from dataclasses import replace
import hashlib
from time import perf_counter

from champions_practice.belief_controller import BeliefDecisionEngine
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import (
    ParticleUpdate,
    compose_branch_member_lineage,
    merge_sampled_world_witnesses,
    public_observation_signature,
)
from champions_practice.queue_retention import pending_queue_key, retain_pending_queues
from champions_practice.reachability import (
    ReachabilityStatus,
    finite_public_transition_reachability,
)
from champions_practice.search_worker import FORCED_WAIT_CHOICE
from champions_practice.state_maintenance_audit import transition_failure


def condition_queue_histories(worker, engine, *, particles, own_choice, before, after, deadline):
    witnesses = []

    def progress(children, _excluded):
        witnesses.extend(children)

    update = engine._condition_adaptive(
        worker,
        particles=particles,
        ai_choice=own_choice,
        view=after,
        previous_view=before,
        batches=engine.rng_sample_batches,
        deadline=deadline,
        allow_partial_finite_recovery=True,
        progress_callback=progress,
    )
    # During an owned pivot pause, fresh action evidence may cover only the
    # move still queued. No new opponent command can be selected in a native
    # parent whose ONLY legal opponent command is wait. Enumerate that exact
    # parent continuation, never infer the original hidden selected command.
    request = before.get("request", {})
    if (
        update.particles
        or update.unsupported_public_evidence
        or before.get("phase") != "switch"
        or not any(request.get("forceSwitch", ()))
    ):
        return update
    excluded = set(update.exhaustively_excluded_world_ids)
    matched = set(update.matched_world_ids)
    unresolved = set(update.sampled_unresolved_world_ids)
    leaves = 0
    new_witnesses = 0
    for world_id in sorted(unresolved):
        group = [p for p in particles if p.world_id == world_id]
        all_disproved = True
        for particle in group:
            if perf_counter() >= deadline - 0.5:
                all_disproved = False
                break
            if worker.legal_choices(state=particle.state, side="p1") != [FORCED_WAIT_CHOICE]:
                all_disproved = False
                break
            probe = finite_public_transition_reachability(
                worker,
                state=particle.state,
                side="p2",
                p1_choice=FORCED_WAIT_CHOICE,
                p2_choice=own_choice,
                expected_public_view=after,
                previews=engine.previews,
                max_leaves=256,
                witness_seed_window_attempts=64,
            )
            leaves += probe.leaves_examined
            if probe.evidence.status is ReachabilityStatus.WITNESSED:
                assert probe.child_state is not None and probe.member_lineage is not None
                p1_lineage, p2_lineage = compose_branch_member_lineage(
                    particle,
                    child_state=probe.child_state,
                    raw_lineage=probe.member_lineage,
                )
                witnesses.append(
                    replace(
                        particle,
                        state=probe.child_state,
                        p1_member_lineage=p1_lineage,
                        p2_member_lineage=p2_lineage,
                        history_id=particle.history_id + "|queue-witness",
                    )
                )
                matched.add(world_id)
                new_witnesses += 1
                unresolved.discard(world_id)
                all_disproved = False
                break
            if not probe.evidence.establishes_impossibility:
                all_disproved = False
        if all_disproved:
            excluded.add(world_id)
            unresolved.discard(world_id)
    authoritative = tuple(p for p in particles if p.world_id not in excluded)
    merged = (
        merge_sampled_world_witnesses(authoritative, tuple(witnesses)) if not unresolved else ()
    )
    # Only all represented histories in a queue class can disprove that class;
    # sampled misses and finite-tree exhaustion remain unresolved. These are
    # offline native history IDs, not exclusions of the underlying set.
    return ParticleUpdate(
        particles=merged,
        generated=update.generated + leaves,
        matched=update.matched + new_witnesses,
        deduplicated=update.deduplicated,
        matched_world_ids=tuple(sorted(matched)),
        sampled_unresolved_world_ids=tuple(sorted(unresolved)),
        exhaustively_excluded_world_ids=tuple(sorted(excluded)),
        unsupported_public_evidence=update.unsupported_public_evidence,
        structural_mismatch_paths=update.structural_mismatch_paths,
        finite_reachability_leaves=update.finite_reachability_leaves + leaves,
    )


class QueueShadow:
    def __init__(self, *, team, priors, preview, view, budget, seed, capacity=24):
        self.engine = BeliefDecisionEngine(
            ".",
            battle_format=CHAMPIONS_FORMAT,
            ai_team=team,
            opponent_priors=priors,
            world_limit=4,
            max_particles=4,
            particle_seed=seed,
        )
        self.engine.initialize_preview(view=view, ai_choice=preview)
        self.budget = budget
        self.capacity = capacity
        self.failure = None if self.engine.particles else "opening-no-match"

    def checkpoint(self, worker, view, menu):
        if self.failure:
            return False
        wanted = public_observation_signature(view)
        for particle in self.engine.particles:
            projected = worker.state_view(
                state=particle.state, side="p2", previews=self.engine.previews
            )
            if public_observation_signature(projected) != wanted:
                self.failure = "queue-shadow-public-mismatch"
            elif sorted(worker.legal_choices(state=particle.state, side="p2")) != sorted(menu):
                self.failure = "queue-shadow-own-menu-mismatch"
        return self.failure is None

    def advance(self, *, own_choice, before, after, index):
        if self.failure:
            return {"failure": self.failure, "attempted": False}
        start = perf_counter()
        deadline = start + self.budget
        tagged = []
        original_ids = {}
        # Temporarily treat every retained set/queue class as a separate
        # hypothesis. A witness for one queue cannot certify a different queue.
        # Exclusions apply only to these sampled native histories, never all
        # publicly possible histories of the underlying set.
        for particle in self.engine.particles:
            tag = (
                particle.world_id
                + "|queue:"
                + hashlib.sha256(pending_queue_key(particle.state).encode()).hexdigest()
            )
            original_ids[tag] = particle.world_id
            tagged.append(replace(particle, world_id=tag))
        try:
            update, timeout = self.engine._run_until_deadline(
                lambda worker: condition_queue_histories(
                    worker,
                    self.engine,
                    particles=tuple(tagged),
                    own_choice=own_choice,
                    before=before,
                    after=after,
                    deadline=deadline,
                ),
                deadline=deadline,
            )
            self.failure = transition_failure(update, timeout)
        except (RuntimeError, ValueError, TimeoutError) as error:
            update = None
            self.failure = "conditioning-error:" + type(error).__name__
        row = {
            "attempted": True,
            "failure": self.failure,
            "elapsed_seconds": perf_counter() - start,
            "queue_classes_before": len(original_ids),
        }
        if update is not None:
            row.update(
                generated=update.generated,
                matched=update.matched,
                witnessed_queue_classes=len(update.matched_world_ids),
                unresolved_queue_classes=len(update.sampled_unresolved_world_ids),
                disproved_sampled_queue_classes=len(update.exhaustively_excluded_world_ids),
                finite_leaves=update.finite_reachability_leaves,
                mismatch_paths=list(update.structural_mismatch_paths),
            )
            if not self.failure:
                restored = tuple(
                    replace(p, world_id=original_ids[p.world_id]) for p in update.particles
                )
                retained = retain_pending_queues(restored, limit=self.capacity, seed=index + 53)
                row.update(
                    queue_classes_after=retained.classes, retained_particles=len(retained.particles)
                )
                self.failure = retained.unresolved_reason
                row["failure"] = self.failure
                if not self.failure:
                    self.engine.particles = retained.particles
        # Last-good states remain diagnostic only after any unresolved result.
        return row
