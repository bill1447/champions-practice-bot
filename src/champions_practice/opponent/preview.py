"""Team-preview scoring for 4v4 doubles.

The first version is intentionally transparent. It considers only information that is
public at team preview plus our own known set. It does not inspect hidden opponent moves,
items, abilities, or spreads.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from statistics import mean

from poke_env.battle import MoveCategory, Pokemon


SPEED_CONTROL = {"tailwind", "trickroom"}
REDIRECTION = {"followme", "ragepowder"}
FAKE_OUT = {"fakeout"}
PROTECT_LIKE = {
    "protect",
    "detect",
    "spikyshield",
    "kingsshield",
    "banefulbunker",
    "silktrap",
    "burningbulwark",
    "obstruct",
}

TERRAIN_ABILITIES = {
    "psychicsurge": "psychic",
    "grassysurge": "grass",
    "electricsurge": "electric",
    "mistysurge": "fairy",
}
WEATHER_ABILITIES = {
    "drizzle": "rain",
    "drought": "sun",
    "sandstream": "sand",
    "snowwarning": "snow",
}
WEATHER_SPEED_ABILITIES = {
    "swiftswim": "rain",
    "chlorophyll": "sun",
    "sandrush": "sand",
    "slushrush": "snow",
}


@dataclass(frozen=True)
class PreviewChoice:
    order: tuple[int, int, int, int]
    score: float
    reasons: tuple[str, ...]


def enumerate_preview_orders(team_size: int = 6) -> list[tuple[int, int, int, int]]:
    """Enumerate bring-4/lead-2 choices with unordered leads and unordered backs.

    For six Pokémon this is 15 possible bring-4 sets times 6 lead pairs = 90 choices.
    Indices are 1-based to match Showdown's /team protocol.
    """
    orders: list[tuple[int, int, int, int]] = []
    for bring in combinations(range(1, team_size + 1), 4):
        for leads in combinations(bring, 2):
            backs = tuple(index for index in bring if index not in leads)
            orders.append((leads[0], leads[1], backs[0], backs[1]))
    return orders


def _known_damaging_moves(mon: Pokemon):
    return [
        move
        for move in mon.moves.values()
        if move.category != MoveCategory.STATUS and move.base_power > 0
    ]


def _offensive_pressure(mon: Pokemon, opponent: Pokemon) -> float:
    moves = _known_damaging_moves(mon)
    if not moves:
        return 0.0

    values: list[float] = []
    for move in moves:
        effectiveness = opponent.damage_multiplier(move)
        stab = 1.5 if move.type in mon.types else 1.0
        expected_hits = getattr(move, "expected_hits", 1.0) or 1.0
        values.append(
            move.base_power
            * move.accuracy
            * expected_hits
            * effectiveness
            * stab
        )

    return max(values)


def _defensive_risk(mon: Pokemon, opponent: Pokemon) -> float:
    """Estimate plausible opposing STAB pressure from public typing only."""
    multipliers = [mon.damage_multiplier(type_) for type_ in opponent.types]
    return max(multipliers, default=1.0)


def _individual_matchup(mon: Pokemon, opponents: list[Pokemon]) -> float:
    if not opponents:
        return 0.0

    offense = mean(_offensive_pressure(mon, foe) for foe in opponents) / 100.0
    defense = mean(_defensive_risk(mon, foe) for foe in opponents)

    speed = mon.base_stats.get("spe", 0)
    opposing_speed = mean(foe.base_stats.get("spe", 0) for foe in opponents)
    speed_edge = (speed - opposing_speed) / 100.0

    # Coverage matters most; defensive exposure and raw speed are secondary.
    return offense - 0.70 * defense + 0.20 * speed_edge


def _move_ids(mon: Pokemon) -> set[str]:
    return set(mon.moves)


def _ability_id(mon: Pokemon) -> str:
    return (mon.ability or "").lower().replace(" ", "")


def _pair_synergy(a: Pokemon, b: Pokemon) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    a_moves = _move_ids(a)
    b_moves = _move_ids(b)

    if (a_moves | b_moves) & SPEED_CONTROL:
        score += 0.65
        reasons.append("speed-control")

    if (a_moves | b_moves) & REDIRECTION:
        score += 0.45
        reasons.append("redirection")

    if (a_moves | b_moves) & FAKE_OUT:
        score += 0.35
        reasons.append("fake-out")

    # Two passive leads are usually a poor way to begin a 4v4 game.
    a_attack_count = len(_known_damaging_moves(a))
    b_attack_count = len(_known_damaging_moves(b))
    if a_attack_count == 0 and b_attack_count == 0:
        score -= 1.25
        reasons.append("double-passive")

    # Terrain setter + matching offensive move.
    for setter, partner in ((a, b), (b, a)):
        terrain_type = TERRAIN_ABILITIES.get(_ability_id(setter))
        if terrain_type is None:
            continue
        if any(
            move.type.name.lower() == terrain_type
            and move.category != MoveCategory.STATUS
            for move in partner.moves.values()
        ):
            score += 0.45
            reasons.append(f"{terrain_type}-terrain-offense")

    # Weather setter + speed abuser.
    for setter, partner in ((a, b), (b, a)):
        weather = WEATHER_ABILITIES.get(_ability_id(setter))
        if weather and WEATHER_SPEED_ABILITIES.get(_ability_id(partner)) == weather:
            score += 0.70
            reasons.append(f"{weather}-speed")

    return score, reasons


def score_preview_order(
    order: tuple[int, int, int, int],
    team: list[Pokemon],
    opponents: list[Pokemon],
) -> PreviewChoice:
    selected = [team[index - 1] for index in order]
    lead_a, lead_b = selected[:2]

    score = sum(_individual_matchup(mon, opponents) for mon in selected)
    reasons: list[str] = []

    synergy, synergy_reasons = _pair_synergy(lead_a, lead_b)
    score += synergy
    reasons.extend(synergy_reasons)

    # Reward role diversity across the four. We do not force any one archetype.
    selected_move_ids = [_move_ids(mon) for mon in selected]
    if any(moves & SPEED_CONTROL for moves in selected_move_ids):
        score += 0.35
        reasons.append("bring-speed-control")
    if any(moves & REDIRECTION for moves in selected_move_ids):
        score += 0.20
        reasons.append("bring-redirection")

    # Encourage at least one Protect-capable Pokémon without treating Protect as mandatory.
    protect_count = sum(bool(moves & PROTECT_LIKE) for moves in selected_move_ids)
    score += min(protect_count, 2) * 0.08

    return PreviewChoice(order=order, score=score, reasons=tuple(reasons))


def choose_team_preview(
    team: list[Pokemon],
    opponents: list[Pokemon],
) -> tuple[PreviewChoice, list[PreviewChoice]]:
    """Score all valid bring-4/lead-2 choices and return the best plus ranking."""
    candidates = [
        score_preview_order(order, team, opponents)
        for order in enumerate_preview_orders(len(team))
    ]
    candidates.sort(key=lambda choice: (choice.score, choice.order), reverse=True)
    return candidates[0], candidates
