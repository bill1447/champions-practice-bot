"use strict";

const readline = require("readline");
const path = require("path");

const root = path.resolve(__dirname, "..");
const showdownRoot = path.join(root, "external", "pokemon-showdown");
const {
  Battle,
  extractChannelMessages,
} = require(path.join(showdownRoot, "dist", "sim", "battle"));
const { Teams } = require(path.join(showdownRoot, "dist", "sim", "teams"));

const sessions = new Map();
const sessionPreviewSpecies = new Map();
let nextSessionId = 1;

function importTeam(text) {
  const team = Teams.import(text);
  if (!team || !Array.isArray(team) || team.length === 0) {
    throw new Error("Could not import Showdown team text");
  }
  return team;
}

function cloneJson(value) {
  if (value === undefined) return null;
  return JSON.parse(JSON.stringify(value));
}

function hpPercent(mon) {
  if (!mon || !mon.maxhp) return 0;
  return Math.round((mon.hp / mon.maxhp) * 1000) / 10;
}

function publicActive(mon, identity) {
  if (!mon || !identity) return null;
  return {
    species: identity.visibleSpecies,
    base_species: identity.baseSpecies,
    hp_percent: identity.hpPercent ?? hpPercent(mon),
    fainted: identity.fainted ?? mon.fainted,
    status: mon.status || null,
    boosts: { ...mon.boosts },
  };
}

function toId(value) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function canonicalProtocolIdentity(value) {
  const text = String(value || "").trim();
  const slot = text.match(/^(p[12][a-z])(?::|$)/);
  if (slot) return slot[1];
  const side = text.match(/^(p[12])(?::|$)/);
  if (side) return side[1];

  const tagged = text.match(/^\[([^\]]+)\]\s*(.*)$/);
  if (tagged) {
    const tag = toId(tagged[1]);
    const payload = tagged[2] ? canonicalProtocolIdentity(tagged[2]) : "";
    return payload ? `[${tag}]:${payload}` : `[${tag}]`;
  }

  const effect = text.match(/^(move|ability|item):\s*(.*)$/i);
  if (effect) {
    return `${toId(effect[1])}:${toId(effect[2])}`;
  }

  if (/^[+-]?\d+$/.test(text)) return String(Number(text));
  return toId(text);
}

const PUBLIC_ACTION_OUTCOMES = new Set([
  "-fail",
  "-miss",
  "-immune",
  "-notarget",
  "-block",
]);

function protocolSlotIdentity(value) {
  const slot = String(value || "").split(":", 1)[0];
  if (!/^p[12][a-z]$/.test(slot)) return null;
  return {
    side: slot.slice(0, 2),
    slot: slot.charCodeAt(2) - "a".charCodeAt(0) + 1,
  };
}

function publicRole(sideId, actorSide) {
  return actorSide === sideId ? "player" : "opponent";
}

function publicMoveProvenance(parts) {
  const provenance = [];
  for (const value of parts.slice(5)) {
    if (!String(value).trim().toLowerCase().startsWith("[from]")) continue;
    const normalized = canonicalProtocolIdentity(value);
    if (normalized) provenance.push(normalized);
  }
  return provenance;
}

function publicMoveActionContext(parts, sideId) {
  const actor = protocolSlotIdentity(parts[2]);
  const move = toId(parts[3]);
  if (!actor || !move) return null;
  const provenance = publicMoveProvenance(parts);
  return {
    side: publicRole(sideId, actor.side),
    slot: actor.slot,
    move,
    source: provenance.length ? "called" : "selected",
  };
}

function publicExecutionEventDelta(battle, sideId) {
  const channel = sideId === "p1" ? 1 : 2;
  const visibleLog = extractChannelMessages(battle.log.join("\n"), [channel])[channel];
  let logTurn = 0;
  let currentAction = null;
  const byTurn = new Map();

  function turnActions() {
    if (!byTurn.has(logTurn)) byTurn.set(logTurn, []);
    return byTurn.get(logTurn);
  }

  for (const line of visibleLog) {
    const parts = line.split("|");
    const event = parts[1];

    if (event === "turn") {
      const parsed = Number(parts[2]);
      if (Number.isInteger(parsed) && parsed > 0) logTurn = parsed;
      currentAction = null;
      continue;
    }
    if (logTurn <= 0) continue;

    if (event === "move") {
      currentAction = null;
      const actor = protocolSlotIdentity(parts[2]);
      if (!actor) continue;

      const move = toId(parts[3]);
      if (!move) continue;
      const provenance = publicMoveProvenance(parts);
      currentAction = {
        side: publicRole(sideId, actor.side),
        slot: actor.slot,
        outcome: "executed",
        move,
        source: provenance.length ? "called" : "selected",
        provenance,
        effects: [],
      };
      turnActions().push(currentAction);
      continue;
    }

    if (event === "cant") {
      currentAction = null;
      const actor = protocolSlotIdentity(parts[2]);
      if (!actor) continue;
      const attemptedMove = toId(parts[4]);
      currentAction = {
        side: publicRole(sideId, actor.side),
        slot: actor.slot,
        outcome: "prevented",
        reason: canonicalProtocolIdentity(parts[3]),
        attempted_move: attemptedMove || null,
        effects: [],
      };
      turnActions().push(currentAction);
      continue;
    }

    if (PUBLIC_ACTION_OUTCOMES.has(event) && currentAction !== null) {
      if (!currentAction.effects.includes(event)) {
        currentAction.effects.push(event);
      }
    }
  }

  const turns = [...byTurn.keys()].sort((left, right) => right - left);
  if (!turns.length) return { turn: null, actions: [] };
  const turn = turns[0];
  const actions = byTurn.get(turn).map((action) => ({
    ...action,
    effects: action.effects.slice().sort(),
  }));
  // Preserve the exact channel-visible execution sequence. Order is mechanics
  // evidence: Showdown carries state such as lastMove across turns. The sequence
  // also includes both sides and called/nested moves so an exact public match
  // cannot hide persistent state behind an identical final snapshot.
  return { turn, actions };
}

const PUBLIC_MECHANICS_EVENTS = new Set([
  // These are protocol facts whose occurrence or payload can constrain exact
  // mechanics even when later effects restore the same reduced final board.
  // Every value below is taken only from the requesting side's sanitized
  // Showdown channel; the canonicalizer never consults hidden live state.
  "-formechange",
  "-fail",
  "-block",
  "-notarget",
  "-miss",
  "-damage",
  "-heal",
  "-sethp",
  "-status",
  "-curestatus",
  "-cureteam",
  "-boost",
  "-unboost",
  "-setboost",
  "-swapboost",
  "-invertboost",
  "-clearboost",
  "-clearallboost",
  "-clearpositiveboost",
  "-clearnegativeboost",
  "-copyboost",
  "-weather",
  "-fieldstart",
  "-fieldend",
  "-fieldactivate",
  "-sidestart",
  "-sideend",
  "-swapsideconditions",
  "-start",
  "-end",
  "-crit",
  "-supereffective",
  "-resisted",
  "-immune",
  "-item",
  "-enditem",
  "-ability",
  "-endability",
  "-transform",
  "-mega",
  "-primal",
  "-burst",
  "-zpower",
  "-zbroken",
  "-terastallize",
  "-dynamax",
  "-activate",
  "-waiting",
  "-prepare",
  "-mustrecharge",
  "-nothing",
  "-hitcount",
  "-singlemove",
  "-singleturn",
  "-ohko",
]);

const PUBLIC_PRESENTATION_EVENTS = new Set([
  "-hint",
  "-message",
  "-center",
  "-combine",
  "-anim",
]);

function canonicalPublicCondition(value) {
  return String(value || "").trim().toLowerCase().replace(/\s+/g, " ");
}

function canonicalPublicMechanicsEvent(parts, actionContext) {
  const event = parts[1];
  if (!PUBLIC_MECHANICS_EVENTS.has(event)) return null;

  if (event === "-hitcount") {
    const count = Number(parts[3]);
    if (!Number.isInteger(count) || count < 1) return null;
    const canonical = [
      event,
      canonicalProtocolIdentity(parts[2]),
      String(count),
    ];
    if (actionContext) {
      canonical.push(
        "[action]",
        actionContext.side,
        String(actionContext.slot),
        actionContext.move,
        actionContext.source,
      );
    }
    return canonical;
  }

  if (event === "-damage" || event === "-heal" || event === "-sethp") {
    const canonical = [
      event,
      canonicalProtocolIdentity(parts[2]),
      canonicalPublicCondition(parts[3]),
    ];
    for (const value of parts.slice(4)) {
      const normalized = canonicalProtocolIdentity(value);
      if (normalized) canonical.push(normalized);
    }
    return canonical;
  }

  if (event === "-formechange") {
    const canonical = [
      event,
      canonicalProtocolIdentity(parts[2]),
      toId(String(parts[3] || "").split(",", 1)[0]),
    ];
    if (parts[4]) canonical.push(canonicalPublicCondition(parts[4]));
    for (const value of parts.slice(5)) {
      const normalized = canonicalProtocolIdentity(value);
      if (normalized) canonical.push(normalized);
    }
    return canonical;
  }

  const canonical = [event];
  for (const value of parts.slice(2)) {
    const normalized = canonicalProtocolIdentity(value);
    if (normalized) canonical.push(normalized);
  }
  return canonical;
}

function publicMechanicsEventDelta(battle, sideId) {
  const channel = sideId === "p1" ? 1 : 2;
  const visibleLog = extractChannelMessages(battle.log.join("\n"), [channel])[channel];
  let logTurn = 0;
  let actionContext = null;
  let current = { turn: null, events: [], unsupported: [] };
  let latest = null;

  function hasEvidence(record) {
    return record.events.length || record.unsupported.length;
  }

  function preserveCurrent() {
    if (current.turn !== null && hasEvidence(current)) latest = current;
  }

  for (const line of visibleLog) {
    const parts = line.split("|");
    const event = parts[1];

    if (event === "turn") {
      preserveCurrent();
      const parsed = Number(parts[2]);
      logTurn = Number.isInteger(parsed) && parsed > 0 ? parsed : 0;
      current = { turn: logTurn || null, events: [], unsupported: [] };
      actionContext = null;
      continue;
    }
    if (logTurn <= 0) continue;

    if (event === "move") {
      actionContext = publicMoveActionContext(parts, sideId);
      continue;
    }
    if (event === "cant") {
      actionContext = null;
      continue;
    }
    if (!event.startsWith("-")) continue;
    if (PUBLIC_PRESENTATION_EVENTS.has(event)) continue;

    if (!PUBLIC_MECHANICS_EVENTS.has(event)) {
      const unsupported = canonicalProtocolIdentity(event);
      if (unsupported && !current.unsupported.includes(unsupported)) {
        current.unsupported.push(unsupported);
      }
      continue;
    }

    const canonical = canonicalPublicMechanicsEvent(parts, actionContext);
    if (!canonical) {
      const invalid = `${canonicalProtocolIdentity(event)}:invalid`;
      if (!current.unsupported.includes(invalid)) {
        current.unsupported.push(invalid);
      }
      continue;
    }
    current.events.push(canonical);
  }

  preserveCurrent();
  if (!latest) return { turn: null, events: [], unsupported: [] };
  return {
    turn: latest.turn,
    events: latest.events,
    unsupported: latest.unsupported.slice().sort(),
  };
}

function publicLastOpponentActions(battle, sideId) {
  const opponentPrefix = sideId === "p1" ? "p2" : "p1";
  const channel = sideId === "p1" ? 1 : 2;
  const visibleLog = extractChannelMessages(battle.log.join("\n"), [channel])[channel];
  let logTurn = 0;
  const byTurn = new Map();

  function slotIdentity(value) {
    const slot = String(value || "").split(":", 1)[0];
    if (!/^p[12][a-z]$/.test(slot)) return null;
    return {
      side: slot.slice(0, 2),
      slot: slot.charCodeAt(2) - "a".charCodeAt(0) + 1,
    };
  }

  for (const line of visibleLog) {
    const parts = line.split("|");
    const event = parts[1];
    if (event === "turn") {
      const parsed = Number(parts[2]);
      if (Number.isInteger(parsed) && parsed > 0) logTurn = parsed;
      continue;
    }
    if (event !== "move" || logTurn <= 0) continue;

    const actor = slotIdentity(parts[2]);
    if (!actor || actor.side !== opponentPrefix) continue;
    if (parts.slice(5).some((part) => String(part).startsWith("[from]"))) {
      continue;
    }

    const move = toId(parts[3]);
    if (!move) continue;
    const target = slotIdentity(parts[4]);
    let targetLocation = null;
    if (target) {
      targetLocation = target.side === opponentPrefix ? -target.slot : target.slot;
    }

    if (!byTurn.has(logTurn)) byTurn.set(logTurn, new Map());
    const actions = byTurn.get(logTurn);
    const previous = actions.get(actor.slot);
    if (previous === undefined) {
      actions.set(actor.slot, {
        turn: logTurn,
        slot: actor.slot,
        move,
        target: targetLocation,
      });
    } else {
      // Multiple public move events from one slot can be caused by effects such as
      // Instruct. They do not map cleanly to one chosen command, so keep that slot
      // unconstrained rather than inferring private intent.
      actions.set(actor.slot, null);
    }
  }

  const turns = [...byTurn.keys()].sort((left, right) => right - left);
  if (!turns.length) return [];
  return [...byTurn.get(turns[0]).values()]
    .filter((action) => action !== null)
    .sort((left, right) => left.slot - right.slot);
}

function publicOpponentKnowledge(battle, sideId, previewSpecies) {
  const opponentPrefix = sideId === "p1" ? "p2" : "p1";
  const channel = sideId === "p1" ? 1 : 2;
  const observations = new Map();
  const slotSpecies = new Map();
  const slotVisibleSpecies = new Map();
  const slotConditions = new Map();

  for (const species of previewSpecies) {
    const key = toId(species);
    observations.set(key, {
      species,
      moves: new Set(),
      items: new Set(),
      abilities: new Set(),
      hpPercent: null,
      status: null,
      fainted: false,
      seen: false,
    });
  }

  function actorSlot(actor) {
    const slot = String(actor || "").split(":", 1)[0];
    return slot.startsWith(opponentPrefix) ? slot : null;
  }

  function observationForActor(actor) {
    const slot = actorSlot(actor);
    if (!slot) return null;
    const speciesKey = slotSpecies.get(slot);
    return speciesKey ? observations.get(speciesKey) || null : null;
  }

  function publicCondition(condition) {
    const text = String(condition || "");
    if (!text) return {};
    if (text.endsWith(" fnt") || text === "0 fnt") {
      return { hpPercent: 0, fainted: true };
    }
    const [hp, status] = text.split(" ");
    const [current, maximum] = hp.split("/").map(Number);
    if (!Number.isFinite(current) || !Number.isFinite(maximum) || maximum <= 0) {
      return {};
    }
    return {
      hpPercent: Math.round((current / maximum) * 1000) / 10,
      fainted: current <= 0,
      status: status && status !== "fnt" ? toId(status) : null,
    };
  }

  function applyCondition(observation, condition, replaceStatus = false) {
    if (condition.hpPercent !== undefined) {
      observation.hpPercent = condition.hpPercent;
    }
    if (condition.fainted !== undefined) {
      observation.fainted = condition.fainted;
    }
    if (replaceStatus || condition.status) {
      observation.status = condition.status ?? null;
    }
  }

  const visibleLog = extractChannelMessages(battle.log.join("\n"), [channel])[channel];
  for (const line of visibleLog) {
    const parts = line.split("|");
    const event = parts[1];
    const slot = actorSlot(parts[2]);

    if (slot && ["switch", "drag", "replace"].includes(event)) {
      const species = String(parts[3] || "").split(",", 1)[0];
      const speciesKey = toId(species);
      const observation = observations.get(speciesKey);
      if (observation) {
        observation.seen = true;
        const condition = publicCondition(parts[4]);
        applyCondition(observation, condition, true);
        slotSpecies.set(slot, speciesKey);
        slotVisibleSpecies.set(slot, species);
        slotConditions.set(slot, condition);
      }
      continue;
    }

    if (slot && ["detailschange", "-formechange"].includes(event)) {
      const species = String(parts[3] || "").split(",", 1)[0];
      if (species) slotVisibleSpecies.set(slot, species);
    }

    const observation = observationForActor(parts[2]);
    if (!observation) continue;

    if (["-damage", "-heal", "-sethp"].includes(event)) {
      const condition = publicCondition(parts[3]);
      applyCondition(observation, condition);
      slotConditions.set(slot, condition);
    } else if (event === "-status") {
      observation.status = toId(parts[3]);
    } else if (event === "-curestatus") {
      observation.status = null;
    } else if (event === "move") {
      const called = parts.slice(5).some(
        (part) => String(part).trim().toLowerCase().startsWith("[from]"),
      );
      if (!called) observation.moves.add(toId(parts[3]));
    } else if (event === "-item" || event === "-enditem") {
      observation.items.add(toId(parts[3]));
    } else if (event === "-mega") {
      observation.items.add(toId(parts[4]));
    } else if (event === "-ability") {
      observation.abilities.add(toId(parts[3]));
      if (parts[4] && !parts[4].startsWith("[")) {
        observation.abilities.add(toId(parts[4]));
      }
    } else if (event === "faint") {
      observation.hpPercent = 0;
      observation.fainted = true;
      slotConditions.set(slot, { hpPercent: 0, fainted: true });
    }
  }

  const activeIdentities = new Map();
  for (const [slot, speciesKey] of slotSpecies) {
    const observation = observations.get(speciesKey);
    const visibleSpecies = slotVisibleSpecies.get(slot);
    if (!observation || !visibleSpecies) continue;
    activeIdentities.set(slot, {
      baseSpecies: observation.species,
      visibleSpecies,
      ...slotConditions.get(slot),
    });
  }

  return {
    activeIdentities,
    revealed: [...observations.values()].map((observation) => ({
      species: observation.species,
      moves: [...observation.moves].filter(Boolean).sort(),
      items: [...observation.items].filter(Boolean).sort(),
      abilities: [...observation.abilities].filter(Boolean).sort(),
      hp_percent: observation.hpPercent,
      status: observation.status,
      fainted: observation.fainted,
      seen: observation.seen,
    })),
  };
}

function ownPokemon(mon, battle) {
  const damagingMoveCount = mon.moveSlots.filter(
    (slot) => battle.dex.moves.get(slot.id).category !== "Status",
  ).length;
  return {
    species: mon.species.name,
    hp: mon.hp,
    maxhp: mon.maxhp,
    hp_percent: hpPercent(mon),
    fainted: mon.fainted,
    status: mon.status || null,
    boosts: { ...mon.boosts },
    item: mon.item || null,
    ability: mon.ability || null,
    moves: mon.moveSlots.map((slot) => slot.move),
    speed: mon.speed,
    damaging_move_count: damagingMoveCount,
    active: mon.isActive,
  };
}

function publicSideConditions(side) {
  return Object.keys(side.sideConditions || {}).sort();
}

function playerView(battle, sideId = "p1", previews = null) {
  if (sideId !== "p1" && sideId !== "p2") {
    throw new Error("side must be p1 or p2");
  }
  const own = sideId === "p1" ? battle.p1 : battle.p2;
  const opponent = sideId === "p1" ? battle.p2 : battle.p1;
  const opponentId = sideId === "p1" ? "p2" : "p1";
  const opponentPreview = previews ? previews[opponentId] : opponent.pokemon.map(
    (mon) => mon.set.species,
  );
  const opponentKnowledge = publicOpponentKnowledge(
    battle,
    sideId,
    opponentPreview,
  );

  return {
    turn: battle.turn,
    phase: battle.requestState || (battle.ended ? "ended" : ""),
    opponent_last_actions: publicLastOpponentActions(battle, sideId),
    // Selected commands are not proof of execution. This channel-sanitized
    // ledger preserves the ordered, both-side public execution sequence, including
    // called-move provenance, prevention, and public failure effects. Raw protocol
    // animation targets are intentionally excluded; selected target intent is already
    // represented by sealed/resolved commands and opponent_last_actions.
    public_execution_delta: publicExecutionEventDelta(battle, sideId),
    // This bounded per-turn ledger is derived only from the requesting side's
    // Showdown-visible channel. It preserves quantitative and historical mechanics
    // evidence even when later effects restore the same reduced final state.
    public_event_delta: publicMechanicsEventDelta(battle, sideId),
    ended: battle.ended,
    winner: battle.winner || null,
    field: {
      weather: battle.field.weather || null,
      terrain: battle.field.terrain || null,
      pseudo_weather: Object.keys(battle.field.pseudoWeather || {}).sort(),
    },
    request: cloneJson(own.activeRequest),
    player: {
      name: own.name,
      active: own.active.map((mon) => (mon ? mon.species.name : null)),
      active_details: own.active.map((mon) => (mon ? ownPokemon(mon, battle) : null)),
      side_conditions: publicSideConditions(own),
      team: own.pokemon.map((mon) => ownPokemon(mon, battle)),
    },
    opponent: {
      name: opponent.name,
      preview_species: opponentPreview.slice(),
      side_conditions: publicSideConditions(opponent),
      active: opponent.active.map((mon, index) => publicActive(
        mon,
        opponentKnowledge.activeIdentities.get(
          `${opponentId}${String.fromCharCode("a".charCodeAt(0) + index)}`,
        ),
      )),
      revealed: opponentKnowledge.revealed,
    },
  };
}

function summarize(battle) {
  function activeSummary(mon) {
    if (!mon) return null;
    const moveTypes = new Set();
    for (const slot of mon.moveSlots) {
      const move = battle.dex.moves.get(slot.id);
      if (move.category !== "Status") moveTypes.add(move.type.toLowerCase());
    }
    return {
      species: mon.species.name,
      hp: mon.hp,
      maxhp: mon.maxhp,
      fainted: mon.fainted,
      status: mon.status || null,
      boosts: { ...mon.boosts },
      speed: mon.speed,
      grounded: !!mon.isGrounded(),
      moveTypes: [...moveTypes],
    };
  }

  function sideSummary(side) {
    return {
      name: side.name,
      active: side.active.map(activeSummary),
      sideConditions: Object.keys(side.sideConditions || {}),
      pokemon: side.pokemon.map((mon) => ({
        species: mon.species.name,
        hp: mon.hp,
        maxhp: mon.maxhp,
        fainted: mon.fainted,
        status: mon.status || null,
      })),
    };
  }

  return {
    turn: battle.turn,
    requestState: battle.requestState,
    ended: battle.ended,
    winner: battle.winner || null,
    field: {
      weather: battle.field.weather || null,
      terrain: battle.field.terrain || null,
      pseudoWeather: Object.keys(battle.field.pseudoWeather || {}),
    },
    p1: sideSummary(battle.p1),
    p2: sideSummary(battle.p2),
  };
}

function combinations(values, count, start = 0, prefix = [], output = []) {
  if (prefix.length === count) {
    output.push(prefix.slice());
    return output;
  }
  for (let index = start; index <= values.length - (count - prefix.length); index++) {
    prefix.push(values[index]);
    combinations(values, count, index + 1, prefix, output);
    prefix.pop();
  }
  return output;
}

function cartesian(groups, index = 0, prefix = [], output = []) {
  if (index === groups.length) {
    output.push(prefix.join(", "));
    return output;
  }
  for (const value of groups[index]) {
    prefix.push(value);
    cartesian(groups, index + 1, prefix, output);
    prefix.pop();
  }
  return output;
}

function isFainted(requestPokemon) {
  return requestPokemon.condition.endsWith(" fnt");
}

function previewCandidates(battle, side) {
  const teamSize = side.activeRequest.side.pokemon.length;
  const pickedSize = side.pickedTeamSize();
  const leadSize = Math.min(battle.activePerHalf, pickedSize);
  const slots = Array.from({ length: teamSize }, (_, index) => index + 1);
  const candidates = [];

  for (const brought of combinations(slots, pickedSize)) {
    for (const leads of combinations(brought, leadSize)) {
      const leadOrders = leadSize === 2 ? [leads, [leads[1], leads[0]]] : [leads];
      const bench = brought.filter((slot) => !leads.includes(slot));
      for (const orderedLeads of leadOrders) {
        candidates.push(`team ${orderedLeads.concat(bench).join("")}`);
      }
    }
  }
  return candidates;
}

const PUBLIC_CHOOSABLE_TARGETS = new Set([
  "normal",
  "any",
  "adjacentAlly",
  "adjacentAllyOrSelf",
  "adjacentFoe",
]);

function publicValidTargetLoc(
  targetLoc,
  sourceSlot,
  targetType,
  activePerHalf,
  gameType,
) {
  if (targetLoc === 0) return true;
  if (Math.abs(targetLoc) > activePerHalf) return false;

  // Showdown commands describe targets relative to the choosing side:
  // positive locations are foes; negative locations are the user's own slots.
  // This is pure slot geometry copied from Battle#validTargetLoc and does not
  // consult the opponent's exact live Pokemon, abilities, items, or choices.
  const sourceLoc = -(sourceSlot + 1);
  const isSelf = sourceLoc === targetLoc;
  const isFoe = gameType === "freeforall" ? !isSelf : targetLoc > 0;
  const acrossFromTargetLoc = -(activePerHalf + 1 - targetLoc);
  const isAdjacent = targetLoc > 0
    ? Math.abs(acrossFromTargetLoc - sourceLoc) <= 1
    : Math.abs(targetLoc - sourceLoc) === 1;

  if (gameType === "freeforall" && targetType === "adjacentAlly") {
    return isAdjacent;
  }

  switch (targetType) {
    case "randomNormal":
    case "scripted":
    case "normal":
      return isAdjacent;
    case "adjacentAlly":
      return isAdjacent && !isFoe;
    case "adjacentAllyOrSelf":
      return (isAdjacent && !isFoe) || isSelf;
    case "adjacentFoe":
      return isAdjacent && isFoe;
    case "any":
      return !isSelf;
    default:
      return false;
  }
}

function publicMoveTargetLocations(request, sourceSlot, targetType, gameType) {
  const activePerHalf = request.active.length;
  if (!PUBLIC_CHOOSABLE_TARGETS.has(targetType) || activePerHalf < 2) {
    return [0];
  }

  const locations = [];
  for (let slot = 1; slot <= activePerHalf; slot++) {
    for (const targetLoc of [slot, -slot]) {
      if (
        publicValidTargetLoc(
          targetLoc,
          sourceSlot,
          targetType,
          activePerHalf,
          gameType,
        )
      ) {
        locations.push(targetLoc);
      }
    }
  }
  return locations;
}

function availableSwitches(request) {
  return request.side.pokemon
    .map((pokemon, index) => ({ pokemon, slot: index + 1 }))
    .filter(({ pokemon }) => !pokemon.active && !isFainted(pokemon))
    .map(({ slot }) => `switch ${slot}`);
}

function availableRevivalTargets(request) {
  return request.side.pokemon
    .map((pokemon, index) => ({ pokemon, slot: index + 1 }))
    .filter(({ pokemon }) => isFainted(pokemon))
    .map(({ slot }) => `switch ${slot}`);
}

function moveSlotCandidates(request, slot, gameType) {
  const active = request.active[slot];
  const pokemon = request.side.pokemon[slot];
  if (!active || isFainted(pokemon) || pokemon.commanding) return ["pass"];

  const choices = [];
  for (const move of active.moves) {
    if (move.disabled) continue;
    const targets = publicMoveTargetLocations(
      request,
      slot,
      move.target,
      gameType,
    );
    const events = [""];
    if (active.canMegaEvo) events.push("mega");
    if (active.canMegaEvoX) events.push("megax");
    if (active.canMegaEvoY) events.push("megay");
    if (active.canUltraBurst) events.push("ultra");

    for (const target of targets) {
      for (const event of events) {
        const parts = [`move ${move.id}`];
        if (target) parts.push(target > 0 ? `+${target}` : String(target));
        if (event) parts.push(event);
        choices.push(parts.join(" "));
      }
    }
  }

  if (!active.trapped) choices.push(...availableSwitches(request));
  return choices;
}

function switchCandidates(request) {
  const switches = availableSwitches(request);
  const revivalTargets = availableRevivalTargets(request);
  const ordinaryRequired = request.forceSwitch.reduce(
    (count, mustSwitch, slot) => (
      count + (
        mustSwitch && !request.side.pokemon[slot]?.reviving ? 1 : 0
      )
    ),
    0,
  );
  const allowVacancy = switches.length < ordinaryRequired;

  return request.forceSwitch.map((mustSwitch, slot) => {
    if (!mustSwitch) return ["pass"];

    // Revival Blessing reuses Showdown's force-switch protocol, but the selected
    // "switch" target is a fainted party member to revive, not a healthy reserve
    // entering the active slot. The public request exposes this with reviving:true
    // on the acting active Pokemon, so no hidden-state lookup is needed.
    if (request.side.pokemon[slot]?.reviving) {
      return revivalTargets;
    }

    return allowVacancy ? [...switches, "pass"] : switches;
  });
}

function proposedChoices(battle, side) {
  const request = side.activeRequest;
  if (!request || request.wait) return [""];
  if (request.teamPreview) return previewCandidates(battle, side);
  if (request.forceSwitch) return cartesian(switchCandidates(request));
  if (request.active) {
    return cartesian(
      request.active.map((_, slot) => (
        moveSlotCandidates(request, slot, battle.gameType)
      )),
    );
  }
  return [];
}

function validateChoices(state, sideId, candidates) {
  // Reuse one restored battle for the entire candidate set. Side.choose() only mutates
  // choice/request bookkeeping, so clearing the choice is enough between validations;
  // no turn is advanced until both players have submitted choices.
  const branch = Battle.fromJSON(JSON.stringify(state));
  branch.restart(() => {});
  const side = sideId === "p1" ? branch.p1 : branch.p2;
  const legal = new Set();
  try {
    for (const candidate of candidates) {
      try {
        side.clearChoice();
        if (candidate === "") {
          if (
            side.requestState === "" ||
            !side.activeRequest ||
            side.activeRequest.wait
          ) {
            legal.add("");
          }
          continue;
        }
        if (!side.choose(candidate) || !side.isChoiceDone()) continue;
        legal.add(side.getChoice());
      } catch {
        // A rejected candidate must not poison validation of later candidates.
        side.clearChoice();
      }
    }
  } finally {
    branch.destroy();
  }
  return [...legal].sort();
}

function isPubliclyStructurallySelectable(choice, request, gameType) {
  const commands = choice.split(",").map((command) => command.trim());
  const switchSlots = [];
  let transformationCount = 0;

  if (request?.active && commands.length !== request.active.length) return false;
  if (request?.forceSwitch && commands.length !== request.forceSwitch.length) {
    return false;
  }

  const hasParty = Array.isArray(request?.side?.pokemon);
  const healthySwitches = new Set(
    hasParty ? availableSwitches(request) : [],
  );
  const revivalTargets = new Set(
    hasParty ? availableRevivalTargets(request) : [],
  );

  for (const [slot, command] of commands.entries()) {
    const tokens = command.split(/\s+/);
    if (tokens[0] === "switch" && /^\d+$/.test(tokens[1] || "")) {
      switchSlots.push(tokens[1]);
    }

    if (request?.active) {
      const active = request.active[slot];
      const pokemon = request.side.pokemon[slot];
      const mustPass = !active || isFainted(pokemon) || pokemon.commanding;
      if (mustPass) {
        if (tokens[0] !== "pass") return false;
        continue;
      }
      if (tokens[0] === "pass") return false;
      if (tokens[0] === "switch") {
        if (active.trapped) return false;
        if (!healthySwitches.has(command)) return false;
        continue;
      }
      if (tokens[0] !== "move") return false;
    }

    if (request?.forceSwitch) {
      if (!request.forceSwitch[slot]) {
        if (tokens[0] !== "pass") return false;
        continue;
      }
      if (request.side.pokemon[slot]?.reviving) {
        if (!revivalTargets.has(command)) return false;
        continue;
      }
      if (tokens[0] !== "switch" && tokens[0] !== "pass") return false;
      if (tokens[0] === "switch" && !healthySwitches.has(command)) return false;
    }

    const transformations = tokens.filter((token) =>
      token === "mega" ||
      token === "megax" ||
      token === "megay" ||
      token === "ultra"
    );
    transformationCount += transformations.length;

    if (tokens[0] !== "move" || !request?.active?.[slot]) continue;

    const active = request.active[slot];
    const move = active.moves.find((entry) => entry.id === tokens[1]);
    if (!move || move.disabled) return false;

    const targetToken = tokens.slice(2).find((token) =>
      /^[+-]\d+$/.test(token)
    );
    const targetLoc = targetToken ? Number(targetToken) : 0;
    const targetIsChoosable = PUBLIC_CHOOSABLE_TARGETS.has(move.target);

    if (targetIsChoosable && request.active.length >= 2) {
      if (!targetLoc) return false;
      if (
        !publicValidTargetLoc(
          targetLoc,
          slot,
          move.target,
          request.active.length,
          gameType,
        )
      ) {
        return false;
      }
    } else if (targetLoc) {
      return false;
    }

    for (const transformation of transformations) {
      if (transformation === "mega" && !active.canMegaEvo) return false;
      if (transformation === "megax" && !active.canMegaEvoX) return false;
      if (transformation === "megay" && !active.canMegaEvoY) return false;
      if (transformation === "ultra" && !active.canUltraBurst) return false;
    }
  }

  // One bench Pokemon cannot fill two active slots, and one side cannot spend
  // the same once-per-battle transformation twice in a joint command. These
  // constraints depend only on the side's public request, not hidden opponent state.
  if (new Set(switchSlots).size !== switchSlots.length) return false;
  if (transformationCount > 1) return false;
  return true;
}

function publicChoiceCandidates(battle, sideId) {
  if (sideId !== "p1" && sideId !== "p2") {
    throw new Error("side must be p1 or p2");
  }
  if (battle.ended) return [];
  const side = sideId === "p1" ? battle.p1 : battle.p2;
  const request = side.activeRequest;
  const choices = proposedChoices(battle, side).filter((choice) =>
    isPubliclyStructurallySelectable(choice, request, battle.gameType)
  );

  // Never probe a maybe-trapped slot against the exact hidden live state before
  // sealing. Showdown deliberately exposes maybeTrapped when switching might be
  // unavailable because of hidden opponent information. Until we have an explicit
  // unavailable-choice retry protocol, keep only choices that are certainly
  // selectable from the public request.
  if (!request?.active) return [...new Set(choices)].sort();

  const uncertainSlots = new Set(
    request.active
      .map((active, index) => ({ active, index }))
      .filter(({ active }) => active?.maybeTrapped || active?.maybeLocked)
      .map(({ index }) => index),
  );
  if (!uncertainSlots.size) return [...new Set(choices)].sort();

  const certain = choices.filter((choice) => {
    const commands = choice.split(",").map((command) => command.trim());
    for (const slot of uncertainSlots) {
      if (commands[slot]?.startsWith("switch ")) return false;
    }
    return true;
  });
  return [...new Set(certain)].sort();
}

function enumerateLegalChoices(battle, sideId) {
  if (sideId !== "p1" && sideId !== "p2") {
    throw new Error("side must be p1 or p2");
  }
  if (battle.ended) return [];
  const side = sideId === "p1" ? battle.p1 : battle.p2;
  return validateChoices(battle.toJSON(), sideId, proposedChoices(battle, side));
}

const RECOVERY_STATS = ["hp", "atk", "def", "spa", "spd", "spe"];
const RECOVERY_NON_HP_STATS = ["atk", "def", "spa", "spd", "spe"];
const CHAMPIONS_STAT_POINT_CAP = 32;
const CHAMPIONS_TOTAL_STAT_POINTS = 66;

function recoveryStatPoints(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const normalized = {};
  let total = 0;
  for (const stat of RECOVERY_STATS) {
    const points = value[stat];
    if (!Number.isInteger(points)) return null;
    if (points < 0 || points > CHAMPIONS_STAT_POINT_CAP) return null;
    normalized[stat] = points;
    total += points;
  }
  if (total > CHAMPIONS_TOTAL_STAT_POINTS) return null;
  return normalized;
}

function materializeRecoveryStatProposal(state, sideId, proposal) {
  const battle = Battle.fromJSON(JSON.stringify(state));
  battle.restart(() => {});
  try {
    const side = sideId === "p1" ? battle.p1 : battle.p2;
    const pokemonIndex = proposal.pokemon_index;
    if (
      !Number.isInteger(pokemonIndex) ||
      pokemonIndex < 0 ||
      pokemonIndex >= side.pokemon.length
    ) {
      return { proposal_id: proposal.proposal_id, rejected: "invalid-pokemon-index" };
    }

    const pokemon = side.pokemon[pokemonIndex];
    if (pokemon.transformed) {
      return { proposal_id: proposal.proposal_id, rejected: "transformed-pokemon" };
    }

    for (const stat of RECOVERY_NON_HP_STATS) {
      if (pokemon.storedStats[stat] !== pokemon.baseStoredStats[stat]) {
        return {
          proposal_id: proposal.proposal_id,
          rejected: "temporary-stored-stat-mutation",
        };
      }
    }

    const points = recoveryStatPoints(proposal.stat_points);
    if (!points) {
      return { proposal_id: proposal.proposal_id, rejected: "invalid-stat-points" };
    }
    const currentHpPoints = Number(pokemon.set.evs?.hp || 0);
    if (points.hp !== currentHpPoints) {
      return { proposal_id: proposal.proposal_id, rejected: "hp-broadening-disabled" };
    }

    pokemon.set.evs = { ...points };
    const recalculated = battle.spreadModify(pokemon.species.baseStats, pokemon.set);
    if (recalculated.hp !== pokemon.baseMaxhp) {
      return {
        proposal_id: proposal.proposal_id,
        rejected: "hp-rematerialization-changed-maxhp",
      };
    }

    for (const stat of RECOVERY_STATS) {
      pokemon.baseStoredStats[stat] = recalculated[stat];
    }
    for (const stat of RECOVERY_NON_HP_STATS) {
      pokemon.storedStats[stat] = recalculated[stat];
    }
    pokemon.updateSpeed();

    return {
      proposal_id: proposal.proposal_id,
      state: battle.toJSON(),
      stats: { ...recalculated },
    };
  } finally {
    battle.destroy();
  }
}

function materializeRecoveryStatProposals(request) {
  if (!request.state) {
    throw new Error("materialize_recovery_stat_proposals requires state");
  }
  if (request.side !== "p1" && request.side !== "p2") {
    throw new Error("materialize_recovery_stat_proposals requires p1 or p2 side");
  }
  if (!Array.isArray(request.proposals) || request.proposals.length === 0) {
    throw new Error("materialize_recovery_stat_proposals requires proposals");
  }
  if (request.proposals.length > 256) {
    throw new Error("materialize_recovery_stat_proposals accepts at most 256 proposals");
  }

  const ids = new Set();
  for (const proposal of request.proposals) {
    if (!proposal || typeof proposal !== "object") {
      throw new Error("recovery stat proposal must be an object");
    }
    if (typeof proposal.proposal_id !== "string" || !proposal.proposal_id) {
      throw new Error("recovery stat proposal requires proposal_id");
    }
    if (ids.has(proposal.proposal_id)) {
      throw new Error("recovery stat proposal ids must be unique");
    }
    ids.add(proposal.proposal_id);
  }

  return {
    proposals: request.proposals.map((proposal) =>
      materializeRecoveryStatProposal(request.state, request.side, proposal)
    ),
  };
}

function validateRecoveryStatCandidate(request) {
  if (!request.state) {
    throw new Error("validate_recovery_stat_candidate requires state");
  }
  if (request.side !== "p1" && request.side !== "p2") {
    throw new Error("validate_recovery_stat_candidate requires p1 or p2 side");
  }

  const points = recoveryStatPoints(request.stat_points);
  if (!points) {
    return { valid: false, reason: "invalid-stat-points" };
  }

  const pokemonIndex = request.pokemon_index;
  const sideIndex = request.side === "p1" ? 0 : 1;
  const rawSides = request.state.sides;
  if (
    !Number.isInteger(pokemonIndex) ||
    pokemonIndex < 0 ||
    !Array.isArray(rawSides) ||
    !rawSides[sideIndex] ||
    !Array.isArray(rawSides[sideIndex].pokemon) ||
    pokemonIndex >= rawSides[sideIndex].pokemon.length
  ) {
    return { valid: false, reason: "invalid-pokemon-index" };
  }

  const rawPokemon = rawSides[sideIndex].pokemon[pokemonIndex];
  if (!rawPokemon || typeof rawPokemon !== "object") {
    return { valid: false, reason: "invalid-pokemon-state" };
  }
  const rawSet = rawPokemon.set;
  const rawPoints = recoveryStatPoints(rawSet && rawSet.evs);
  if (
    !rawPoints ||
    RECOVERY_STATS.some((stat) => rawPoints[stat] !== points[stat])
  ) {
    return { valid: false, reason: "stat-point-mismatch" };
  }

  const battle = Battle.fromJSON(JSON.stringify(request.state));
  battle.restart(() => {});
  try {
    const side = request.side === "p1" ? battle.p1 : battle.p2;
    const pokemon = side.pokemon[pokemonIndex];
    if (pokemon.transformed) {
      return { valid: false, reason: "transformed-pokemon" };
    }

    const recalculated = battle.spreadModify(pokemon.species.baseStats, pokemon.set);
    if (recalculated.hp !== rawPokemon.baseMaxhp) {
      return { valid: false, reason: "maxhp-mismatch" };
    }

    for (const stat of RECOVERY_STATS) {
      if (
        !rawPokemon.baseStoredStats ||
        rawPokemon.baseStoredStats[stat] !== recalculated[stat]
      ) {
        return { valid: false, reason: `base-stored-${stat}-mismatch` };
      }
    }
    for (const stat of RECOVERY_NON_HP_STATS) {
      if (
        !rawPokemon.storedStats ||
        rawPokemon.storedStats[stat] !== recalculated[stat]
      ) {
        return { valid: false, reason: `stored-${stat}-mismatch` };
      }
    }

    const serializedSpeed = rawPokemon.speed;
    pokemon.updateSpeed();
    if (pokemon.speed !== serializedSpeed) {
      return { valid: false, reason: "speed-mismatch" };
    }

    return { valid: true };
  } finally {
    battle.destroy();
  }
}

function stateView(request) {
  if (!request.state) {
    throw new Error("state_view requires a serialized battle state");
  }
  const sideId = request.side || "p1";
  const battle = Battle.fromJSON(JSON.stringify(request.state));
  battle.restart(() => {});
  try {
    const previews = request.previews || {
      p1: battle.p1.pokemon.map((mon) => mon.set.species),
      p2: battle.p2.pokemon.map((mon) => mon.set.species),
    };
    return {
      side: sideId,
      view: playerView(battle, sideId, previews),
    };
  } finally {
    battle.destroy();
  }
}

function legalChoices(request) {
  if (!request.state) {
    throw new Error("legal_choices requires a serialized battle state");
  }
  const battle = Battle.fromJSON(JSON.stringify(request.state));
  battle.restart(() => {});
  try {
    return {
      side: request.side,
      choices: enumerateLegalChoices(battle, request.side),
    };
  } finally {
    battle.destroy();
  }
}

function validateRequestedChoices(request) {
  if (!request.state) {
    throw new Error("validate_choices requires a serialized battle state");
  }
  if (!Array.isArray(request.candidates) || !request.candidates.length) {
    throw new Error("validate_choices requires non-empty candidates");
  }
  if (!request.candidates.every((candidate) => typeof candidate === "string")) {
    throw new Error("validate_choices candidates must be strings");
  }
  return {
    side: request.side,
    choices: validateChoices(request.state, request.side, request.candidates),
  };
}

function battleOptions(request) {
  const options = {
    formatid: request.format,
    strictChoices: request.strict_choices !== false,
    p1: {
      name: request.p1_name || "Search P1",
      team: importTeam(request.p1_team),
    },
    p2: {
      name: request.p2_name || "Search P2",
      team: importTeam(request.p2_team),
    },
  };

  if (request.seed) {
    options.seed = request.seed;
  }

  return options;
}

function createBattle(request) {
  const battle = new Battle(battleOptions(request));

  if (request.p1_preview || request.p2_preview) {
    if (!request.p1_preview || !request.p2_preview) {
      battle.destroy();
      throw new Error("Both preview choices are required when either is provided");
    }
    battle.makeChoices(request.p1_preview, request.p2_preview);
  }

  const response = {
    state: battle.toJSON(),
    summary: summarize(battle),
  };
  battle.destroy();
  return response;
}

function resolveBranch(
  state,
  p1Choice,
  p2Choice,
  includeState = true,
  rngSeed = null,
  viewSide = null,
  previews = null,
) {
  if (!state) {
    throw new Error("branch requires a serialized battle state");
  }
  if (typeof p1Choice !== "string" || typeof p2Choice !== "string") {
    throw new Error("branch requires p1_choice and p2_choice strings");
  }

  const battle = Battle.fromJSON(JSON.stringify(state));
  battle.restart(() => {});
  if (rngSeed !== null) {
    if (typeof rngSeed !== "string") {
      battle.destroy();
      throw new Error("rng_seed must be a string");
    }
    battle.resetRNG(rngSeed);
  }

  battle.makeChoices(p1Choice, p2Choice);

  const response = {
    summary: summarize(battle),
  };
  if (includeState) response.state = battle.toJSON();
  if (viewSide !== null) {
    const effectivePreviews = previews || {
      p1: battle.p1.pokemon.map((mon) => mon.set.species),
      p2: battle.p2.pokemon.map((mon) => mon.set.species),
    };
    response.view = playerView(battle, viewSide, effectivePreviews);
  }
  battle.destroy();
  return response;
}

function branchBattle(request) {
  return resolveBranch(
    request.state,
    request.p1_choice,
    request.p2_choice,
    request.include_state !== false,
    request.rng_seed ?? null,
    request.view_side ?? null,
    request.previews ?? null,
  );
}

function branchMany(request) {
  if (!request.state) {
    throw new Error("branch_many requires a serialized battle state");
  }
  if (!Array.isArray(request.branches) || request.branches.length === 0) {
    throw new Error("branch_many requires a non-empty branches array");
  }
  if (request.branches.length > 10000) {
    throw new Error("branch_many accepts at most 10000 branches");
  }

  return {
    branches: request.branches.map((branch, index) => {
      try {
        return {
          index,
          ...resolveBranch(
            request.state,
            branch.p1_choice,
            branch.p2_choice,
            branch.include_state === true,
            branch.rng_seed ?? null,
            branch.view_side ?? null,
            branch.previews ?? null,
          ),
        };
      } catch (error) {
        throw new Error(
          `branch_many branch ${index} failed: ${
            error instanceof Error ? error.message : String(error)
          }`,
        );
      }
    }),
  };
}

function markSafeRetry(error) {
  if (error instanceof Error) {
    error.safeRetry = true;
    return error;
  }
  const wrapped = new Error(String(error));
  wrapped.safeRetry = true;
  return wrapped;
}

function getSession(sessionId) {
  const battle = sessions.get(sessionId);
  if (!battle) {
    throw new Error(`Unknown battle session: ${sessionId}`);
  }
  return battle;
}

function startSession(request) {
  const battle = new Battle(battleOptions(request));
  const sessionId = `session-${nextSessionId++}`;
  try {
    const previews = {
      p1: battle.p1.pokemon.map((mon) => mon.set.species),
      p2: battle.p2.pokemon.map((mon) => mon.set.species),
    };
    const view = playerView(battle, "p1", previews);

    // Do not publish ownership until every response component is built.
    // A thrown serialization/view error must not leave an unreachable live session.
    sessions.set(sessionId, battle);
    sessionPreviewSpecies.set(sessionId, previews);
    return {
      session_id: sessionId,
      view,
    };
  } catch (error) {
    try {
      battle.destroy();
    } finally {
      sessions.delete(sessionId);
      sessionPreviewSpecies.delete(sessionId);
    }
    throw markSafeRetry(error);
  }
}

function sessionView(request) {
  const battle = getSession(request.session_id);
  const sideId = request.side || "p1";
  return {
    session_id: request.session_id,
    side: sideId,
    view: playerView(
      battle,
      sideId,
      sessionPreviewSpecies.get(request.session_id),
    ),
  };
}

function sessionSnapshot(request) {
  const battle = getSession(request.session_id);
  return {
    session_id: request.session_id,
    state: battle.toJSON(),
    summary: summarize(battle),
  };
}

function sessionPublicChoices(request) {
  const battle = getSession(request.session_id);
  return {
    session_id: request.session_id,
    side: request.side,
    choices: publicChoiceCandidates(battle, request.side),
  };
}

function sessionLegalChoices(request) {
  const battle = getSession(request.session_id);
  return {
    session_id: request.session_id,
    side: request.side,
    choices: enumerateLegalChoices(battle, request.side),
  };
}

function sessionChoose(request) {
  const battle = getSession(request.session_id);
  if (typeof request.p1_choice !== "string" || typeof request.p2_choice !== "string") {
    throw new Error("session_choose requires p1_choice and p2_choice strings");
  }

  // Battle#makeChoices submits sides sequentially. If either choice or the
  // response-view construction throws, restore the exact pre-submit snapshot.
  // An explicit request error must therefore mean the live mutation did not stick.
  const before = battle.toJSON();
  try {
    battle.makeChoices(request.p1_choice, request.p2_choice);
    const view = playerView(
      battle,
      "p1",
      sessionPreviewSpecies.get(request.session_id),
    );
    return {
      session_id: request.session_id,
      view,
    };
  } catch (error) {
    try {
      battle.destroy();
      const restored = Battle.fromJSON(JSON.stringify(before));
      restored.restart(() => {});
      sessions.set(request.session_id, restored);
    } catch (rollbackError) {
      sessions.delete(request.session_id);
      sessionPreviewSpecies.delete(request.session_id);
      throw new Error(
        `session_choose rollback failed: ${
          rollbackError instanceof Error ? rollbackError.message : String(rollbackError)
        }`,
      );
    }
    throw markSafeRetry(error);
  }
}

function closeSession(request) {
  const battle = getSession(request.session_id);
  battle.destroy();
  sessions.delete(request.session_id);
  sessionPreviewSpecies.delete(request.session_id);
  return {
    session_id: request.session_id,
    closed: true,
  };
}

function handle(request) {
  switch (request.op) {
    case "ping":
      return { pong: true };
    case "create":
      return createBattle(request);
    case "branch":
      return branchBattle(request);
    case "branch_many":
      return branchMany(request);
    case "legal_choices":
      return legalChoices(request);
    case "validate_choices":
      return validateRequestedChoices(request);
    case "materialize_recovery_stat_proposals":
      return materializeRecoveryStatProposals(request);
    case "validate_recovery_stat_candidate":
      return validateRecoveryStatCandidate(request);
    case "state_view":
      return stateView(request);
    case "session_start":
      return startSession(request);
    case "session_view":
      return sessionView(request);
    case "session_snapshot":
      return sessionSnapshot(request);
    case "session_public_choices":
      return sessionPublicChoices(request);
    case "session_legal_choices":
      return sessionLegalChoices(request);
    case "session_choose":
      return sessionChoose(request);
    case "session_close":
      return closeSession(request);
    default:
      throw new Error(`Unknown operation: ${request.op}`);
  }
}

function destroySessions() {
  for (const battle of sessions.values()) {
    battle.destroy();
  }
  sessions.clear();
  sessionPreviewSpecies.clear();
}

process.on("exit", destroySessions);

const rl = readline.createInterface({
  input: process.stdin,
  crlfDelay: Infinity,
});

rl.on("line", (line) => {
  if (!line.trim()) return;

  let id = null;
  try {
    const request = JSON.parse(line);
    id = request.id ?? null;
    const result = handle(request);
    process.stdout.write(JSON.stringify({ id, ok: true, result }) + "\n");
  } catch (error) {
    process.stdout.write(
      JSON.stringify({
        id,
        ok: false,
        error: error instanceof Error ? error.message : String(error),
        safe_retry: error instanceof Error && error.safeRetry === true,
      }) + "\n",
    );
  }
});
