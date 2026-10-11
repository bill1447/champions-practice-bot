"""Ordered, player-visible lifecycle evidence; no native state inputs."""

import json

SURGE_ABILITIES = frozenset({"psychicsurge", "grassysurge", "electricsurge", "mistysurge"})
TRACE_ABILITIES = SURGE_ABILITIES | {"unburden", "pixilate"}


def public_trace_copy(event, actors, abilities=SURGE_ABILITIES):
    """One positively disclosed native Trace copy, with an identified donor."""
    if (len(event) < 6 or event[0] != "-ability" or event[3] != "trace"
            or "[from]:ability:trace" not in event or event[2] not in abilities):
        return None
    donor = next((token[5:] for token in event if token.startswith("[of]:")), None)
    if event[1] not in actors or donor not in actors or donor[:2] == event[1][:2]:
        return None
    return event[2]


def public_trace_plan(view, ledger):
    """Current disclosed Surge copies; switch and native Mega end that copy."""
    ordered = ordered_public_lifecycle(view, ledger)
    if ordered is None:
        return None
    copies = {}
    identities = {}
    for _, event, identities in ordered:
        actor = event[1] if len(event) > 1 else None
        if event[0] in {"switch", "drag", "-mega"}:
            copies.pop(actor, None)
        elif event[0] == "-ability":
            copied = public_trace_copy(event, identities, TRACE_ABILITIES)
            copies.pop(actor, None)
            if "[from]:ability:trace" in event:
                copies[actor] = copied
        elif event[0] in {"-endability", "-transform", "-formechange"} and actor in copies:
            return None
        elif event[0] in {"-item", "-enditem"} and copies.get(actor) == "unburden":
            return None  # Lost-item activation needs a separate opponent speed domain.
    result = []
    for side, prefix, entries in (
        ("player", "p2", view["player"].get("active_details", [])),
        ("opponent", "p1", view["opponent"].get("active", [])),
    ):
        for slot, mon in enumerate(entries):
            actor = prefix + chr(97 + slot)
            if mon and not mon.get("fainted") and actor in copies:
                if copies[actor] is None:
                    return None
                result.append({"side": side, "slot": slot, "species": identities[actor],
                               "ability": copies[actor]})
    return result


def public_opponent_mega_plan(view, ledger):
    """A channel-visible Mega event proves the evolution and its stone."""
    ordered = ordered_public_lifecycle(view, ledger)
    if ordered is None:
        return None
    result = {}
    for _, event, actors in ordered:
        if event[0] != "-mega" or not event[1].startswith("p1"):
            continue
        if len(event) != 4 or event[1] not in actors:
            return None
        species = event[2]
        result[species] = {"species": species, "item": event[3]}
    return list(result.values())


def public_post_residual_switch(view):
    """Only the visible upkeep boundary certifies an empty historical queue."""
    delta = view.get("public_event_delta", {})
    return (view.get("phase") == "switch" and delta.get("turn") == view.get("turn")
            and not delta.get("unsupported") and delta.get("events", [])[-1:] == [["upkeep"]])


def ordered_public_lifecycle(view, ledger):
    if ledger is None or ledger.current_turn != view.get("turn"):
        return None
    snapshots = [(turn, json.loads(payload)) for turn, payload in getattr(ledger, "field_snapshots", ())]
    openings = [snapshot for turn, snapshot in snapshots if turn == 1]
    if not openings:
        return None
    if not set(range(1, view["turn"] + 1)) <= {turn for turn, _ in snapshots}:
        return None
    actors = {}
    for side, prefix in (("player", "p2"), ("opponent", "p1")):
        for slot, species in enumerate(openings[0].get("active_species", {}).get(side, [])):
            if species:
                actors[prefix + chr(97 + slot)] = species
    versions = {}
    ordered = []
    complete = set()
    for observed_turn, snapshot in snapshots:
        delta = snapshot.get("public_event_delta", {})
        if delta.get("unsupported"):
            return None
        turn = delta.get("turn")
        if type(turn) is not int:
            continue
        events = delta.get("events", [])
        previous = versions.get(turn, [])
        if events[:len(previous)] != previous:
            return None
        for event in events[len(previous):]:
            if event[0] in {"switch", "drag"}:
                actors[event[1]] = event[2]
            ordered.append((turn, event, dict(actors)))
        versions[turn] = events
        if snapshot.get("phase") == "move" and observed_turn == turn + 1:
            complete.add(turn)
    # Every completed turn needs its producer's ordered move/switch evidence.
    if not set(range(1, view["turn"])) <= complete:
        return None
    return ordered


STALL_MOVES = frozenset({
    "protect", "detect", "endure", "banefulbunker", "burningbulwark", "kingsshield",
    "maxguard", "obstruct", "silktrap", "spikyshield", "quickguard", "wideguard",
})


def public_protection_plan(view, ledger):
    ordered = ordered_public_lifecycle(view, ledger)
    if ordered is None:
        return None
    counts = {}
    successes = {}
    attempts = {}
    confirmed = set()
    turn_now = 1
    identities = {}

    def finish_turn():
        if set(attempts) - confirmed:
            return False
        for actor in set(counts) | set(attempts):
            counts[actor] = min(6, counts.get(actor, 0) + 1) if successes.get(actor) else 0
        return True

    for turn, event, identities in ordered:
        if turn > view["turn"] or (turn == view["turn"] and not public_post_residual_switch(view)):
            return None  # unresolved partial current-turn effects
        if turn != turn_now:
            if not finish_turn():
                return None
            successes, attempts, confirmed = {}, {}, set()
            turn_now = turn
        kind = event[0]
        actor = event[1] if len(event) > 1 else None
        if kind in {"switch", "drag"}:
            counts[actor] = 0
            successes.pop(actor, None)
            attempts.pop(actor, None)
        elif kind == "move" and event[2] in STALL_MOVES:
            attempts[actor] = attempts.get(actor, 0) + 1
            if attempts[actor] > 1:
                return None  # multi-attempt/called chains need ordered failure domains
        elif kind == "-singleturn" and event[2].removeprefix("move:") in STALL_MOVES:
            if attempts.get(actor) != 1:
                return None
            successes[actor] = True
            confirmed.add(actor)
        elif kind == "-fail" and actor in attempts:
            confirmed.add(actor)
    if not finish_turn():
        return None
    result = []
    for side, prefix, entries in (
        ("player", "p2", view["player"].get("active_details", [])),
        ("opponent", "p1", view["opponent"].get("active", [])),
    ):
        for slot, mon in enumerate(entries):
            if not mon or mon.get("fainted"):
                continue
            actor = prefix + chr(97 + slot)
            species = mon.get("base_species", mon.get("species"))
            known = identities.get(actor)
            # Public Mega forms retain their roster identity.
            def normalize(value):
                return ''.join(c for c in value.lower() if c.isalnum())
            if not known or (normalize(known) not in {normalize(species), normalize(mon["species"])}
                             and normalize(mon["species"]) != normalize(known) + "mega"):
                return None
            if normalize(mon["species"]) == normalize(known) + "mega":
                species = known
            result.append({"side": side, "slot": slot, "species": species,
                           "successes": counts.get(actor, 0)})
    return result
