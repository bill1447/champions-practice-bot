"""Bounded approximate joint outcomes; no native state or calibrated probabilities."""

from dataclasses import dataclass, replace
from itertools import product
from statistics import fmean
from time import perf_counter

from .policy import Decision, OpponentEvidence, PokemonFact, RankedAction, ident, rank_action


@dataclass(frozen=True)
class Part:
    kind: str
    move: str = ""
    target: int | None = None
    incoming: str = ""


@dataclass(frozen=True)
class Response:
    label: str
    parts: tuple[Part, ...]
    priority_weight: float


def parse(action, board):
    parts = []
    for slot, command in enumerate(action.split(",")):
        tokens = command.strip().split()
        if not tokens or tokens[0] in {"pass", "wait"}:
            parts.append(Part("pass"))
        elif tokens[0] == "switch":
            parts.append(Part("switch", incoming=tokens[1]))
        elif tokens[0] == "move":
            move = ident(tokens[1])
            if tokens[1].isdigit() and slot < len(board.owned_active) and board.owned_active[slot]:
                moves = board.owned_active[slot].moves
                index = int(tokens[1]) - 1
                move = ident(moves[index]) if index < len(moves) else move
            target = next((int(t) for t in tokens[2:] if t.lstrip("+-").isdigit()), None)
            parts.append(Part("move", move, target))
        else:
            parts.append(Part("pass"))
    return tuple(parts)


def boost(mon, stat):
    stage = dict(mon.boosts).get(stat, 0)
    return (2 + max(0, stage)) / (2 + max(0, -stage))


def stat_range(mon, stat, catalog):
    known = dict(mon.stats).get(stat)
    if known is not None:
        return known * boost(mon, stat), known * boost(mon, stat)
    base = catalog.base_stats.get(ident(mon.species), {}).get(stat, 80)
    # Pinned Champions flat-stat formula, 0..32 points and nature extrema.
    if stat == "hp":
        return base + 75, base + 107
    return int((base + 20) * .9) * boost(mon, stat), int((base + 52) * 1.1) * boost(mon, stat)


def hp_range(mon, catalog):
    if mon.hp is not None:
        return mon.hp, mon.hp
    lo, hi = stat_range(mon, "hp", catalog)
    percent = mon.hp_percent if mon.hp_percent is not None else 100
    return max(1, lo * percent / 100), max(1, hi * min(100, percent + 1) / 100)


def move_data(move, mon, catalog):
    if move.startswith("generic:"):
        _, move_type, priority = move.split(":")
        return {"category": "Physical" if stat_range(mon, "atk", catalog)[1] >= stat_range(mon, "spa", catalog)[1] else "Special",
                "type": move_type, "power": 45 if int(priority) else 80, "priority": int(priority),
                "accuracy": 100, "target": "normal", "protect": True}
    data = dict(catalog.moves.get(move, {"category": "Status", "type": "Normal", "power": 0,
                                       "priority": 0, "accuracy": 100, "target": "self", "protect": True}))
    if mon:
        data["target"] = dict(mon.move_targets).get(move, data["target"])
    return data


def damage_range(attacker, defender, move, catalog, *, spread=False, weather=None, terrain=None, helping=False):
    data = move_data(move, attacker, catalog)
    if data["category"] == "Status":
        return 0.0, 0.0
    attack_stat, defense_stat = ("atk", "def") if data["category"] == "Physical" else ("spa", "spd")
    attack = stat_range(attacker, attack_stat, catalog)
    defense = stat_range(defender, defense_stat, catalog)
    power = data["power"] or 50
    if move == "weatherball" and weather:
        data["type"] = {"raindance": "Water", "sunnyday": "Fire", "sandstorm": "Rock", "snow": "Ice"}.get(weather, data["type"])
        power *= 2
    if move == "expandingforce" and data["target"] == "allAdjacentFoes" and terrain == "psychicterrain":
        power *= 1.5
    modifier = catalog.effectiveness(data["type"], defender.species)
    if data["type"] in catalog.species.get(ident(attacker.species), []):
        modifier *= 1.5
    if spread:
        modifier *= .75
    if attacker.status == "brn" and data["category"] == "Physical" and ident(attacker.ability) != "guts":
        modifier *= .5
    if weather in {"raindance", "sunnyday"} and data["type"] in {"Water", "Fire"}:
        favored = "Water" if weather == "raindance" else "Fire"
        modifier *= 1.5 if data["type"] == favored else .5
    if helping:
        modifier *= 1.5
    if terrain == "psychicterrain" and data["type"] == "Psychic" and "Flying" not in catalog.species.get(ident(attacker.species), []):
        modifier *= 1.3
    # Widen for rounded formula/modifiers; not certified ability/item/type coverage.
    low = ((22 * power * attack[0] / max(1, defense[1])) / 50 + 2) * modifier * .85 * .8
    high = ((22 * power * attack[1] / max(1, defense[0])) / 50 + 2) * modifier * 1.2
    return low, high


def evidence_for(mon, board):
    return next((e for e in board.opponent_evidence if ident(e.species) == ident(mon.species)), OpponentEvidence(mon.species))


def response_options(mon, board, catalog):
    if mon is None or mon.fainted:
        return [(Part("pass"), 1)]
    evidence = evidence_for(mon, board)
    attacks = [m for m in evidence.revealed_moves if catalog.moves.get(m, {}).get("category") in {"Physical", "Special"}]
    if not attacks:
        move_type = catalog.species.get(ident(mon.species), ["Normal"])[0]
        attacks = [f"generic:{move_type}:0"]
    strongest = max(attacks, key=lambda m: move_data(m, mon, catalog)["power"] or 50)
    choices = [(Part("move", strongest, target), .5) for target in (1, 2)]
    support = set(catalog.support.get(ident(mon.species), ["protect"])) | set(evidence.revealed_moves)
    weight = {"low": .04, "unknown": .18, "high": .5}[evidence.protect_tendency]
    if "protect" not in support:
        weight *= .25  # unknown called/transformed alternatives are not disproved
    choices.append((Part("move", "protect"), weight))
    for move in ("tailwind", "trickroom", "followme", "ragepowder"):
        if move in support:
            choices.append((Part("move", move), .08))
    active_species = {ident(m.species) for m in board.opponents if m}
    bench = next((s for s in board.opponent_preview if ident(s) not in active_species), None)
    if bench:
        choices.append((Part("switch", incoming=bench), .1))
    # Retain a priority threat independently of revealed attack preference.
    priorities = [m for m in attacks if move_data(m, mon, catalog)["priority"] > 0]
    if priorities:
        choices.append((Part("move", priorities[0], 1), .1))
    return choices


def responses(board, catalog):
    groups = [response_options(m, board, catalog) for m in board.opponents]
    result = []
    for combination in product(*groups):
        parts = tuple(p[0] for p in combination)
        switches = [p.incoming for p in parts if p.kind == "switch"]
        if len(switches) != len(set(switches)):
            continue
        weight = 1
        for _, value in combination:
            weight *= value
        label = " / ".join(p.move if p.kind == "move" else p.kind + (":" + p.incoming if p.incoming else "") for p in parts)
        result.append(Response(label, parts, weight))
    return tuple(result)


def simulate(plan, response, board, catalog, *, adverse):
    actors = {}
    for side, team in ((0, board.owned_active), (1, board.opponents)):
        for slot, mon in enumerate(team):
            if mon and not mon.fainted:
                lo, hi = hp_range(mon, catalog)
                actors[side, slot] = {"mon": mon, "hp": lo if (side == 0) == adverse else hi,
                                      "maxhp": mon.maxhp or stat_range(mon, "hp", catalog)[1], "protected": False}
    queue = [(0, i, part) for i, part in enumerate(plan)] + [(1, i, part) for i, part in enumerate(response.parts)]
    room = "trickroom" in board.pseudo_weather
    initial_room = room
    winds = ["tailwind" in board.own_side_conditions, "tailwind" in board.opponent_side_conditions]
    initial_winds = list(winds)
    redirect, helping = {}, set()
    damage = [0.0, 0.0]
    kos = [0, 0]
    blocked, waste, control = 0.0, 0.0, 0.0

    def speed(side, slot):
        actor = actors.get((side, slot))
        if not actor:
            return 0
        mon = actor["mon"]
        if side == 0 and mon.speed is not None:
            value = abs(mon.speed)
        else:
            bounds = stat_range(mon, "spe", catalog)
            value = bounds[0] if adverse == initial_room else bounds[1]
            if initial_winds[side]:
                value *= 2
        if winds[side] and not initial_winds[side]:
            value *= 2
        return -value if room else value

    def ordering(event):
        side, slot, part = event
        mon = actors.get((side, slot), {}).get("mon")
        priority = 6 if part.kind == "switch" else move_data(part.move, mon, catalog)["priority"] if mon else -10
        # Prefer opponent in uncertain speed ties for adverse continuations.
        return priority, speed(side, slot), int(side == (1 if adverse else 0))

    def advantage():
        return sum(speed(0, a) > speed(1, b) for a in range(2) for b in range(2)
                   if (0, a) in actors and (1, b) in actors and actors[0, a]["hp"] > 0 and actors[1, b]["hp"] > 0)

    while queue:
        event = max(queue, key=ordering)
        queue.remove(event)
        side, slot, part = event
        actor = actors.get((side, slot))
        if not actor or actor["hp"] <= 0 or part.kind == "pass":
            continue
        mon = actor["mon"]
        if mon.status in {"slp", "frz"} and (side == 0) == adverse and part.kind != "switch":
            continue  # awakening/thawing history remains an uncertain continuation
        if part.kind == "switch":
            if side == 0:
                index = int(part.incoming) - 1
                incoming = board.owned_team[index]
            else:
                incoming = PokemonFact(part.incoming, 100, False, None)
            lo, hi = hp_range(incoming, catalog)
            actors[side, slot] = {"mon": incoming, "hp": lo if (side == 0) == adverse else hi,
                                  "maxhp": incoming.maxhp or stat_range(incoming, "hp", catalog)[1], "protected": False}
            continue
        data = move_data(part.move, mon, catalog)
        if part.move in {"protect", "detect"}:
            repeated = slot in board.recent_own_protect if side == 0 else evidence_for(mon, board).recent_protect
            actor["protected"] = not (adverse and side == 0 and repeated) and not (not adverse and side == 1 and repeated)
            if side == 0:
                control -= 4  # offensive tempo surrendered, even on success
            continue
        if part.move == "tailwind":
            if not winds[side]:
                winds[side] = True
            continue
        if part.move == "trickroom":
            room = not room
            continue
        if part.move in {"followme", "ragepowder"}:
            redirect[side] = (slot, part.move)
            continue
        if part.move == "helpinghand":
            helping.add((side, 1 - slot))
            continue
        if data["category"] == "Status":
            continue
        spread = data["target"] in {"allAdjacent", "allAdjacentFoes"}
        if spread:
            targets = [(1-side, i) for i in range(2)]
            if data["target"] == "allAdjacent":
                targets.append((side, 1-slot))
        elif part.target is not None and part.target < 0:
            targets = [(side, -part.target-1)]
        else:
            target_slot = (part.target or 1) - 1
            if 1-side in redirect:
                redirected, move = redirect[1-side]
                immune_powder = "Grass" in catalog.species.get(ident(mon.species), []) or ident(mon.item) == "safetygoggles" or ident(mon.ability) == "overcoat"
                if move == "followme" or not immune_powder:
                    target_slot = redirected
            targets = [(1-side, target_slot)]
            selected = targets[0]
            if selected not in actors or actors[selected]["hp"] <= 0:
                targets = [key for key, value in actors.items() if key[0] == 1-side and value["hp"] > 0][:1]
        targets = [t for t in targets if t in actors and actors[t]["hp"] > 0]
        for target in targets:
            defender = actors[target]
            if defender["protected"] and data.get("protect", True):
                blocked += 1 if side == 0 else 0
                continue
            if data["priority"] > 0 and target[0] != side and board.terrain == "psychicterrain" and "Flying" not in catalog.species.get(ident(defender["mon"].species), []):
                continue
            low, high = damage_range(mon, defender["mon"], part.move, catalog,
                spread=spread and len(targets) > 1, weather=board.weather, terrain=board.terrain,
                helping=(side, slot) in helping)
            amount = low if (side == 0) == adverse else high
            accuracy = 100 if board.weather == "raindance" and part.move in {"hurricane", "thunder"} else data["accuracy"]
            if accuracy < 100 and (side == 0) == adverse:
                amount = 0  # retain a miss continuation, without inventing its probability
            spent = min(defender["hp"], amount)
            waste += max(0, amount-defender["hp"]) if side == 0 else 0
            defender["hp"] -= spent
            damage[target[0]] += 100 * spent / max(1, defender["maxhp"])
            if defender["hp"] <= 0:
                kos[target[0]] += 1
            if part.move == "feint":
                defender["protected"] = False
    if room != ("trickroom" in board.pseudo_weather) or winds != initial_winds:
        after_advantage = advantage()
        saved_winds, saved_room = list(winds), room
        winds[:], room = initial_winds, initial_room
        before_advantage = advantage()
        winds[:], room = saved_winds, saved_room
        control += 6 * (after_advantage - before_advantage)
    value = 80 * kos[1] - 100 * kos[0] + .3 * damage[1] - .4 * damage[0] + control
    return {"utility": value, "opponent_kos": kos[1], "own_kos": kos[0],
            "opponent_pressure": round(damage[1], 2), "own_damage": round(damage[0], 2),
            "blocked_attacks": blocked, "wasted_damage": round(waste, 2), "field_utility": control}


def assess(action, board, catalog, scenarios):
    plan = parse(action, board)
    target_counts, pressure, public_pressure = {}, {}, {}
    for slot, part in enumerate(plan):
        mon = board.owned_active[slot] if slot < len(board.owned_active) else None
        if mon and part.kind == "move" and part.target and part.target > 0 and move_data(part.move, mon, catalog)["category"] != "Status":
            target_counts[part.target-1] = target_counts.get(part.target-1, 0) + 1
            target = board.opponents[part.target-1]
            if target:
                damage = damage_range(mon, target, part.move, catalog, weather=board.weather, terrain=board.terrain)
                previous = pressure.get(part.target-1, (0, 0))
                pressure[part.target-1] = (previous[0]+damage[0], previous[1]+damage[1])
                public_mon = replace(mon, moves=(), speed=None, item=None, ability=None,
                                     hp=None, maxhp=None, stats=(), move_targets=())
                public_move = part.move if (slot, part.move) in board.public_own_moves else (
                    "generic:" + catalog.species.get(ident(mon.species), ["Normal"])[0] + ":0")
                public_damage = damage_range(public_mon, target, public_move, catalog,
                                             weather=board.weather, terrain=board.terrain)
                prior = public_pressure.get(part.target-1, (0, 0))
                public_pressure[part.target-1] = (prior[0]+public_damage[0], prior[1]+public_damage[1])
    evaluations = []
    for response in scenarios:
        if perf_counter() >= board.deadline:
            return None
        weight = response.priority_weight
        protected = [i for i, p in enumerate(response.parts) if p.move in {"protect", "detect"}]
        # Responsive opponent: concentrated pressure makes its shield response
        # more salient. Weights are scenario priorities, not probabilities.
        if any(target_counts.get(i, 0) >= 2 for i in protected):
            for i in protected:
                if target_counts.get(i, 0) >= 2 and board.opponents[i]:
                    hp = hp_range(board.opponents[i], catalog)
                    weight *= 3 if public_pressure[i][0] >= hp[1] else 1.8 if public_pressure[i][1] >= hp[0] else 1.2
        low = simulate(plan, response, board, catalog, adverse=True)
        high = simulate(plan, response, board, catalog, adverse=False)
        evaluations.append({"response": response.label, "priority_weight": round(weight, 5),
                            "parts": [{"kind": p.kind, "move": p.move, "target": p.target, "incoming": p.incoming} for p in response.parts],
                            "adverse": low, "favorable": high})
    weighted = sum(e["priority_weight"] * fmean((e["adverse"]["utility"], e["favorable"]["utility"])) for e in evaluations)
    weighted /= sum(e["priority_weight"] for e in evaluations)
    worst = min(e["adverse"]["utility"] for e in evaluations)
    score = .85 * weighted + .15 * worst
    concentrated = any(count >= 2 for count in target_counts.values())
    potential = any(values[1] >= hp_range(board.opponents[i], catalog)[0] for i, values in pressure.items())
    reason = ("high conditional KO potential; concentrated Protect exposure" if potential else
              "concentrated pressure with limited KO potential; Protect exposure") if concentrated else "distributed pressure or positional action"
    analysis = {"action": action, "scenario_mean_utility": round(weighted, 3), "downside_utility": round(worst, 3),
                "risk_score": round(score, 3), "assessment": reason, "guaranteed_ko": False,
                "responses": evaluations, "weights_are_probabilities": False,
                "target_damage_ranges_conditional_hit": {str(i+1): [round(v, 2) for v in values] for i, values in pressure.items()},
                "mechanically_certified": False}
    analysis["response_count"] = len(evaluations)
    analysis["response_coverage_exhaustive"] = False
    analysis["response_forecast_uses_private_owned_stats"] = False
    return RankedAction(action, score, (reason, "joint damage/order/survival estimates are conditional and approximate")), analysis


def candidates(board, catalog, limit=24):
    ordered = sorted(board.legal_actions, key=lambda a: rank_action(a, board, catalog).score, reverse=True)
    selected = list(ordered[:limit])
    # Reserve strategic families before tactical pruning.
    for token in ("protect", "switch", "tailwind", "trickroom", "followme", "ragepowder", "helpinghand"):
        match = next((a for a in ordered if token in a), None)
        if match and match not in selected:
            selected.append(match)
    # A high attack score on one partner must not prune the OTHER partner's
    # shield, or a healthier but badly matched reserve must not hide a switch.
    parsed = {a: parse(a, board) for a in ordered}
    for slot in range(len(board.owned_active)):
        shield = next((a for a in ordered if slot < len(parsed[a]) and parsed[a][slot].move in {"protect", "detect"}), None)
        if shield and shield not in selected:
            selected.append(shield)
        incoming = {parts[slot].incoming for parts in parsed.values() if slot < len(parts) and parts[slot].kind == "switch"}
        for destination in sorted(incoming):
            match = next(a for a in ordered if slot < len(parsed[a]) and parsed[a][slot].kind == "switch" and parsed[a][slot].incoming == destination)
            if match not in selected:
                selected.append(match)
    split = next((a for a in ordered if {p.target for p in parse(a, board) if p.kind == "move"} >= {1, 2}), None)
    spread = next((a for a in ordered if any(p.kind == "move" and slot < len(board.owned_active) and board.owned_active[slot] and
                  move_data(p.move, board.owned_active[slot], catalog)["target"] in {"allAdjacent", "allAdjacentFoes"}
                  for slot, p in enumerate(parse(a, board)))), None)
    for match in (split, spread):
        if match and match not in selected:
            selected.append(match)
    return selected


def decide_joint(board, catalog):
    started = perf_counter()
    if started >= board.deadline:
        return Decision(board.legal_actions[0], (), None, 0, len(board.legal_actions), True, 0,
                        ("deadline incumbent from authoritative menu",))
    scenarios = responses(board, catalog)
    ranked, analyses = [], []
    prepared = candidates(board, catalog)
    for action in prepared:
        if perf_counter() >= board.deadline:
            break
        result = assess(action, board, catalog, scenarios)
        if result is None:
            break
        candidate, analysis = result
        ranked.append(candidate)
        analyses.append(analysis)
    top = tuple(sorted(ranked, key=lambda c: c.score, reverse=True)[:3])
    if not top:
        return Decision(prepared[0], (), None, 0, len(board.legal_actions), True,
                        (perf_counter()-started)*1000, ("risk budget unresolved; public-ranking legal incumbent",))
    chosen = top[0]
    top_actions = {c.action for c in top}
    for family in ("focus", "split", "support"):
        for candidate in sorted(ranked, key=lambda c: c.score, reverse=True):
            parts = parse(candidate.action, board)
            targets = [p.target for p in parts if p.kind == "move" and p.target and p.target > 0]
            matched = (len(targets) == 2 and len(set(targets)) == 1) if family == "focus" else (
                len(set(targets)) == 2) if family == "split" else any(p.kind == "switch" or p.move in {
                    "protect", "detect", "tailwind", "trickroom", "followme", "ragepowder", "helpinghand"} for p in parts)
            if matched:
                top_actions.add(candidate.action)
                break
    return Decision(chosen.action, top, top[0].score-top[1].score if len(top)>1 else None,
        len(ranked), len(board.legal_actions), perf_counter() >= board.deadline,
        (perf_counter()-started)*1000, chosen.reasons,
        assumptions=("Joint outcomes use approximate damage/stat/order ranges, not certified mechanics.",
                     "Scenario weights are uncalibrated priorities, not opponent probabilities.",
                     "Possible/model-consistent KOs are never guaranteed against unknown effects.",
                     "Unmodeled moves, abilities, misses, critical hits and lifecycle effects remain unresolved."),
        joint_analysis=tuple(a for a in analyses if a["action"] in top_actions))
