"""Production support gate for fresh present-state construction.

Projection equality does not establish latent native timers or protection
chains. Until public-domain construction is implemented, these states remain
unsupported, not impossible. No simulator state or private counters enter here.
"""

from __future__ import annotations

import json


def opening_terrain_plan(view: dict, ledger=None) -> dict | None:
    """Observed native ability starts or continuous public opening terrain."""
    terrain = view.get("field", {}).get("terrain")
    if not terrain or ledger is None or ledger.current_turn != view.get("turn"):
        return None
    snapshots = getattr(ledger, "field_snapshots", ())
    parsed = [(turn, json.loads(payload)) for turn, payload in snapshots if turn >= 1]
    if any(snapshot.get("public_event_delta", {}).get("unsupported")
           for _, snapshot in parsed):
        return None
    start = None
    seen_starts = set()
    for observed_turn, snapshot in parsed:
        delta = snapshot.get("public_event_delta", {})
        for event in delta.get("events", []):
            if len(event) < 2 or event[:2] != ["-fieldstart", "move:" + terrain]:
                continue
            key = (delta.get("turn"), tuple(event))
            if key in seen_starts:
                continue
            seen_starts.add(key)
            source = next((token[5:] for token in event if token.startswith("[of]:")), "")
            ability = next((token[15:] for token in event
                            if token.startswith("[from]:ability:")), "")
            if source not in {"p1a", "p1b", "p2a", "p2b"} or ability not in {
                "psychicsurge", "grassysurge", "electricsurge", "mistysurge",
            } or snapshot.get("terrain") != terrain:
                return None
            side = "player" if source.startswith("p2") else "opponent"
            species = snapshot.get("active_species", {}).get(side, [None, None])[
                0 if source.endswith("a") else 1
            ]
            if not species or type(delta.get("turn")) is not int:
                return None
            start = (observed_turn, delta["turn"], side, species, ability)
    if start is not None:
        observed_turn, source_turn, side, species, ability = start
        recent = [(turn, snapshot) for turn, snapshot in parsed if turn >= observed_turn]
        if any(snapshot.get("terrain") != terrain for _, snapshot in recent) or {
            turn for turn, _ in recent
        } != set(range(observed_turn, view["turn"] + 1)):
            return None
        return {"opening_terrain": terrain, "residual_turns": view["turn"] - source_turn,
                "source_side": side, "source_species": species, "source_ability": ability}
    if any(snapshot.get("terrain") != terrain for _, snapshot in parsed) or {
        turn for turn, _ in parsed
    } != set(range(1, view["turn"] + 1)):
        return None
    for record in ledger.records:
        if record.kind != "public_event_delta":
            continue
        delta = json.loads(record.payload)
        if delta.get("unsupported"):
            return None
        for event in delta["events"]:
            if event and event[0] == "-fieldstart" and any(
                "terrain" in str(token).lower() for token in event[1:]
            ):
                return None
    return {"opening_terrain": terrain, "residual_turns": view["turn"] - 1}


# Pinned moves.ts: stallingMove users plus Quick/Wide Guard, which also call
# addVolatile('stall'). Failed/called/prevented attempts are conservatively
# unsupported; this gate never infers a reset from a command or failure tag.
PROTECTION_CHAIN_MOVES = frozenset({
    "protect", "detect", "endure", "banefulbunker", "burningbulwark",
    "kingsshield", "matblock", "maxguard", "obstruct", "silktrap", "spikyshield",
    "quickguard", "wideguard",
})


def unsupported_present_mechanics(view: dict, ledger=None) -> str | None:
    """Return a fixed public-only reason before spawning a search worker.

    This applies to fresh midgame hypotheses, not turn-one native openings or
    exact live-session forks. The complete latest execution delta is required:
    missing history cannot certify absence of a protection chain. A retained
    older delta is not evidence for the just-completed turn.
    """
    field = view.get("field")
    player = view.get("player")
    opponent = view.get("opponent")
    if not all(isinstance(part, dict) for part in (field, player, opponent)):
        return "unsupported-public-effect-projection"
    if not {"weather", "terrain", "pseudo_weather"} <= field.keys():
        return "unsupported-public-effect-projection"
    if field["weather"] or field["pseudo_weather"] or (
        field["terrain"] and opening_terrain_plan(view, ledger) is None
    ):
        return "unsupported-public-effect-duration"
    for side in (player, opponent):
        if not isinstance(side.get("side_conditions"), list):
            return "unsupported-public-effect-projection"
        # Unknown side effects are deliberately not presumed permanent. The
        # current projection also lacks hazard layer counts, so admitting them
        # as exact present mechanics would require a separate proof.
        if side["side_conditions"]:
            return "unsupported-public-effect-duration"

    delta = view.get("public_execution_delta")
    turn = view.get("turn")
    if (
        type(turn) is not int or turn < 2
        or not isinstance(delta, dict)
        or type(delta.get("turn")) is not int or delta["turn"] != turn - 1
        or not isinstance(delta.get("actions"), list) or not delta["actions"]
    ):
        return "unsupported-public-protection-history"
    for action in delta["actions"]:
        if not isinstance(action, dict):
            return "unsupported-public-protection-history"
        if action.get("outcome") not in {"executed", "prevented"}:
            return "unsupported-public-protection-history"
        move = action.get("move") if action["outcome"] == "executed" else action.get(
            "attempted_move"
        )
        if action["outcome"] == "prevented" and action.get("reason") in {
            "flinch", "par", "slp", "frz", "recharge", "truant",
        }:
            # Native cant executes no move: it cannot refresh stall, and the
            # preceding turn's duration-1 stall expires on this residual.
            continue
        if move in PROTECTION_CHAIN_MOVES:
            return "unsupported-public-protection-chain"
        # A prevented unidentified action cannot prove chain state either.
        if not isinstance(move, str) or not move:
            return "unsupported-public-protection-history"
    return None
