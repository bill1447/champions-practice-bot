"""Inspectable, public-only match plans; never score or select battle actions.

The preferred anchor is a declared working hypothesis, not a solved win condition.
Requirements remain questions until tactical evidence certifies them.
"""

from dataclasses import asdict

from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.strategy import (
    DesiredBoard, ResourcePurpose, StrategicPlan, assess_strategic_position,
    generate_strategic_plans,
)


def ident(value):
    return ''.join(c for c in str(value).lower() if c.isalnum())


def moves(mon):
    return {ident(m) for m in mon.get('moves', [])}


def resource_id(species):
    return ident(species).removesuffix('mega')


def attack_type(mon, move, catalog):
    kind = catalog.moves.get(move, {}).get('type')
    if kind == 'Normal' and (ident(mon.get('ability')) == 'pixilate' or
                            ident(mon.get('item')) == 'gardevoirite'):
        return 'Fairy'
    return kind


def diagnose_match(view, catalog, *, previous=None):
    """Reassess using only this side's view and the pinned public mechanics catalog."""
    belief = build_public_opponent_belief(view)
    assessment = assess_strategic_position(view)
    team = view['player']['team']
    living = [m for m in team if not m.get('fainted', False)]
    candidates = []
    for mon in living:
        attacks = [m for m in moves(mon) if catalog.moves.get(m, {}).get('power', 0) > 0]
        if not attacks:
            continue
        spread = [m for m in attacks if m in {'hypervoice', 'expandingforce', 'rockslide', 'earthquake', 'heatwave', 'surf'}]
        # This rule only declares an inspectable starting hypothesis; no battle action
        # is ranked. Continuity avoids changing the declared plan on small HP changes.
        retained = previous is not None and resource_id(previous['anchor']) == resource_id(mon['species'])
        candidates.append((retained, len(spread), len(attacks), mon.get('hp_percent', 0), mon['species'], mon))
    anchor = max(candidates, key=lambda c: c[:5])[-1] if candidates else None
    anchor_name = anchor['species'] if anchor else None
    anchor_moves = moves(anchor) if anchor else set()
    psychic = 'expandingforce' in anchor_moves
    hypervoice = 'hypervoice' in anchor_moves
    mega_fairy = hypervoice and anchor is not None and (
        ident(anchor.get('item')) == 'gardevoirite' or ident(anchor.get('ability')) == 'pixilate')
    attack_types = {attack_type(anchor, m, catalog) for m in anchor_moves
                    if catalog.moves.get(m, {}).get('power', 0) > 0}
    if mega_fairy:
        attack_types.discard('Normal')
        attack_types.add('Fairy')
    main_types = {'Psychic'} if psychic else set(attack_types)
    if mega_fairy:
        main_types.add('Fairy')
    names = {ident(m['species']): m for m in living}
    tools = []
    for mon in living:
        available = moves(mon)
        for role, options in (
            ('redirection', {'followme', 'ragepowder'}),
            ('speed control', {'trickroom', 'tailwind', 'icywind', 'electroweb'}),
            ('temporary defense', {'protect', 'detect'}),
            ('pivot', {'uturn', 'voltswitch', 'partingshot', 'flipturn'}),
            ('setup denial', {'imprison', 'taunt'}),
        ):
            if available & options:
                tools.append({'resource': mon['species'], 'role': role,
                              'moves': sorted(available & options)})
        if ident(mon.get('ability')) == 'psychicsurge' or 'psychicterrain' in available:
            tools.append({'resource': mon['species'], 'role': 'Psychic Terrain', 'moves': []})
    requirements = [
        {'name': 'anchor available', 'state': 'observed' if anchor else 'failed',
         'evidence': f'{anchor_name} is living.' if anchor else 'No living damage anchor identified.'},
        {'name': 'safe attacking window', 'state': 'unverified',
         'evidence': 'Compare attack/KO, partner intervention, trade, switch and defense against plausible replies.'},
        {'name': 'favorable speed order', 'state': 'unverified',
         'evidence': 'Trick Room reverses order; it is useful only when the resulting order advances this plan.'},
    ]
    if psychic:
        terrain = ident(view['field'].get('terrain')) == 'psychicterrain'
        requirements.append({'name': 'Psychic Terrain for Expanding Force',
            'state': 'observed' if terrain else 'missing',
            'evidence': 'Terrain alone does not prove the attacker is grounded, duration, or safe execution.'})
    blockers = []
    for foe in belief.pokemon:
        if foe.fainted:
            continue
        resistant = sorted(t for t in main_types if catalog.effectiveness(t, foe.species) < 1)
        if not resistant:
            continue
        answers = []
        for mon in living:
            for move in moves(mon):
                data = catalog.moves.get(move, {})
                if data.get('power', 0) > 0 and catalog.effectiveness(attack_type(mon, move, catalog), foe.species) > 1:
                    answers.append(f"{mon['species']}: {move}")
        blockers.append({'species': foe.species,
            'presence': 'active' if foe.active_slot is not None else 'seen reserve' if foe.seen else 'preview possibility',
            'resisted_attack_types': resistant, 'possible_answers': sorted(answers),
            'typing_multipliers': {t: catalog.effectiveness(t, foe.species) for t in resistant},
            'qualification': 'Base typing, assuming our declared Mega/Pixilate transition where applicable; not a damage, PP, ability, KO, or selected-four certificate.'})
    possible = {ident(p.species): p for p in belief.pokemon if not p.fainted}
    opponent_plans = []
    for setter, attacker, weather, ability in (
        ('tyranitar', 'excadrill', 'sandstorm', 'Sand Rush'),
        ('pelipper', 'basculegion', 'raindance', 'Swift Swim'),
    ):
        if setter in possible and attacker in possible:
            opponent_plans.append({'objective': f'Enable {possible[attacker].species} with {weather}.',
                'status': 'hypothesis',
                'evidence': f'Both species are in public preview; weather currently {view["field"].get("weather")}.',
                'unknowns': f'Selection beyond observed entrants, {ability}, items, moves and effective speed remain unverified.',
                'test': 'Compare removing the attacker, denying weather, changing speed order and racing; do not automatically stall.'})
    for foe in belief.pokemon:
        if foe.fainted:
            continue
        control = sorted({ident(m) for m in foe.revealed_moves} & {'trickroom', 'tailwind'})
        if control:
            opponent_plans.append({'objective': f'{foe.species} may reuse revealed speed control.',
                'status': 'hypothesis', 'evidence': control,
                'test': 'Compare denial, exploitation, stalling, or finishing before control matters.'})
    if assessment.speed_control.opponent_tailwind:
        opponent_plans.append({'objective': 'Convert active opposing Tailwind into attacks.',
            'status': 'observed condition, inferred intent', 'evidence': 'Public side condition: Tailwind.',
            'test': 'Verify whether waiting buys a favorable turn; attacking may be better.'})
    if not opponent_plans:
        opponent_plans.append({'objective': 'Opponent win condition unresolved.', 'status': 'unknown',
            'evidence': 'No supported weather pairing or revealed speed-control plan identified.'})
    if any(ident(p.species) == 'rillaboom' for p in belief.pokemon if not p.fainted) and psychic:
        blockers.append({'species': 'Rillaboom', 'presence': 'public preview/reveal',
            'qualification': 'Possible terrain replacement if Grassy Surge is available; ability and entry timing require evidence.',
            'possible_answers': ['Compare preserving/re-entering our setter with attacking immediately.']})
    desired = ('safe-attacking-window', 'answers-weakened-or-bypassed') + (('psychicterrain-and-grounded-attacker',) if psychic else ())
    plan = StrategicPlan(name=f'working-finish-{ident(anchor_name)}',
        objective=f'Create repeatable or decisive attacks for {anchor_name}.' if anchor else 'Find a viable remaining attacker or material trade.',
        desired_board=DesiredBoard(required_conditions=desired,
            required_resources=(anchor_name,) if anchor else (),
            resource_purposes=(ResourcePurpose(anchor_name, 'provisional finisher'),) if anchor else ()),
        required_resources=(anchor_name,) if anchor else (),
        preserve=(anchor_name,) if anchor else (),
        rationale=('Working anchor chosen by continuity, spread coverage, damaging moves, then HP; not proven optimal.',),
        failure_conditions=('anchor-lost-without-winning-trade',))
    previous_anchor = previous['anchor'] if previous else None
    update = 'initial hypothesis' if previous is None else 'retained living anchor' if resource_id(previous_anchor) == resource_id(anchor_name) else 'replan: previous anchor fainted, unselected, or no longer a damage candidate'
    relevant = [b['species'] for b in blockers if b.get('presence') == 'active']
    current = 'Test an immediate finish or decisive trade before spending a turn on setup or defense.'
    if psychic and ident(view['field'].get('terrain')) != 'psychicterrain':
        current += ' Compare restoring Psychic Terrain with attacking through other available damage.'
    if relevant:
        current += ' Test removing or bypassing active typing answers: ' + ', '.join(relevant) + '.'
    current += ' If neither finishes, certify a safe attacking window and its next-turn payoff.'
    return {'turn': assessment.turn, 'phase': assessment.phase, 'anchor': anchor_name,
        'update': update, 'plan': asdict(plan), 'requirements': requirements,
        'blockers': blockers, 'available_answers': tools, 'opponent_plans': opponent_plans,
        'current_objective': current,
        'trade_rule': 'No support sacrifice is approved by this report. Compare what its loss enables, remaining terrain/speed access, and a no-sacrifice alternative.',
        'defense_rule': 'Protect or stalling needs a named payoff next turn; compare the sacrificed attack and opponent setup/repositioning.',
        'reassessment': ['Can the opponent finish first?', 'Is this anchor still the best win condition?',
            'Can remaining damage bypass a blocker without removing it?', 'What does the next attacking window require?'],
        'existing_plan_candidates': [asdict(p) for p in generate_strategic_plans(assessment, limit=None)],
        'uncertainty': ['No opponent hidden set, actual reply, winner or native state is accepted.',
            'Typing and role availability do not establish tactical feasibility.',
            'Psychic Terrain protects grounded allies from opposing priority; grounding and terrain timing need verification.',
            'No action selection, move bonus, plan feasibility score or gameplay strength claim.'],
        'living_resources': sorted(names)}
