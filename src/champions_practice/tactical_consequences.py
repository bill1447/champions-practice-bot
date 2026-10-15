"""Offline bounded native consequences over explicit hypothetical worlds.

No sessions, hidden-state reconstruction or live-state capability. Callers must
provide admitted public hypotheses and the authoritative root action menu.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import json
from statistics import fmean
from time import perf_counter

from .agent_v2.policy import observe, rank_action
from .belief_search import ExactBeliefWorldState
from .exact_search import score_exact_summary_breakdown


@dataclass(frozen=True)
class TacticalLimits:
    root_actions: int = 10
    responses: int = 4
    next_actions: int = 4
    rng_seeds: tuple[str, ...] = ('sodium,'+'12345678'*8,)
    branch_limit: int = 4096
    phase_limit: int = 6

    def __post_init__(self):
        if min(self.root_actions, self.responses, self.next_actions, self.branch_limit, self.phase_limit) < 1 or not self.rng_seeds:
            raise ValueError('positive tactical limits and explicit hypothetical RNG samples required')


@dataclass(frozen=True)
class TacticalResult:
    action: str
    status: str
    ranking: tuple[dict, ...]
    branch_count: int
    continuation_groups: int
    elapsed_seconds: float
    reason: str = ''
    assumptions: tuple[str, ...] = (
        'Native mechanics are exact only within each supplied hypothetical world.',
        'Opponent sets, candidate coverage and RNG samples are incomplete.',
        'Position utility is not a calibrated win probability.',
        'Two-turn horizon does not establish long-term strategy or playing strength.',
    )


def observation_key(view):
    """An information set uses owned request and public facts, never world IDs."""
    request = dict(view.get('request', {}))
    request.pop('rqid', None)
    # Native state_view is the sanitized boundary. Unknown root keys are ignored.
    return json.dumps({k: request if k == 'request' else view.get(k)
                       for k in ('turn', 'phase', 'field', 'player', 'opponent',
                                 'request', 'public_event_delta', 'ended')}, sort_keys=True)


def shortlist(view, legal, catalog, limit, incumbent=None):
    """Move scoring proposes candidates; it never chooses the final plan.

    Reserve per-slot defense, speed control/disruption and switching before
    filling with alternate attacks. Every returned joint command is native legal.
    """
    if not legal:
        raise ValueError('empty hypothetical menu')
    board = observe(view, legal, deadline=perf_counter()+60)
    ordered = sorted(legal, key=lambda a: rank_action(a, board, catalog).score, reverse=True)
    mega_profile = tuple('mega' in p.split() for p in (incumbent or ordered[0]).split(','))
    ordered.sort(key=lambda a: tuple('mega' in p.split() for p in a.split(',')) != mega_profile)
    chosen = [incumbent] if incumbent in legal else [ordered[0]]
    commands = {a: [p.strip().split() for p in a.split(',')] for a in ordered}
    # Reserve complementary plans such as Trick Room + Protect, rather than
    # always pairing every support move with the highest-scoring attack.
    for setup in ('trickroom', 'tailwind', 'followme', 'ragepowder'):
        match = next((a for a in ordered if any(len(p) > 1 and p[1] == setup for p in commands[a]) and
                      any(len(p) > 1 and p[1] in {'protect', 'detect'} for p in commands[a])), None)
        if match and match not in chosen:
            chosen.append(match)
    for predicate in (
        lambda p: len(p) > 1 and p[0] == 'move' and p[1] in {'protect', 'detect'},
        lambda p: len(p) > 1 and p[0] == 'move' and p[1] in {'trickroom', 'tailwind'},
        lambda p: len(p) > 1 and p[0] == 'move' and p[1] in {'followme', 'ragepowder', 'fakeout', 'helpinghand', 'wideguard', 'partingshot'},
        lambda p: p and p[0] == 'switch',
    ):
        for slot in range(len(board.owned_active)):
            match = next((a for a in ordered if a not in chosen and slot < len(commands[a]) and predicate(commands[a][slot])), None)
            if match:
                chosen.append(match)
    chosen.extend(a for a in ordered if a not in chosen)
    return tuple(chosen[:limit])


class _Incomplete(Exception):
    pass


@dataclass
class _Node:
    state: dict
    summary: dict | None
    world: int
    weight: float
    history: tuple[str, ...] = ()
    view: dict | None = field(default=None, repr=False)
    leaf_breakdown: dict | None = field(default=None, repr=False)
    leaf_positions: tuple[dict, ...] = field(default=(), repr=False)


def _leaf_breakdown(summary, side):
    """Telemetry only: decompose the existing score without changing its value."""
    value = score_exact_summary_breakdown(summary, side)
    result = {name: getattr(value, name) for name in ('total', 'terminal', 'material', 'position', 'speed')}
    def material_parts(team):
        alive = [m for m in team['pokemon'] if m['hp'] > 0 and not m['fainted']]
        return (1000.0*len(alive), sum(100.0*m['hp']/max(1, m['maxhp']) for m in alive),
                -20.0*sum(bool(m.get('status')) for m in alive))
    other = 'p2' if side == 'p1' else 'p1'
    own, enemy = material_parts(summary[side]), material_parts(summary[other])
    result.update({name: 0.0 if value.terminal else a-b
                   for name, a, b in zip(('living', 'hp', 'status'), own, enemy, strict=True)})
    return result


def evaluate_consequences(worker, *, worlds: tuple[ExactBeliefWorldState, ...], side,
                          authoritative_actions, incumbent, catalog, deadline,
                          limits=TacticalLimits(), horizon_turns=2, include_leaf_positions=False):
    """Resolve two actual turns, including intervening replacement requests.

    Every sampled first response/RNG outcome is extended. Continuation decisions
    are shared across worlds with identical public observations and own action
    history, preventing a separate hidden-set-specific counterplay in each world.
    Budgets abort the whole comparison and retain the legal incumbent.
    """
    if not worlds or side not in ('p1', 'p2') or incumbent not in authoritative_actions or horizon_turns not in (1, 2):
        raise ValueError('hypotheses, side and authoritative legal incumbent required')
    started = perf_counter()
    other = 'p2' if side == 'p1' else 'p1'
    count, groups = 0, 0
    continuations = Counter()
    continuation_trace = []
    menu_counts = Counter()

    def check(branches=0):
        if perf_counter() >= deadline:
            raise _Incomplete('deadline')
        if count+branches > limits.branch_limit:
            raise _Incomplete('branch limit')

    def view(node):
        if node.view is None:
            check()
            node.view = worker.state_view(state=node.state, side=side)
            check()
        return node.view

    def resolve(node, own, replies):
        nonlocal count
        specs, keys = [], []
        for action in own:
            for reply in replies:
                for rng in limits.rng_seeds:
                    commands = {side: action, other: reply}
                    specs.append({'p1_choice': commands['p1'], 'p2_choice': commands['p2'],
                                  'rng_seed': rng, 'include_state': True})
                    keys.append((action, reply))
        check(len(specs))
        output = worker.branch_many(state=node.state, branches=specs)
        count += len(specs)
        check()
        if len(output) != len(specs):
            raise RuntimeError('incomplete native tactical batch')
        children = []
        for (action, reply), branch in zip(keys, output, strict=True):
            if not isinstance(branch.get('summary'), dict) or not isinstance(branch.get('state'), dict):
                raise RuntimeError('native consequences require summary and hypothetical state')
            children.append((action, reply, _Node(branch['state'], branch['summary'], node.world,
                node.weight, node.history+(action,))))
        return children

    def backup(children, values, action):
        per_reply = defaultdict(list)
        for (candidate, reply, _), value in zip(children, values, strict=True):
            if candidate == action:
                per_reply[reply].append(value)
        return min(fmean(samples) for samples in per_reply.values())

    def component_backup(children, action):
        by_reply = defaultdict(list)
        for candidate, reply, child in children:
            if candidate == action:
                by_reply[reply].append(child.leaf_breakdown)
        worst = min(by_reply, key=lambda reply: fmean(b['total'] for b in by_reply[reply]))
        return {name: fmean(b[name] for b in by_reply[worst]) for name in by_reply[worst][0]}

    def extend(nodes, goal, phases):
        nonlocal groups
        check()
        values = [None]*len(nodes)
        pending = defaultdict(list)
        for index, node in enumerate(nodes):
            if node.summary.get('ended') or int(node.summary['turn']) >= goal:
                values[index] = score_exact_summary_breakdown(node.summary, side).total
                node.leaf_breakdown = _leaf_breakdown(node.summary, side)
                if include_leaf_positions:
                    position = dict(node.summary)
                    parties = node.state.get('sides', [])
                    position['ownMegaAvailability'] = {
                        ''.join(c for c in mon['set']['species'].lower() if c.isalnum()): bool(mon.get('canMegaEvo'))
                        for mon in (parties[int(side[1])-1]['pokemon'] if parties else [])}
                    node.leaf_positions = (position,)
            else:
                pending[(node.history, observation_key(view(node)))].append(index)
        for indexes in pending.values():
            if phases <= 0:
                raise _Incomplete('replacement/pivot phase limit')
            groups += 1
            members = [nodes[i] for i in indexes]
            menus = [worker.legal_choices(state=n.state, side=side) for n in members]
            common = [a for a in menus[0] if all(a in menu for menu in menus[1:])]
            if not common:
                raise _Incomplete('no shared information-set action')
            own = shortlist(view(members[0]), common, catalog, limits.next_actions)
            menu_counts['continuation_legal'] += len(common)
            menu_counts['continuation_selected'] += len(own)
            expanded, lengths = [], []
            for node in members:
                check()
                replies = worker.legal_choices(state=node.state, side=other)
                enemy_view = worker.state_view(state=node.state, side=other)
                selected = shortlist(enemy_view, replies, catalog, limits.responses)
                children = resolve(node, own, selected)
                lengths.append(children)
                expanded.extend(child for _, _, child in children)
            scores = extend(expanded, goal, phases-1)
            by_node, cursor = [], 0
            for children in lengths:
                leaf = scores[cursor:cursor+len(children)]
                cursor += len(children)
                by_node.append({a: backup(children, leaf, a) for a in own})
            # Opponent alternatives are adversarial histories, not invented
            # probabilities. Use one robust continuation for this information set.
            chosen = max(own, key=lambda a: (min(v[a] for v in by_node), fmean(v[a] for v in by_node), -own.index(a)))
            continuations[chosen] += 1
            continuation_trace.append({'history': members[0].history, 'action': chosen,
                'indistinguishable_samples': len(members),
                'comparisons': {a: min(v[a] for v in by_node) for a in own}})
            for index, values_by_action, children in zip(indexes, by_node, lengths, strict=True):
                values[index] = values_by_action[chosen]
                nodes[index].leaf_breakdown = component_backup(children, chosen)
                if include_leaf_positions:
                    grouped = defaultdict(list)
                    for action, reply, child in children:
                        if action == chosen:
                            grouped[reply].append(child)
                    worst = min(grouped, key=lambda r: fmean(c.leaf_breakdown['total'] for c in grouped[r]))
                    nodes[index].leaf_positions = tuple(p for c in grouped[worst] for p in c.leaf_positions)
        return values

    try:
        check()
        roots = [_Node(w.state, None, i, w.weight) for i, w in enumerate(worlds)]
        views = [view(n) for n in roots]
        if len({observation_key(v) for v in views}) != 1:
            raise _Incomplete('root hypotheses disagree with public observation')
        legal = [worker.legal_choices(state=n.state, side=side) for n in roots]
        if any(any(a not in menu for a in authoritative_actions) for menu in legal):
            raise _Incomplete('hypothesis contradicts authoritative own menu')
        own = shortlist(views[0], list(authoritative_actions), catalog, limits.root_actions, incumbent)
        expanded, per_world = [], []
        for node in roots:
            check()
            replies = worker.legal_choices(state=node.state, side=other)
            enemy_view = worker.state_view(state=node.state, side=other)
            selected = shortlist(enemy_view, replies, catalog, limits.responses)
            children = resolve(node, own, selected)
            per_world.append(children)
            expanded.extend(child for _, _, child in children)
        goal = int(views[0]['turn'])+horizon_turns
        leaves = extend(expanded, goal, limits.phase_limit-1)
        per_action = defaultdict(list)
        cursor = 0
        for node, children in zip(roots, per_world, strict=True):
            values = leaves[cursor:cursor+len(children)]
            cursor += len(children)
            immediate = [score_exact_summary_breakdown(child.summary, side).total for _, _, child in children]
            for action in own:
                reply_scores = defaultdict(list)
                first_breakdowns = defaultdict(list)
                leaf_breakdowns = defaultdict(list)
                for (candidate, reply, child), value in zip(children, values, strict=True):
                    if candidate == action:
                        reply_scores[reply].append(value)
                        first_breakdowns[reply].append(score_exact_summary_breakdown(child.summary, side))
                        leaf_breakdowns[reply].append(child.leaf_breakdown)
                per_action[action].append({'world': worlds[node.world].label, 'weight': node.weight,
                    'leaf_utility': backup(children, values, action),
                    'one_turn_utility': backup(children, immediate, action),
                    'sampled_responses': {reply: {'leaf_utility': fmean(scores),
                        **({'leaf_positions': [position for candidate, response, child in children
                            if candidate == action and response == reply for position in child.leaf_positions]}
                           if include_leaf_positions else {}),
                        'leaf_breakdown': {component: fmean(b[component] for b in leaf_breakdowns[reply])
                                           for component in leaf_breakdowns[reply][0]},
                        'first_turn_breakdown': {component: fmean(getattr(b, component) for b in first_breakdowns[reply])
                            for component in ('total', 'terminal', 'material', 'position', 'speed')}}
                        for reply, scores in reply_scores.items()}})
        ranking = []
        for action, outcomes in per_action.items():
            total_weight = sum(v['weight'] for v in outcomes)
            ranking.append({'action': action, 'worst_world_utility': min(v['leaf_utility'] for v in outcomes),
                'weighted_utility': sum(v['weight']*v['leaf_utility'] for v in outcomes)/total_weight,
                'worlds': outcomes})
        ranking.sort(key=lambda r: (-r['worst_world_utility'], -r['weighted_utility'], own.index(r['action'])))
        check()
        ranking[0]['coverage'] = {'root_legal': len(authoritative_actions), 'root_selected': len(own),
            **menu_counts, 'continuation_actions': dict(continuations), 'goal_turn': goal, 'horizon_turns': horizon_turns}
        ranking[0]['continuations'] = [t for t in continuation_trace if t['history'][0] == ranking[0]['action']]
        return TacticalResult(ranking[0]['action'], 'complete', tuple(ranking), count, groups, perf_counter()-started)
    except _Incomplete as error:
        return TacticalResult(incumbent, 'incomplete', (), count, groups, perf_counter()-started, str(error))
