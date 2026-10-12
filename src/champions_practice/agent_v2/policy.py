"""Public-only board-aware heuristic; scores are utilities, not damage or odds."""

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import subprocess
from time import perf_counter


def ident(value):
    return "".join(c for c in str(value).lower() if c.isalnum())


@dataclass(frozen=True)
class PokemonFact:
    species: str
    hp_percent: float | None
    fainted: bool
    status: str | None
    moves: tuple[str, ...] = ()
    speed: int | None = None
    item: str | None = None
    ability: str | None = None
    boosts: tuple[tuple[str, int], ...] = ()
    hp: int | None = None
    maxhp: int | None = None


@dataclass(frozen=True)
class DecisionInput:
    turn: int
    phase: str
    owned_active: tuple[PokemonFact | None, ...]
    owned_team: tuple[PokemonFact, ...]
    opponents: tuple[PokemonFact | None, ...]
    weather: str | None
    terrain: str | None
    pseudo_weather: tuple[str, ...]
    own_side_conditions: tuple[str, ...]
    legal_actions: tuple[str, ...]
    deadline: float

    def __post_init__(self):
        if not self.legal_actions or not all(isinstance(a, str) and a for a in self.legal_actions):
            raise ValueError("decision requires authoritative nonempty legal actions")
        if not math.isfinite(self.deadline):
            raise ValueError("deadline must be finite monotonic time")
        if any(mon and (mon.moves or mon.speed is not None or mon.item or mon.ability or
                        mon.hp is not None or mon.maxhp is not None)
               for mon in self.opponents):
            raise ValueError("opponent active facts must not contain private set data")


@dataclass(frozen=True)
class RankedAction:
    action: str
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Decision:
    action: str
    alternatives: tuple[RankedAction, ...]
    score_margin: float | None
    evaluated_actions: int
    legal_action_count: int
    deadline_exhausted: bool
    elapsed_ms: float
    explanation: tuple[str, ...]
    assumptions: tuple[str, ...] = (
        "Heuristic utility is neither damage nor win probability.",
        "Species typing is a public Dex assumption; effects, abilities and type changes may invalidate it.",
        "Opponent stats, unrevealed moves, intentions and historical counters remain unknown.",
    )


class PublicCatalog:
    def __init__(self, data):
        self.moves = data["moves"]
        self.species = data["species"]
        self.types = data["types"]
        self.fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    @classmethod
    def load(cls, root=None):
        root = root or Path(__file__).resolve().parents[3]
        result = subprocess.run(["node", str(root / "tools/agent-v2-catalog.js")],
                                capture_output=True, text=True, check=True, timeout=30)
        return cls(json.loads(result.stdout))

    def effectiveness(self, move_type, species):
        factor = 1.0
        for defensive_type in self.species.get(ident(species), []):
            code = self.types.get(defensive_type, {}).get(move_type, 0)
            factor *= {0: 1.0, 1: 2.0, 2: 0.5, 3: 0.0}.get(code, 1.0)
        return factor


def observe(view, legal_actions, *, deadline):
    """Copy explicit allowlisted facts; never retain raw view/request/native state."""
    def fact(mon, *, owned=False):
        if mon is None:
            return None
        return PokemonFact(str(mon["species"]), mon.get("hp_percent"), bool(mon.get("fainted")),
                           mon.get("status"), tuple(mon.get("moves", ())) if owned else (),
                           mon.get("speed") if owned else None,
                           mon.get("item") if owned else None,
                           mon.get("ability") if owned else None,
                           tuple(sorted(mon.get("boosts", {}).items())),
                           mon.get("hp") if owned else None, mon.get("maxhp") if owned else None)
    field, player = view.get("field", {}), view["player"]
    return DecisionInput(view["turn"], view["phase"],
        tuple(fact(m, owned=True) for m in player["active_details"]),
        tuple(fact(m, owned=True) for m in player["team"]),
        tuple(fact(m) for m in view["opponent"]["active"]),
        field.get("weather"), field.get("terrain"), tuple(field.get("pseudo_weather", ())),
        tuple(player.get("side_conditions", ())), tuple(legal_actions), deadline)


def rank_action(action, board, catalog):
    score, reasons = 0.0, []
    for slot, command in enumerate(action.split(",")):
        parts = command.strip().split()
        if not parts:
            continue
        own = board.owned_active[slot] if slot < len(board.owned_active) else None
        if parts[0] == "switch":
            index = int(parts[1]) - 1
            incoming = board.owned_team[index] if index < len(board.owned_team) else None
            score -= 4
            if incoming and own:
                recovery = (incoming.hp_percent or 0) - (own.hp_percent or 0)
                score += max(0, recovery) / 15
                reasons.append("switch utility considers visible own health; incoming damage is unknown")
            continue
        if parts[0] != "move":
            reasons.append("authoritative phase action")
            continue
        move_id = ident(parts[1])
        if parts[1].isdigit() and own:
            index = int(parts[1]) - 1
            move_id = ident(own.moves[index]) if index < len(own.moves) else move_id
        move = catalog.moves.get(move_id)
        if not move:
            reasons.append("unknown move metadata; neutral utility")
            continue
        if move["category"] == "Status":
            value = 0.0
            if move_id == "tailwind":
                value = 13 if "tailwind" not in board.own_side_conditions else -8
                reasons.append("establish own Tailwind" if value > 0 else "avoid redundant Tailwind")
            elif move_id == "trickroom":
                value = -3 if "trickroom" in board.pseudo_weather else 1
                reasons.append("Trick Room speed advantage unresolved; avoid automatic toggling")
            elif move_id in {"followme", "ragepowder", "helpinghand"}:
                value = 5 if len(board.owned_active) > 1 else 0
                reasons.append("support partner; success and survival are not certified")
            elif move_id in {"willowisp", "sleeppowder", "spore", "thunderwave"}:
                value = 6
                reasons.append("status pressure under unknown immunities")
            elif move_id in {"protect", "detect"}:
                value = 1
                reasons.append("Protect lacks a certified response/history model")
            score += value
            continue
        targets = [mon for mon in board.opponents if mon and not mon.fainted]
        target_token = next((p for p in parts[2:] if p.lstrip("+-").isdigit()), None)
        if target_token:
            location = int(target_token)
            if location < 0:
                score -= 100
                reasons.append("avoid deliberate damaging ally target")
                continue
            targets = [board.opponents[location - 1]] if 0 < location <= len(board.opponents) else []
            targets = [m for m in targets if m and not m.fainted]
        if not targets:
            reasons.append("no visible living target")
            continue
        power = move["power"] or 50  # variable-power moves remain approximate
        stab = 1.5 if own and move["type"] in catalog.species.get(ident(own.species), []) else 1
        utility = sum(min(3, catalog.effectiveness(move["type"], target.species)) *
                      (1 + (100 - (target.hp_percent if target.hp_percent is not None else 100)) / 200)
                      for target in targets)
        if len(targets) > 1:
            utility *= 0.75
        score += min(power, 150) / 10 * stab * utility * move["accuracy"] / 100
        if own and own.status == "brn" and move["category"] == "Physical":
            score -= 3
            reasons.append("burn discounts physical pressure; ability exceptions unknown")
        if "mega" in parts:
            score += 0.5
            reasons.append("available Mega receives a provisional utility bonus")
        reasons.append(f"{move_id}: public typing, base power, accuracy and target health proxy")
    return RankedAction(action, score, tuple(reasons))


def decide(board, catalog):
    started = perf_counter()
    # A legal incumbent exists before any ranking. No reconstruction is attempted.
    best = RankedAction(board.legal_actions[0], 0, ("deadline incumbent from authoritative menu",))
    ranked = []
    for action in board.legal_actions:
        if perf_counter() >= board.deadline:
            break
        candidate = rank_action(action, board, catalog)
        ranked.append(candidate)
        if len(ranked) == 1 or candidate.score > best.score:
            best = candidate
    top = tuple(sorted(ranked, key=lambda c: c.score, reverse=True)[:3])
    return Decision(best.action, top, top[0].score - top[1].score if len(top) > 1 else None,
                    len(ranked), len(board.legal_actions), len(ranked) < len(board.legal_actions),
                    (perf_counter() - started) * 1000, best.reasons)
