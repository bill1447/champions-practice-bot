"""Closed contract for fresh-state search, using public evidence only.

An observation/menu match is necessary, but cannot certify persistent native
state. Unknown events, static capabilities and missing history are unresolved.
Rejected hypotheses carry no negative authority about the real opponent.
"""

from dataclasses import dataclass
import json

from champions_practice.public_lifecycle import ordered_public_lifecycle, public_protection_plan
from champions_practice.public_inventory import public_inventory_plan


def sid(value):
    return "".join(c for c in str(value or "").lower() if c.isalnum())


@dataclass(frozen=True)
class MechanicSupport:
    mechanic: str
    classification: str  # supported, absent, unresolved
    evidence: str


@dataclass(frozen=True)
class SupportContract:
    mechanics: tuple[MechanicSupport, ...]

    @property
    def unresolved_reason(self):
        return next(
            (
                f"unsupported-persistent:{entry.mechanic}"
                for entry in self.mechanics
                if entry.classification == "unresolved"
            ),
            None,
        )


# These events restore exact HP, boosts, inventory or stateless move results.
# All other protocol families require an explicit lifecycle decision below.
STATELESS_EVENTS = frozenset(
    {
        "switch",
        "drag",
        "faint",
        "upkeep",
        "-damage",
        "-heal",
        "-sethp",
        "-boost",
        "-unboost",
        "-setboost",
        "-clearboost",
        "-clearallboost",
        "-clearpositiveboost",
        "-clearnegativeboost",
        "-crit",
        "-supereffective",
        "-resisted",
        "-immune",
        "-miss",
        "-notarget",
        "-fail",
        "-nothing",
        "-hitcount",
        "-item",
        "-enditem",
    }
)
# Each supported move either uses current facts only, or has a dedicated native
# lifecycle plan. Stateful moves with public starts are permitted only while
# a complete channel proves their persistent effects have not occurred.
CURRENT_FACT_MOVES = frozenset(
    {
        "splash",
        "tackle",
        "psychic",
        "protect",
        "detect",
        "endure",
        "wideguard",
        "quickguard",
        "followme",
        "trickroom",
        "fakeout",
        "firstimpression",
        "closecombat",
        "rockslide",
        "hypervoice",
        "mysticalfire",
        "expandingforce",
        "armorcannon",
        "grassyglide",
        "woodhammer",
        "highhorsepower",
        "psychicfangs",
        "steelroller",
        "bulletpunch",
        "zenheadbutt",
        "icepunch",
        "direclaw",
        "flareblitz",
        "darkestlariat",
        "partingshot",
        "sleeppowder",
        "sludgebomb",
        "energyball",
        "extremespeed",
        "dragonclaw",
        "earthquake",
        "hydropump",
        "thunderbolt",
        "willowisp",
        "hurricane",
        "weatherball",
        "tailwind",
        "flashcannon",
        "dragonpulse",
        "wavecrash",
        "aquajet",
        "crunch",
        "lowkick",
        "ironhead",
        "flamethrower",
        "imprison",
        "taunt",
        "substitute",
        "confuseray",
        "saltcure",
        "perishsong",
        "toxic",
    }
)
# History-sensitive moves such as Encore, Stomping Tantrum, Last Resort,
# Rage Fist, Retaliate and copying moves deliberately have no admission entry.
CURRENT_FACT_ABILITIES = frozenset(
    {
        "innerfocus",
        "clearbody",
        "lightmetal",
        "levitate",
        "intimidate",
        "toughclaws",
        "pixilate",
        "chlorophyll",
        "swiftswim",
        "sandrush",
        "roughskin",
        "stamina",
        "psychicsurge",
        "grassysurge",
        "electricsurge",
        "mistysurge",
        "trace",
        "flashfire",
        "unburden",
        "drizzle",
        "sandstream",
    }
)
CURRENT_FACT_ITEMS = frozenset(
    {
        "",
        "lifeorb",
        "leftovers",
        "focussash",
        "dragonfang",
        "mysticwater",
        # Pinned native onBasePower Fire multiplier; no counters or lifecycle.
        # Transfers/removals and unsupported moves still require their gates.
        "charcoal",
        "gardevoirite",
        "metagrossite",
        "psychicseed",
        "sitrusberry",
        "lumberry",
        "terrainextender",
        "damprock",
        "smoothrock",
        "babiriberry",
        "chartiberry",
        "chilanberry",
        "chopleberry",
        "cobaberry",
        "colburberry",
        "habanberry",
        "kasibberry",
        "kebiaberry",
        "occaberry",
        "passhoberry",
        "payapaberry",
        "rindoberry",
        "roseliberry",
        "shucaberry",
        "tangaberry",
        "wacanberry",
        "yacheberry",
    }
)


def public_active_tenure_plan(view, ledger):
    """Count native move entries and endTurn boundaries since each public entry.

    Fake Out in the pinned build uses activeMoveActions, not calendar turns.
    A visible cant also entered runMove; a voluntary switch did not. Called
    moves/ambiguous histories are unresolved, never assigned a zero counter.
    """
    ordered = ordered_public_lifecycle(view, ledger)
    if ordered is None:
        return None
    completed_upkeeps = [
        turn for turn, event, _ in ordered if event == ["upkeep"] and turn < view["turn"]
    ]
    if sorted(completed_upkeeps) != list(range(1, view["turn"])):
        return None
    opening = next(json.loads(payload) for turn, payload in ledger.field_snapshots if turn == 1)
    if opening.get("phase") != "move" or opening.get("public_event_delta", {}).get("events"):
        return None  # A first observation in the middle of turn one is not a fresh opening.
    actors = {}
    counts = {}
    ages = {}
    for side, prefix in (("player", "p2"), ("opponent", "p1")):
        for slot, species in enumerate(opening.get("active_species", {}).get(side, [])):
            if species:
                actor = prefix + chr(97 + slot)
                actors[actor], counts[actor], ages[actor] = species, 0, 1
    previous_turn = None
    upkeep = False

    def finish_turn(turn):
        if turn is not None and 1 <= turn < view["turn"]:
            if not upkeep:
                return False
            for actor in actors:
                ages[actor] += 1
        return True

    for turn, event, _ in ordered:
        if turn != previous_turn:
            if not finish_turn(previous_turn):
                return None
            previous_turn, upkeep = turn, False
        actor = event[1] if len(event) > 1 else None
        if event[0] in {"switch", "drag"}:
            actors[actor], counts[actor], ages[actor] = event[2], 0, 0
        elif event[0] == "faint":
            actors.pop(actor, None)
        elif event[0] in {"move", "cant"}:
            if actor not in actors or any(token.startswith("[from]") for token in event[3:]):
                return None
            counts[actor] += 1
        elif event == ["upkeep"]:
            upkeep = True
    if not finish_turn(previous_turn):
        return None
    result = []
    for side, prefix, key in (("player", "p2", "active_details"), ("opponent", "p1", "active")):
        for slot, mon in enumerate(view[side].get(key, [])):
            if not mon or mon.get("fainted"):
                continue
            actor = prefix + chr(97 + slot)
            known = sid(actors.get(actor))
            current = sid(mon.get("base_species", mon.get("species")))
            if not known or known not in {current, sid(mon.get("species"))}:
                if sid(mon.get("species")) != known + "mega":
                    return None
            result.append(
                {
                    "side": side,
                    "slot": slot,
                    "species": actors[actor],
                    "move_actions": counts[actor],
                    "active_turns": ages[actor],
                }
            )
    return result if result else None


def public_support_contract(view, ledger):
    """Classify observed persistent families; no unobserved foe-set assumptions."""
    entries = []

    def record(name, state, evidence):
        entries.append(MechanicSupport(name, state, evidence))

    ordered = ordered_public_lifecycle(view, ledger)
    if ordered is None:
        record("history", "unresolved", "complete opening-to-current public channel required")
        return SupportContract(tuple(entries))
    if public_active_tenure_plan(view, ledger) is None:
        record("active-tenure", "unresolved", "ambiguous public action/entry lifecycle")
    else:
        record(
            "active-tenure", "supported", "ordered native move/cant entries and upkeep boundaries"
        )
    if public_protection_plan(view, ledger) is None:
        record("protection-history", "unresolved", "complete shared stall lifecycle required")
    else:
        record("protection-history", "supported", "pinned start/restart/expiry lifecycle")
    if public_opponent_pp_plan(view, ledger) is None:
        record("opponent-pp", "unresolved", "ordinary move-use provenance unavailable")
    else:
        record(
            "opponent-pp",
            "supported",
            "ordinary uses restored with pinned deductPP; static exclusions required",
        )

    statuses = [
        mon.get("status")
        for side, key in (
            ("player", "team"),
            ("player", "active_details"),
            ("opponent", "revealed"),
            ("opponent", "active"),
        )
        for mon in view[side].get(key, [])
        if mon
    ]
    for status in statuses:
        if status not in {None, "", "fnt", "brn", "par", "psn", "frz"}:
            record("status:" + str(status), "unresolved", "native counter not reconstructed")
    active_species = {
        sid(mon.get("base_species", mon.get("species")))
        for mon in view["opponent"].get("active", [])
        if mon
    }
    for mon in view["opponent"].get("revealed", []):
        if (
            mon.get("seen")
            and not mon.get("fainted")
            and sid(mon.get("species")) not in active_species
        ):
            if mon.get("status") or mon.get("hp_percent") != 100:
                record(
                    "opponent-bench", "unresolved", "damaged/statused reserve is not reconstructed"
                )
    observed = set()
    inventory = public_inventory_plan(view, ledger)
    if inventory is None:
        record('opponent-inventory', 'unresolved', 'unsupported or ambiguous inventory lifecycle')
    elif inventory:
        record('opponent-inventory', 'supported', 'bounded public consumption; native state checked separately')
    for _, event, _ in ordered:
        kind = event[0]
        if kind in {"-item", "-enditem"} and event[1].startswith("p1"):
            continue
        if kind in STATELESS_EVENTS:
            continue
        if kind == "move":
            if event[2] not in CURRENT_FACT_MOVES:
                record("move:" + event[2], "unresolved", "no support entry for historical move")
        elif kind == "cant":
            if event[2] not in {"flinch", "par", "frz"}:
                record("cant:" + event[2], "unresolved", "unrestored prevention state")
        elif kind in {"-status", "-curestatus"}:
            if event[2] not in {"brn", "par", "psn", "frz"}:
                record("status:" + event[2], "unresolved", "counter-bearing status history")
        elif kind in {"-start", "-end", "-activate", "-singlemove", "-singleturn"}:
            effect = event[2].removeprefix("move:").removeprefix("ability:")
            if kind in {"-singleturn", "-activate"} and effect in {
                "protect",
                "detect",
                "endure",
                "wideguard",
                "quickguard",
                "followme",
            }:
                continue
            observed.add(effect)
            record("volatile:" + effect, "unresolved", "no demonstrated native reconstruction")
        elif kind in {
            "-fieldstart",
            "-fieldend",
            "-weather",
            "-sidestart",
            "-sideend",
            "-mega",
            "-ability",
        }:
            # Dedicated field/Trace/Mega gates and native plans check these.
            continue
        else:
            record("event:" + kind, "unresolved", "protocol support is not mechanics support")
    for family in (
        "flashfire",
        "encore",
        "taunt",
        "imprison",
        "substitute",
        "confusion",
        "saltcure",
        "perishsong",
    ):
        if family not in observed:
            record(
                "volatile:" + family,
                "absent",
                "complete public start-event channel; static capabilities checked separately",
            )
    if any(
        sid(mon.get("item")) in {"choiceband", "choicescarf", "choicespecs"}
        for mon in view["player"].get("team", [])
    ):
        record("choice-lock", "unresolved", "silent owned choice lock not reconstructed")
    # Choice-lock absence is never certified from an empty reveal list. Every
    # publicly compatible static candidate must pass current_capability_issue.
    return SupportContract(tuple(entries))


def public_opponent_pp_plan(view, ledger):
    """Ordinary visible move entries deduct PP; native cant does not.

    Static support excludes Pressure, PP-changing and called moves. Counts
    persist across switches and apply to benched brought members as well.
    """
    ordered = ordered_public_lifecycle(view, ledger)
    if ordered is None:
        return None
    counts = {}
    species_names = view.get("opponent", {}).get("preview_species")
    if not isinstance(species_names, list) or not species_names or not all(
        isinstance(species, str) and species for species in species_names
    ):
        return None
    preview = {sid(species): species for species in species_names}
    for _, event, actors in ordered:
        if event[0] != "move" or not event[1].startswith("p1"):
            continue
        if any(token.startswith("[from]") for token in event[3:]):
            return None
        species = sid(actors.get(event[1]))
        if species not in preview and species.endswith("mega"):
            species = species[:-4]
        if species not in preview:
            return None
        key = (species, event[2])
        counts[key] = counts.get(key, 0) + 1
    return [
        {"species": preview[species], "move": move, "uses": uses}
        for (species, move), uses in sorted(counts.items())
    ]


def static_support_issue(*, ability, item, moves, opponent=False, inactive=False):
    """Check exact owned or hypothetical set, never inferred unseen absence."""
    if sid(ability) not in CURRENT_FACT_ABILITIES:
        return "unsupported-persistent:ability:" + sid(ability)
    # Active Unburden needs a tested lifecycle domain. An owned inactive
    # holder has the separate native switch-reset certificate below.
    if sid(ability) == "unburden" and (opponent or not inactive):
        return "unsupported-persistent:" + ("opponent-unburden" if opponent else "owned-unburden")
    if sid(item) not in CURRENT_FACT_ITEMS:
        return "unsupported-persistent:item:" + sid(item)
    for move in moves:
        # Native switch-out clearVolatile resets the last-move result; a
        # currently inactive holder cannot attack before native switch-in.
        # Active holders and any observed Stomping history remain unsupported.
        if sid(move) in {'stompingtantrum', 'electroshot', 'phantomforce'} and inactive:
            continue
        if sid(move) not in CURRENT_FACT_MOVES:
            return "unsupported-persistent:move:" + sid(move)
    return None


def current_capability_issue(view, priors):
    """Validate owned inventory and ALL public-compatible opponent candidates.

    Do this before bounded sampling: an unsupported prior must not disappear
    simply because another candidate was sampled. No set revelation is needed
    to retain its possible silent state.
    """
    from champions_practice.belief_worlds import _candidate_matches
    from champions_practice.beliefs import build_public_opponent_belief

    own = view.get("player", {}).get("team")
    if not isinstance(own, list) or not own:
        return "unsupported-persistent:owned-capabilities"
    for mon in own:
        if not {"ability", "item", "move_pp"} <= mon.keys():
            return "unsupported-persistent:owned-capabilities"
        issue = static_support_issue(
            ability=mon["ability"], item=mon["item"], moves=[move["id"] for move in mon["move_pp"]],
            inactive=mon.get('active') is False,
        )
        if issue:
            return issue
    if not priors:
        return "unsupported-persistent:opponent-capabilities"
    belief = build_public_opponent_belief(view)
    for pokemon in belief.pokemon:
        candidates = next(
            (values for species, values in priors.items() if sid(species) == sid(pokemon.species)),
            (),
        )
        possible = [candidate for candidate in candidates if _candidate_matches(pokemon, candidate)]
        if not possible:
            return "unsupported-persistent:opponent-capabilities"
        for candidate in possible:
            issue = static_support_issue(
                ability=candidate.ability, item=candidate.item, moves=candidate.moves, opponent=True,
                inactive=pokemon.active_slot is None or pokemon.fainted,
            )
            if issue:
                return issue
    return None
