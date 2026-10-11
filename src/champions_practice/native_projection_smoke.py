"""Offline projection controls; results have no production admission authority.

These historical fixtures exercise native setters in unsupported domains. They
must test production denial separately; matching projections does not certify
latent state. Never use this helper from a controller or search admission path.
"""

from dataclasses import dataclass
from types import SimpleNamespace

from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.belief_worlds import preview_choice_for_world
from champions_practice.current_state_proposals import build_current_state_set_proposals
from champions_practice.current_state_reconstruction import _matches_approved_prior
from champions_practice.present_rebase import _projection_mechanics_rejection


@dataclass(frozen=True)
class ProjectionProbe:
    particles: tuple  # Offline handles only, deliberately not a PresentRebaseReport.
    unresolved_reason: str | None
    rejection_reasons: tuple = ()


def probe_present_projection(worker, *, ledger, current_view, priors,
                             battle_format, ai_team, ai_preview_choice,
                             legal_live=(), max_roots=2, max_particles=4):
    batch = build_current_state_set_proposals(
        ledger=ledger, current_view=current_view, priors=priors, limit=max_roots,
    )
    belief = build_public_opponent_belief(current_view)
    previews = {"p1": list(ledger.preview_species),
                "p2": [mon["species"] for mon in current_view["player"]["team"]]}
    witnesses = []
    reason = batch.missing_prior
    for proposal in batch.proposals:
        if len(witnesses) >= max_particles:
            break
        root = worker.create_state(
            battle_format=battle_format, p1_team=proposal.team_text, p2_team=ai_team,
            p1_preview=preview_choice_for_world(belief, proposal.world),
            p2_preview=ai_preview_choice,
            p1_name=current_view["opponent"]["name"], p2_name=current_view["player"]["name"],
            seed="sodium,00000001000000020000000300000004",
        )
        report = worker.materialize_present_hypotheses(
            state=root, current_view=current_view, limit=min(4, max_particles - len(witnesses)),
        )
        reason = report.get("reason")
        for outcome in report["outcomes"]:
            state = outcome["state"]
            if not _matches_approved_prior(state, proposal):
                reason = "positive-prior-set-mismatch"
                continue
            projected = worker.state_view(state=state, side="p2", previews=previews)
            mismatch = _projection_mechanics_rejection(
                state, projected, current_view=current_view, ledger=ledger,
                legal_live=legal_live, hypothetical_legal=worker.legal_choices(state=state, side="p2"),
            )
            if mismatch:
                reason = mismatch
                continue
            witnesses.append(SimpleNamespace(state=state, authority="offline-projection-only"))
            if len(witnesses) >= max_particles:
                break
    return ProjectionProbe(tuple(witnesses), None if witnesses else reason)


class NoNativeConstruction:
    def __getattr__(self, name):
        raise AssertionError(f"Unsupported fixture attempted native construction: {name}")
