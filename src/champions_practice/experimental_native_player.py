"""Experimental public-only full-game native player; V2 remains the incumbent.

The player has no live-session handle. Every native state is a hypothesis built
from its owned team, public observations and a separately frozen prior catalog.
"""

from dataclasses import asdict
import hashlib
from time import perf_counter

from .agent_v2 import observe
from .belief_controller import BeliefDecisionEngine, _pin_known_team_genders
from .belief_search import ExactBeliefWorldState
from .config import CHAMPIONS_FORMAT
from .current_state_constraints import PublicConstraintLedger
from .plan_feasibility import compare_routes
from .present_rebase import build_present_rebase
from .public_origin import PublicOriginWorker
from .strategic_diagnostic import diagnose_match
from .tactical_consequences import TacticalLimits, evaluate_consequences, observation_key


def roster(text):
    return [c.splitlines()[0].split(' @ ')[0].removesuffix(' (M)').removesuffix(' (F)')
            for c in text.strip().split('\n\n')]


class PreviewWorker:
    def __init__(self, worker, previews):
        self.worker, self.previews = worker, previews

    def state_view(self, *, state, side):
        return self.worker.state_view(state=state, side=side, previews=self.previews)

    def legal_choices(self, **kwargs):
        return self.worker.legal_choices(**kwargs)

    def branch_many(self, **kwargs):
        return self.worker.branch_many(**kwargs)


class ExperimentalNativePlayer:
    """Consumes canonical p2 public views, including nonactionable checkpoints.

    Opening priors are explicit team-family hypotheses, never the live team.
    Midgame proposals use the approved species/set catalog. Neither is exhaustive.
    """

    def __init__(self, project_root, *, own_team, opening_prior, priors, catalog,
                 incumbent_policy, budget_seconds=8):
        if not 0 < budget_seconds <= 8:
            raise ValueError('experimental budget must be within eight seconds')
        self.project_root = project_root
        self.own_team, self.opening_prior = own_team, opening_prior
        self.priors, self.catalog = priors, catalog
        self.incumbent_policy, self.budget_seconds = incumbent_policy, budget_seconds
        self.ledger = None
        self.previous_plan = None

    def _bounded(self, operation, deadline):
        # Reuse the existing abortable native process lifecycle, without running
        # the belief controller's conditioning or decision cycles/budgets.
        return BeliefDecisionEngine._run_until_deadline(self, operation, deadline=deadline)

    def _opening(self, worker, view, deadline):
        own = _pin_known_team_genders(self.own_team, view['request'])
        scoped = PreviewWorker(worker, {'p1': view['opponent']['preview_species'], 'p2': roster(own)})
        worlds = []
        for hypothesis in range(2):
            enemy = self.opening_prior.replace('Life Orb', 'Sitrus Berry') if hypothesis else self.opening_prior
            for sample in range(16):
                if perf_counter() >= deadline:
                    return scoped, (), 'opening-conditioning-deadline'
                state = worker.create_state(battle_format=CHAMPIONS_FORMAT,
                    p1_team=enemy, p2_team=own,
                    p1_name=view['opponent']['name'], p2_name=view['player']['name'],
                    p1_preview='team 1234' if hypothesis == 0 else 'team 1256', p2_preview='team 1234',
                    seed='sodium,'+hashlib.sha256(f'public-root:{hypothesis}:{sample}'.encode()).hexdigest())
                if observation_key(scoped.state_view(state=state, side='p2')) == observation_key(view):
                    worlds.append(ExactBeliefWorldState(state, 1, f'public-prior-{hypothesis}'))
                    break
        return scoped, tuple(worlds) if len(worlds) == 2 else (), 'opening-hypothesis-rejected'

    def decide(self, view, legal):
        started = perf_counter()
        deadline = started + self.budget_seconds
        if not legal:
            raise ValueError('authoritative legal menu required')
        incumbent = self.incumbent_policy(observe(view, legal, deadline=deadline), self.catalog).action
        if incumbent not in legal:
            raise ValueError('V2 incumbent outside authoritative menu')
        incumbent_seconds = perf_counter()-started
        ledger_error = None
        try:
            self.ledger = (PublicConstraintLedger.from_public_view(view) if self.ledger is None
                           else self.ledger.advance(view))
        except ValueError as error:
            ledger_error = str(error)
        plan = diagnose_match(view, self.catalog, previous=self.previous_plan)
        self.previous_plan = plan
        trace = {'turn': view['turn'], 'phase': view['phase'], 'incumbent': incumbent,
                 'deadline_seconds': self.budget_seconds, 'strategy': plan,
                 'admission_attempted': legal != ['wait'], 'admitted_worlds': 0,
                 'incumbent_seconds': incumbent_seconds,
                 'status': 'fallback', 'reason': '', 'tactical': None}
        action = incumbent
        if legal == ['wait']:
            trace.update(status='nonactionable', reason='forced-wait')
        elif ledger_error is not None:
            trace.update(reason='public-ledger-rejected', error=ledger_error)
        else:
            progress = []
            def operation(worker):
                preparation = perf_counter()
                if view['turn'] == 1 and view['phase'] == 'move':
                    scoped, worlds, reason = self._opening(worker, view, deadline)
                    admission = {'kind': 'public-opening'}
                else:
                    report = build_present_rebase(worker, ledger=self.ledger, current_view=view,
                        priors=self.priors, battle_format=CHAMPIONS_FORMAT,
                        ai_team=_pin_known_team_genders(self.own_team, view['request']),
                        ai_preview_choice='team 1234', legal_live=tuple(legal), max_roots=2, max_particles=2)
                    admission = {k: v for k, v in asdict(report).items() if k != 'particles'}
                    worlds = tuple(ExactBeliefWorldState(p.state, p.weight, p.world_id or str(i))
                                   for i, p in enumerate(report.particles))
                    reason = report.unresolved_reason
                    scoped = PublicOriginWorker(worker, states=[w.state for w in worlds],
                        current_view=view, ledger=self.ledger,
                        previews={'p1': view['opponent']['preview_species'], 'p2': roster(self.own_team)},
                        legal_actions=legal) if worlds else None
                # Publish immutable progress snapshots; an aborting worker never
                # retains a reference to the returned decision telemetry.
                progress.append({'admission': admission, 'admitted_worlds': len(worlds),
                                 'preparation_seconds': perf_counter()-preparation})
                if not worlds:
                    return incumbent, {'status': 'fallback', 'reason': reason}
                result = evaluate_consequences(scoped, worlds=worlds, side='p2',
                    authoritative_actions=legal, incumbent=incumbent, catalog=self.catalog,
                    deadline=deadline, horizon_turns=1, include_leaf_positions=True,
                    limits=TacticalLimits(root_actions=8, responses=3, next_actions=2))
                details = {'tactical': asdict(result), 'status': 'search' if result.status == 'complete' else 'fallback',
                           'reason': result.reason}
                if result.status == 'complete':
                    details['position_assessment'] = compare_routes(result.ranking, view, self.catalog, side='p2')
                return result.action if result.status == 'complete' else incumbent, details

            try:
                result, timed_out = self._bounded(operation, deadline)
                if progress:
                    trace.update(progress[-1])
                if timed_out or result is None:
                    trace.update(status='fallback', reason='shared-decision-deadline')
                else:
                    action, details = result
                    trace.update(details)
            except Exception as error:
                trace.update(status='fallback', reason='native-error:'+type(error).__name__, error=str(error))
        trace.update(action=action, disagreement=action != incumbent, elapsed_seconds=perf_counter()-started)
        if trace['elapsed_seconds'] > self.budget_seconds:
            action = incumbent
            trace.update(action=action, disagreement=False, status='fallback', reason='shared-decision-deadline')
        assert action in legal
        return action, trace
