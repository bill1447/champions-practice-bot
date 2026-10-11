"use strict";

const readline = require("readline");
const path = require("path");
const { createHash } = require("node:crypto");
const { isDeepStrictEqual } = require("node:util");

const root = path.resolve(__dirname, "..");
const showdownRoot = path.join(root, "external", "pokemon-showdown");
const {
  Battle,
  extractChannelMessages,
} = require(path.join(showdownRoot, "dist", "sim", "battle"));
const { Teams } = require(path.join(showdownRoot, "dist", "sim", "teams"));
const { TeamValidator } = require(
  path.join(showdownRoot, "dist", "sim", "team-validator"),
);
const { State } = require(path.join(showdownRoot, "dist", "sim", "state"));
const { PRNG } = require(path.join(showdownRoot, "dist", "sim", "prng"));

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

function moveMetadata(request) {
  if (typeof request.format !== "string" || !request.format) {
    throw new Error("move_metadata requires a format");
  }
  if (
    !Array.isArray(request.moves) ||
    request.moves.length === 0 ||
    request.moves.length > 4096 ||
    !request.moves.every((move) => typeof move === "string" && move)
  ) {
    throw new Error("move_metadata requires 1-4096 move ids");
  }

  const dex = TeamValidator.get(request.format).dex;
  const seen = new Set();
  const moves = [];
  for (const requested of request.moves) {
    const id = toId(requested);
    if (!id || seen.has(id)) continue;
    seen.add(id);
    const move = dex.moves.get(id);
    moves.push({
      requested: id,
      exists: !!move.exists,
      id: move.exists ? move.id : id,
      name: move.exists ? move.name : null,
      target: move.exists ? move.target : null,
      category: move.exists ? move.category : null,
    });
  }
  return { moves };
}

function validateTeamText(request) {
  if (typeof request.format !== "string" || !request.format) {
    throw new Error("validate_team requires a format");
  }
  if (typeof request.team_text !== "string" || !request.team_text.trim()) {
    throw new Error("validate_team requires non-empty team_text");
  }
  const team = importTeam(request.team_text);
  const problems = TeamValidator.get(request.format).validateTeam(team);
  return {
    valid: !problems || problems.length === 0,
    problems: problems ? [...problems] : [],
    team_size: team.length,
    packed_team: Teams.pack(team),
    canonical_text: Teams.export(team, { useStatPoints: true }),
    sets: cloneJson(team),
  };
}

function cloneJson(value) {
  if (value === undefined) return null;
  return JSON.parse(JSON.stringify(value));
}

function hpPercent(mon) {
  if (!mon || !mon.maxhp) return 0;
  return Math.round((mon.hp / mon.maxhp) * 1000) / 10;
}

function championsPublicHpPercent(mon) {
  if (!mon || !mon.maxhp || mon.hp <= 0) return 0;
  return Math.floor(100 * mon.hp / mon.maxhp) || 1;
}

function publicActive(mon, identity) {
  if (!mon || !identity) return null;
  return {
    species: identity.visibleSpecies,
    base_species: identity.baseSpecies,
    hp_percent: identity.hpPercent ?? championsPublicHpPercent(mon),
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
  let beforeAnyResolvedAction = false;
  const byTurn = new Map();

  function slotIdentity(value) {
    const slot = String(value || "").split(":", 1)[0];
    if (!/^p[12][a-z]$/.test(slot)) return null;
    return {
      side: slot.slice(0, 2),
      slot: slot.charCodeAt(2) - "a".charCodeAt(0) + 1,
    };
  }

  function turnActions() {
    if (!byTurn.has(logTurn)) byTurn.set(logTurn, new Map());
    return byTurn.get(logTurn);
  }

  function addSelectedAction(slot, action) {
    const actions = turnActions();
    const previous = actions.get(slot);
    if (previous === undefined) {
      actions.set(slot, action);
      return;
    }
    // A second incompatible public event for the same active slot means the
    // protocol trace no longer proves one selected command (for example a
    // forced switch after a selected switch, or a called/nested move). Leave
    // the slot unconstrained instead of inferring private intent.
    if (JSON.stringify(previous) !== JSON.stringify(action)) {
      actions.set(slot, null);
    }
  }

  for (const line of visibleLog) {
    const parts = line.split("|");
    const event = parts[1];

    if (event === "turn") {
      const parsed = Number(parts[2]);
      logTurn = Number.isInteger(parsed) && parsed > 0 ? parsed : 0;
      beforeAnyResolvedAction = logTurn > 0;
      continue;
    }
    if (logTurn <= 0) continue;

    const actor = slotIdentity(parts[2]);

    // Normal selected switches resolve before ordinary move/cant events.
    // Only a plain channel-visible "switch" in that prefix is admitted as
    // selected-command evidence. "drag" and "replace" are never promoted,
    // and pivot/eject/forced switches occur after resolution has begun. If a
    // slot switches twice in the prefix, addSelectedAction marks it ambiguous.
    if (
      event === "switch" &&
      beforeAnyResolvedAction &&
      actor &&
      actor.side === opponentPrefix
    ) {
      // Pinned Showdown annotates effect-driven switches with public
      // "[from] ..." provenance. Those are consequences of an earlier action,
      // not proof that this switch was the slot's submitted command.
      const sourceDriven = parts.slice(4).some(
        (part) => String(part).trim().toLowerCase().startsWith("[from]"),
      );
      if (!sourceDriven) {
        const species = toId(String(parts[3] || "").split(",", 1)[0]);
        if (species) {
          addSelectedAction(actor.slot, {
            turn: logTurn,
            slot: actor.slot,
            switch_species: species,
          });
        }
      }
      continue;
    }

    if (event === "drag" || event === "replace") {
      // Never infer a submitted switch from explicitly forced/projection-only
      // protocol events. A forced event on a slot already carrying a prefix
      // switch also invalidates that selected-switch inference.
      if (
        beforeAnyResolvedAction &&
        actor &&
        actor.side === opponentPrefix &&
        turnActions().has(actor.slot)
      ) {
        turnActions().set(actor.slot, null);
      }
      continue;
    }

    if (event === "move" || event === "cant") {
      beforeAnyResolvedAction = false;
    }
    if (event !== "move") continue;

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

    addSelectedAction(actor.slot, {
      turn: logTurn,
      slot: actor.slot,
      move,
      target: targetLocation,
    });
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
    const match = hp.match(/^(\d+)\/(\d+)([gry])?$/i);
    if (!match) return {};
    const current = Number(match[1]);
    const maximum = Number(match[2]);
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
    // Own-side information, including benched PP; never export for opponents.
    move_pp: mon.moveSlots.map((slot) => ({
      id: slot.id, pp: slot.pp, maxpp: slot.maxpp,
    })),
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

const FORCED_WAIT_CHOICE = "wait";

function exactChoiceForShowdown(battle, sideId, choice) {
  if (choice === "") {
    throw new Error(
      "[Invalid choice] Empty choice is ambiguous; use the explicit forced-wait token",
    );
  }
  if (choice !== FORCED_WAIT_CHOICE) return choice;

  const side = sideId === "p1" ? battle.p1 : battle.p2;
  if (!side.activeRequest || side.activeRequest.wait !== true) {
    throw new Error(
      `[Unavailable choice] ${sideId} is not currently forced to wait`,
    );
  }
  return "";
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
  let enabledMoveCount = 0;
  for (const move of active.moves) {
    if (move.disabled) continue;
    enabledMoveCount++;
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

  // Showdown's public "testfight" protocol can disclose that the final active
  // has no enabled moves without revealing which hidden foe set caused it. In
  // that exact case, "auto" is the protocol-safe way to let Showdown choose the
  // forced Struggle. Restrict this to the last active: Side#autoChoose finishes
  // every remaining slot, so using it earlier would surrender unrelated choices.
  if (
    enabledMoveCount === 0 &&
    slot === request.active.length - 1
  ) {
    choices.push("auto");
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
  if (!request) return [];
  if (request.wait) return [FORCED_WAIT_CHOICE];
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
  //
  // Keep one *replayable input command* for each canonical action. Showdown
  // serializes an auto-selected forced Struggle as "move struggle", but that
  // canonical string cannot itself be submitted again because Struggle is not
  // present in the Pokemon's move request. In that case preserve the original
  // validated candidate (for example "auto" or a disabled request move) while
  // still deduplicating all candidates that resolve to the same action.
  const branch = Battle.fromJSON(JSON.stringify(state));
  branch.restart(() => {});
  const side = sideId === "p1" ? branch.p1 : branch.p2;
  const legalByCanonicalChoice = new Map();
  try {
    for (const candidate of candidates) {
      try {
        side.clearChoice();
        if (candidate === FORCED_WAIT_CHOICE) {
          if (side.activeRequest?.wait === true) {
            legalByCanonicalChoice.set(FORCED_WAIT_CHOICE, FORCED_WAIT_CHOICE);
          }
          continue;
        }
        if (candidate === "") continue;
        if (!side.choose(candidate) || !side.isChoiceDone()) continue;
        const canonical = side.getChoice();
        const forcedStruggle = canonical
          .split(",")
          .some((command) => command.trim().startsWith("move struggle"));
        if (!legalByCanonicalChoice.has(canonical)) {
          legalByCanonicalChoice.set(
            canonical,
            forcedStruggle ? candidate : canonical,
          );
        }
      } catch {
        // A rejected candidate must not poison validation of later candidates.
        side.clearChoice();
      }
    }
  } finally {
    branch.destroy();
  }
  return [...legalByCanonicalChoice.values()].sort();
}

function isPubliclyStructurallySelectable(choice, request, gameType) {
  if (choice === FORCED_WAIT_CHOICE) return request?.wait === true;
  if (!choice || request?.wait === true) return false;
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
      if (tokens[0] === "auto") {
        if (slot !== request.active.length - 1) return false;
        if (!active.moves.length || active.moves.some((move) => !move.disabled)) {
          return false;
        }
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

function publicChoiceCandidatesFromRequest(battle, sideId) {
  const side = sideId === "p1" ? battle.p1 : battle.p2;
  const request = side.activeRequest;
  const choices = proposedChoices(battle, side).filter((choice) =>
    isPubliclyStructurallySelectable(choice, request, battle.gameType)
  );

  // Never probe a maybe-trapped slot against the exact hidden live state before
  // sealing. Showdown deliberately exposes maybeTrapped when switching might be
  // unavailable because of hidden opponent information. Keep only choices that
  // are certainly selectable from the public request.
  if (!request?.active) return [...new Set(choices)].sort();

  const uncertainSwitchSlots = new Set(
    request.active
      .map((active, index) => ({ active, index }))
      .filter(({ active }) => active?.maybeTrapped || active?.maybeLocked)
      .map(({ index }) => index),
  );
  if (!uncertainSwitchSlots.size) return [...new Set(choices)].sort();

  const certain = choices.filter((choice) => {
    const commands = choice.split(",").map((command) => command.trim());
    for (const slot of uncertainSwitchSlots) {
      if (commands[slot]?.startsWith("switch ")) return false;
    }
    return true;
  });
  return [...new Set(certain)].sort();
}

function publicChoiceCandidates(battle, sideId) {
  if (sideId !== "p1" && sideId !== "p2") {
    throw new Error("side must be p1 or p2");
  }
  if (battle.ended) return [];

  const side = sideId === "p1" ? battle.p1 : battle.p2;
  const request = side.activeRequest;
  const needsFightProbe = request?.active?.some(
    (active) => active?.maybeDisabled || active?.maybeLocked,
  );
  if (!needsFightProbe) {
    return publicChoiceCandidatesFromRequest(battle, sideId);
  }

  // Showdown intentionally hides some Imprison/locking information behind the
  // public "testfight" protocol. Do not replace that with exact hidden-state
  // legality probing. Instead, fork the battle and invoke Showdown's own
  // updateDisabledRequest routine -- the same request update used by testfight --
  // then derive choices only from the resulting player-visible request.
  const probe = Battle.fromJSON(JSON.stringify(battle.toJSON()));
  probe.restart(() => {});
  try {
    const probeSide = sideId === "p1" ? probe.p1 : probe.p2;
    const probeRequest = probeSide.activeRequest;
    if (probeRequest?.active) {
      for (const [slot, active] of probeRequest.active.entries()) {
        if (!active?.maybeDisabled && !active?.maybeLocked) continue;
        const pokemon = probeSide.active[slot];
        if (!pokemon) continue;
        probeSide.updateDisabledRequest(pokemon, active);
      }
    }
    return publicChoiceCandidatesFromRequest(probe, sideId);
  } finally {
    probe.destroy();
  }
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

function validateRecoveryOpeningInputs(request) {
  if (
    typeof request.format !== "string" ||
    !request.format ||
    typeof request.p1_team !== "string" ||
    !request.p1_team ||
    typeof request.p2_team !== "string" ||
    !request.p2_team ||
    typeof request.seed !== "string" ||
    !request.seed
  ) {
    throw new Error(
      "recovery opening authority requires exact format, teams, and RNG seed",
    );
  }
  if (
    typeof request.p1_preview !== "string" ||
    !request.p1_preview ||
    typeof request.p2_preview !== "string" ||
    !request.p2_preview
  ) {
    throw new Error("recovery opening authority requires exact preview choices");
  }
}

function recoveryOpeningOptions(request) {
  validateRecoveryOpeningInputs(request);
  return battleOptions({
    format: request.format,
    p1_team: request.p1_team,
    p2_team: request.p2_team,
    p1_name: request.p1_name || "Search P1",
    p2_name: request.p2_name || "Search P2",
    seed: request.seed,
  });
}

function applyRecoveryOpeningStatProposal(options, sideId, proposal) {
  const points = recoveryStatPoints(proposal.stat_points);
  if (!points) return "invalid-stat-points";
  const team = options[sideId]?.team;
  const pokemonIndex = proposal.pokemon_index;
  if (
    !Array.isArray(team) ||
    !Number.isInteger(pokemonIndex) ||
    pokemonIndex < 0 ||
    pokemonIndex >= team.length
  ) {
    return "invalid-pokemon-index";
  }

  const set = team[pokemonIndex];
  const currentHpPoints = Number(set.evs?.hp || 0);
  if (
    !Number.isInteger(currentHpPoints) ||
    currentHpPoints < 0 ||
    currentHpPoints > CHAMPIONS_STAT_POINT_CAP
  ) {
    return "invalid-current-hp-points";
  }
  if (points.hp !== currentHpPoints) return "hp-broadening-disabled";

  set.evs = { ...points };
  return null;
}

function resolveFreshRecoveryOpening(request, proposal = null) {
  const options = recoveryOpeningOptions(request);
  if (proposal !== null) {
    if (request.side !== "p1" && request.side !== "p2") {
      throw new Error("recovery opening stat proposal requires p1 or p2 side");
    }
    const rejected = applyRecoveryOpeningStatProposal(
      options,
      request.side,
      proposal,
    );
    if (rejected) return { rejected };
  }

  const battle = new Battle(options);
  try {
    const originalPokemon = {
      p1: [...battle.p1.pokemon],
      p2: [...battle.p2.pokemon],
    };
    battle.makeChoices(request.p1_preview, request.p2_preview);
    const lineage = {
      p1: battle.p1.pokemon.map((pokemon) => originalPokemon.p1.indexOf(pokemon)),
      p2: battle.p2.pokemon.map((pokemon) => originalPokemon.p2.indexOf(pokemon)),
    };
    if (
      lineage.p1.some((index) => index < 0) ||
      lineage.p2.some((index) => index < 0)
    ) {
      throw new Error("Could not derive recovery opening member lineage");
    }
    return {
      state: battle.toJSON(),
      preview_lineage: lineage,
    };
  } finally {
    battle.destroy();
  }
}

function normalizedRecoveryState(state) {
  return State.normalize(cloneJson(state));
}

function materializeRecoveryOpeningStatProposals(request) {
  validateRecoveryOpeningInputs(request);
  if (request.side !== "p1" && request.side !== "p2") {
    throw new Error(
      "materialize_recovery_opening_stat_proposals requires p1 or p2 side",
    );
  }
  if (!Array.isArray(request.proposals) || request.proposals.length === 0) {
    throw new Error(
      "materialize_recovery_opening_stat_proposals requires proposals",
    );
  }
  if (request.proposals.length > 256) {
    throw new Error(
      "materialize_recovery_opening_stat_proposals accepts at most 256 proposals",
    );
  }

  const ids = new Set();
  const proposals = request.proposals.map((proposal) => {
    if (!proposal || typeof proposal !== "object") {
      throw new Error("recovery opening stat proposal must be an object");
    }
    if (typeof proposal.proposal_id !== "string" || !proposal.proposal_id) {
      throw new Error("recovery opening stat proposal requires proposal_id");
    }
    if (ids.has(proposal.proposal_id)) {
      throw new Error("recovery opening stat proposal ids must be unique");
    }
    ids.add(proposal.proposal_id);

    const resolved = resolveFreshRecoveryOpening(request, proposal);
    if (resolved.rejected) {
      return {
        proposal_id: proposal.proposal_id,
        rejected: resolved.rejected,
      };
    }
    return {
      proposal_id: proposal.proposal_id,
      state: resolved.state,
    };
  });
  return { proposals };
}

function validateRecoveryOpeningAuthority(request) {
  if (!request.root_state) {
    throw new Error("validate_recovery_opening_authority requires root state");
  }
  const canonical = resolveFreshRecoveryOpening(request);
  if (!canonical.state) {
    throw new Error("could not rebuild recovery opening authority");
  }
  const expectedP1Lineage = request.p1_root_to_input;
  const expectedP2Lineage = request.p2_root_to_input;
  const lineageValid =
    Array.isArray(expectedP1Lineage) &&
    Array.isArray(expectedP2Lineage) &&
    isDeepStrictEqual(canonical.preview_lineage.p1, expectedP1Lineage) &&
    isDeepStrictEqual(canonical.preview_lineage.p2, expectedP2Lineage);
  return {
    valid:
      lineageValid &&
      isDeepStrictEqual(
        normalizedRecoveryState(canonical.state),
        normalizedRecoveryState(request.root_state),
      ),
  };
}

function validateRecoveryOpeningStatCandidate(request) {
  if (!request.candidate_state) {
    throw new Error(
      "validate_recovery_opening_stat_candidate requires candidate state",
    );
  }
  if (request.side !== "p1" && request.side !== "p2") {
    throw new Error(
      "validate_recovery_opening_stat_candidate requires p1 or p2 side",
    );
  }
  const result = resolveFreshRecoveryOpening(request, {
    proposal_id: "validation",
    pokemon_index: request.pokemon_index,
    stat_points: request.stat_points,
  });
  if (!result.state) {
    return {
      valid: false,
      reason: result.rejected || "opening-materialization-rejected",
    };
  }
  return {
    valid: isDeepStrictEqual(
      normalizedRecoveryState(result.state),
      normalizedRecoveryState(request.candidate_state),
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

// #184: mechanics-native HP-only current-state hypothesis construction.
// A same-turn Showdown-produced scaffold is required. This is an *isolated*
// positive candidate operation, NOT proof that unseen history is reachable.
// No live sessions, hidden truth, or arbitrary serialized-state patching.
function materializeCurrentHpHypotheses(request) {
  if (!request.state || !Array.isArray(request.public_hp_buckets) ||
      request.public_hp_buckets.length !== 2) {
    throw new Error("current HP hypotheses need state and two public active HP buckets");
  }
  const limit = request.limit;
  if (!Number.isInteger(limit) || limit < 1 || limit > 8) {
    throw new Error("current HP hypothesis limit must be 1 through 8");
  }
  const baseline = Battle.fromJSON(JSON.stringify(request.state));
  baseline.restart(() => {});
  const outcomes = [];
  let examined = 0;
  let reason = null;
  try {
    if (baseline.requestState !== "move" || baseline.ended) {
      return { outcomes, examined, reason: "unsupported-current-phase" };
    }
    const p1 = baseline.p1;
    const baselineShared = p1.active.map((mon) => mon?.getHealth().shared ?? null);
    for (let slot = 0; slot < p1.active.length && outcomes.length < limit; slot++) {
      const mon = p1.active[slot];
      const bucket = request.public_hp_buckets[slot];
      if (mon === null || mon === undefined || mon.fainted || mon.hp <= 0) {
        continue;
      }
      if (!Number.isInteger(bucket) || bucket < 1 || bucket > 100) {
        return { outcomes: [], examined, reason: "unsupported-public-hp-bucket" };
      }
      // Preserve the exact pinned Champions getHealth() shared producer
      // representation, including the 20%/50% colors, not merely a rounded %.
      if (championsPublicHpPercent(mon) !== bucket) {
        return { outcomes: [], examined, reason: "scaffold-hp-bucket-mismatch" };
      }
      for (let hp = 1; hp <= mon.maxhp && outcomes.length < limit; hp++) {
        if (hp === mon.hp || championsPublicHpPercent({hp, maxhp: mon.maxhp}) !== bucket) {
          continue;
        }
        examined++;
        const child = Battle.fromJSON(JSON.stringify(request.state));
        child.restart(() => {});
        try {
          const target = child.p1.active[slot];
          if (!target || target.fainted || target.hp <= 0 ||
              target.species.id !== mon.species.id) {
            throw new Error("HP hypothesis changed active member identity");
          }
          // Native pinned Showdown setter, not a serialized JSON mutation.
          target.sethp(hp);
          if (target.hp !== hp || target.getHealth().shared !== baselineShared[slot]) {
            continue;
          }
          // Require the candidate to survive full native serialization and
          // deserialization; public projection + exact request checked in Python.
          const state = child.toJSON();
          const restored = Battle.fromJSON(JSON.stringify(state));
          restored.restart(() => {});
          try {
            if (restored.p1.active[slot]?.hp !== hp ||
                restored.p1.active[slot]?.getHealth().shared !== baselineShared[slot]) {
              throw new Error("HP hypothesis roundtrip changed pinned health");
            }
          } finally {
            restored.destroy();
          }
          outcomes.push({ slot, hp, maxhp: target.maxhp, state });
        } finally {
          child.destroy();
        }
      }
    }
    if (!outcomes.length) reason = "no-other-compatible-hp";
    return { outcomes, examined, reason };
  } finally {
    baseline.destroy();
  }
}


// #196: construct bounded present-turn hypotheses from a FRESH public-prior
// Showdown root. This never consumes historical particles, a live session,
// oracle state, or submitted opponent commands. The only exact history comes
// from the player's own request; opponent PP/timers remain hypotheses.
function materializePresentHypotheses(request) {
  const view = request.current_view;
  const limit = request.limit;
  if (!request.state || !view || !Number.isInteger(limit) || limit < 1 || limit > 4) {
    throw new Error("present hypotheses need a fresh root, public view and limit 1..4");
  }
  if (view.phase !== "move" || view.ended || !Number.isInteger(view.turn) ||
      view.turn < 2 || view.turn > 1000 || !view.request ||
      !view.request.side || !Array.isArray(view.player?.team) ||
      !Array.isArray(view.player?.active_details) ||
      !Array.isArray(view.opponent?.active) ||
      !Array.isArray(view.opponent?.revealed)) {
    return { outcomes: [], reason: "unsupported-current-public-phase" };
  }

  const why = (reason, mismatchPath = null, ownSpeedDiagnostic = null) => ({
    outcomes: [], reason,
    ...(mismatchPath ? { mismatch_path: mismatchPath } : {}),
    ...(ownSpeedDiagnostic ? { own_speed_diagnostic: ownSpeedDiagnostic } : {}),
  });
  // Own-side diagnostic only, for offline league forensics. Never include
  // an opponent set, private session, RNG witness or searched action.
  function speedDiagnostic(mon, observed, slot, stage, preRemovalSpeed = null) {
    return {
      stage, slot, species: observed.species,
      observed_speed: observed.speed,
      native_cached_speed: mon.speed,
      native_action_speed: mon.getActionSpeed(),
      native_stored_speed: mon.storedStats.spe,
      speed_boost: mon.boosts.spe,
      status: mon.status || null,
      ability: mon.ability || null,
      item: mon.item || null,
      unburden_volatile: !!mon.volatiles["unburden"],
      trick_room: !!original.field.pseudoWeather["trickroom"],
      terrain: original.field.terrain || null,
      weather: original.field.weather || null,
      ...(preRemovalSpeed === null ? {} :
        { pre_removal_action_speed: preRemovalSpeed }),
    };
  }
  const asId = (value) => toId(value || "");
  const exact = (value) => JSON.stringify(value);
  // Diagnostic only: reveal a FIELD PATH, never the live value or hidden state.
  // Keep exact-JSON equality as the admission requirement.
  function firstMismatchPath(actual, expected, path) {
    if (exact(actual) === exact(expected)) return null;
    if (Array.isArray(actual) && Array.isArray(expected)) {
      for (let i = 0; i < Math.min(actual.length, expected.length); i++) {
        const diff = firstMismatchPath(actual[i], expected[i], `${path}[${i}]`);
        if (diff) return diff;
      }
      return actual.length !== expected.length ? `${path}.length` : path;
    }
    if (actual && expected && typeof actual === "object" &&
        typeof expected === "object" && !Array.isArray(actual) && !Array.isArray(expected)) {
      const keys = [...new Set([...Object.keys(actual), ...Object.keys(expected)])].sort();
      for (const key of keys) {
        if (!(key in actual) || !(key in expected)) return `${path}.${key}`;
        const diff = firstMismatchPath(actual[key], expected[key], `${path}.${key}`);
        if (diff) return diff;
      }
    }
    return path;
  }
  const ownRequested = JSON.stringify(view.request);
  const supportedBoosts = new Set(["atk", "def", "spa", "spd", "spe", "accuracy", "evasion"]);
  const candidates = [];
  const original = Battle.fromJSON(JSON.stringify(request.state));
  const terrainPlan = request.mechanics_plan;
  let terrainSource = null;
  let terrainSourceItem = null;
  if (terrainPlan != null) {
    const sourced = terrainPlan.source_species != null;
    const expectedKeys = sourced
      ? 'opening_terrain,residual_turns,source_ability,source_side,source_species'
      : 'opening_terrain,residual_turns';
    if (Object.keys(terrainPlan).sort().join(',') !== expectedKeys ||
        terrainPlan.opening_terrain !== view.field.terrain ||
        (!sourced && original.field.terrain !== terrainPlan.opening_terrain) ||
        !Number.isInteger(terrainPlan.residual_turns) ||
        (!sourced && terrainPlan.residual_turns !== view.turn - 1) ||
        terrainPlan.residual_turns < 1 || terrainPlan.residual_turns > 7 ||
        view.field.weather || view.field.pseudo_weather.length ||
        view.player.side_conditions.length || view.opponent.side_conditions.length) {
      return why('unsupported-opening-terrain-plan');
    }
    if (sourced) {
      const side = terrainPlan.source_side === 'player' ? original.p2
        : terrainPlan.source_side === 'opponent' ? original.p1 : null;
      const sources = side?.pokemon.filter((mon) =>
        asId(mon.species.name) === asId(terrainPlan.source_species) &&
        mon.ability === terrainPlan.source_ability) || [];
      if (sources.length !== 1) return why('unsupported-terrain-source');
      terrainSource = sources[0];
    } else {
      terrainSource = original.field.terrainState.source;
    }
    if (!terrainSource) return why('unsupported-terrain-source');
    terrainSourceItem = terrainSource.item;
  }
  original.restart(() => {});
  try {
    if (original.turn !== 1 || original.requestState !== "move" || original.ended ||
        original.p1.name !== view.opponent.name ||
        original.p2.name !== view.player.name) {
      return why("root-not-fresh-public-opening");
    }
    // Duplicate base-species identities cannot be associated with public
    // observations from a species-keyed producer. Never guess lineage.
    const allOwn = view.player.team.map((mon) => asId(mon.species));
    const allFoe = view.opponent.revealed.map((mon) => asId(mon.species));
    if (new Set(allOwn).size !== allOwn.length ||
        new Set(allFoe).size !== allFoe.length ||
        allOwn.length !== original.p2.pokemon.length) {
      return why("ambiguous-or-incompatible-roster-identity");
    }

    function find(side, species) {
      const wanted = asId(species);
      // A publicly observed Mega form belongs to its pre-Mega team member.
      // Resolve the identity through the pinned format's species metadata.
      const direct = side.pokemon.find((mon) =>
        asId(mon.baseSpecies.name) === wanted || asId(mon.set.species) === wanted
      );
      if (direct) return direct;
      const nativeSpecies = side.battle.dex.species.get(species);
      // Only a Mega can alias to a different base team identity.
      // Ordinary formes such as Indeedee-F must retain their set identity.
      if (!nativeSpecies.exists || !nativeSpecies.isMega) return undefined;
      const base = asId(nativeSpecies.baseSpecies);
      return side.pokemon.find((mon) => asId(mon.set.species) === base);
    }
    function position(side, identities, path) {
      if (identities.length !== side.active.length) return `${path}.length`;
      for (let slot = 0; slot < identities.length; slot++) {
        const entry = identities[slot];
        const slotPath = `${path}[${slot}]`;
        if (!entry) return `${slotPath}.missing`; // forced-switch state
        const species = typeof entry === "string" ? entry : entry.base_species || entry.species;
        const mon = find(side, species);
        if (!mon) return `${slotPath}.identity`;
        if (side.active[slot] === mon) continue;
        // Do not permute active pointers or bypass pinned native switch rules.
        if (mon.isActive) {
          // A desired member can already occupy the OTHER active slot.
          // Native switchIn rejects an active incoming Pokemon. Stage a
          // non-target bench member into its current slot first, then use
          // pinned native switchIn for the requested position.
          const desiredIds = new Set(identities.filter(Boolean).map((value) =>
            asId(typeof value === "string" ? value : value.base_species || value.species)
          ));
          const staging = side.pokemon.find((candidate) =>
            !candidate.isActive && candidate.hp > 0 &&
            !desiredIds.has(asId(candidate.set.species))
          );
          if (!staging || side.battle.actions.switchIn(staging, mon.position) !== true) {
            return `${slotPath}.already-active`;
          }
        }
        if (!side.active[slot]) return `${slotPath}.empty-native-slot`;
        if (side.battle.actions.switchIn(mon, slot) !== true) {
          return `${slotPath}.native-switch-rejected`;
        }
      }
      return null;
    }
    const ownPositionIssue = position(original.p2, view.player.active_details,
      "$.player.active_details");
    if (ownPositionIssue) return why("unsupported-native-active-position", ownPositionIssue);
    const foePositionIssue = position(original.p1, view.opponent.active,
      "$.opponent.active");
    if (foePositionIssue) return why("unsupported-native-active-position", foePositionIssue);
    const foe = original.p1;
    const own = original.p2;
    // Finish native switch-in events so abilities, weather, terrain, item
    // activation and speed are represented by the actual pinned engine.
    // Clear queued switch-in events before executing them once on the fresh
    // native model. Never fabricate a historical turn's action queue.
    original.queue.clear();
    for (const mon of [...foe.active, ...own.active]) {
      if (mon && !mon.isStarted) original.actions.runSwitch(mon);
    }

    // Only an OWN active Mega form can be re-established from the exact
    // owned item and requested form. Use pinned native evolution mechanics:
    // never write species, ability, stats, or mega-used flags directly.
    for (const observed of view.player.active_details) {
      if (!observed || !observed.species) continue;
      const species = original.dex.species.get(observed.species);
      if (!species.exists || !species.isMega) continue;
      const mon = find(own, observed.species);
      if (!mon || !mon.isActive || asId(mon.species.name) === asId(species.name)) continue;
      if (asId(mon.set.species) !== asId(species.baseSpecies) ||
          !original.actions.runMegaEvo(mon) ||
          asId(mon.species.name) !== asId(species.name)) {
        return why("unsupported-native-own-mega-evolution");
      }
    }

    // A previously Mega-Evolved OWN member may now be on the bench.
    // Temporarily stage it through pinned native switch/evolution mechanics,
    // then restore the exact active position. Never assign species, ability,
    // stats, or Mega flags directly. All resulting requests still pass the
    // exact own-request gate below; any native rejection fails closed.
    for (const [teamIndex, observed] of view.player.team.entries()) {
      if (!observed || observed.active || !observed.species) continue;
      const species = original.dex.species.get(observed.species);
      if (!species.exists || !species.isMega) continue;
      const mon = find(own, observed.species);
      const path = `$.player.team[${teamIndex}].species`;
      if (!mon || mon.isActive ||
          asId(mon.set.species) !== asId(species.baseSpecies) ||
          asId(mon.item) !== asId(observed.item) ||
          !original.dex.items.get(mon.item).megaStone ||
          asId(original.dex.items.get(mon.item).megaStone) !== asId(species.name)) {
        return why("unsupported-native-own-benched-mega", path);
      }
      if (asId(mon.species.name) === asId(species.name)) continue;
      const slot = own.active.findIndex((active) => active && active.hp > 0);
      if (slot < 0) return why("unsupported-native-own-benched-mega", path);
      const displaced = own.active[slot];
      if (original.actions.switchIn(mon, slot) !== true ||
          !original.actions.runMegaEvo(mon) ||
          asId(mon.species.name) !== asId(species.name) ||
          original.actions.switchIn(displaced, slot) !== true ||
          own.active[slot] !== displaced || mon.isActive) {
        return why("unsupported-native-own-benched-mega", path);
      }
    }

    // An opponent Mega is PUBLIC form information, never a license to
    // synthesize an unobserved stone. Only an approved hypothetical set
    // capable of native Mega Evolution can establish the corresponding form.
    for (const observed of view.opponent.active) {
      if (!observed || !observed.species) continue;
      const species = original.dex.species.get(observed.species);
      if (!species.exists || !species.isMega) continue;
      const mon = find(foe, observed.base_species);
      if (!mon || !mon.isActive ||
          asId(mon.set.species) !== asId(species.baseSpecies) ||
          !original.actions.runMegaEvo(mon) ||
          asId(mon.species.name) !== asId(species.name)) {
        return why("unsupported-native-opponent-mega-evolution");
      }
    }

    // Owned facts are exact. Do not synthesize missing own team members,
    // items, abilities, statuses or PP; reject instead.
    for (const [teamIndex, observed] of view.player.team.entries()) {
      const mon = find(own, observed.species);
      const ownPath = `$.player.team[${teamIndex}]`;
      if (!mon || !Number.isInteger(observed.hp) ||
          !Number.isInteger(observed.maxhp) || mon.maxhp !== observed.maxhp ||
          observed.hp < 0 || observed.hp > mon.maxhp) {
        return why("unsupported-exact-own-hp", `${ownPath}.hp`);
      }
      if (asId(observed.species) !== asId(mon.species.name)) {
        return why("unsupported-own-form", `${ownPath}.species`);
      }
      if (observed.hp === 0) {
        mon.faint();
      } else if (mon.hp !== observed.hp) {
        mon.sethp(observed.hp);
      }
      if (asId(mon.item) !== asId(observed.item)) {
        const knownItem = original.dex.items.get(observed.item || "");
        if (observed.item && !knownItem.exists) {
          return why("unsupported-exact-own-item", `${ownPath}.item`);
        }
        if (mon.isActive) {
          // Native SetItem/End events must fire for active Pokemon.
          const changed = observed.item
            ? mon.setItem(knownItem) : mon.clearItem();
          if (!changed) return why("unsupported-exact-own-item");
        } else {
          // Pinned Pokemon.setItem() returns false for bench members. This
          // state belongs to OUR fully observed team; restore the exact
          // present inventory without triggering an active-only item event.
          mon.item = knownItem.id;
          mon.itemState = original.initEffectState({
            id: knownItem.id, target: mon,
          });
        }
        if (asId(mon.item) !== asId(observed.item)) {
          return why("unsupported-exact-own-item");
        }
      }
      if (asId(mon.ability) !== asId(observed.ability)) {
        // A public own ability is exact evidence, but native setAbility may
        // refuse restoration (notably on benched or previously Mega members).
        // Never allow a silently rejected transition to survive until the
        // generic whole-request equality gate.
        const restored = mon.setAbility(observed.ability || "");
        if (!restored || asId(mon.ability) !== asId(observed.ability)) {
          return why("unsupported-native-own-ability", `${ownPath}.ability`);
        }
      }
      // Do not bypass pinned status immunity. If the present state needs
      // historical suppression/change-of-ability evidence we cannot prove,
      // reject this candidate rather than synthesize an illegal native status.
      // The public own-team view uses "fnt" as a faint marker, not as a
      // native major status. mon.faint() above already establishes that fact.
      // Never feed "fnt" into setStatus(), including on a benched fainted mon.
      if (observed.status === "fnt" && observed.hp !== 0) {
        return why("unsupported-own-status", `${ownPath}.status`);
      }
      const ownStatus = observed.status === "fnt" ? "" : observed.status;
      if (ownStatus && mon.status !== ownStatus) {
        if (!mon.isActive || !mon.setStatus(ownStatus, mon)) {
          return why("unsupported-own-status", `${ownPath}.status`);
        }
      } else if (!ownStatus && mon.status) {
        mon.clearStatus();
      }
      // Own PP is fully known even after a Pokemon leaves the field.
      // Restore all selected team members, not only request.active entries.
      // Require an exact slot inventory; do not infer missing bench values.
      if (!Array.isArray(observed.move_pp) ||
          observed.move_pp.length !== mon.moveSlots.length) {
        return why("unsupported-exact-own-bench-pp");
      }
      const ppIds = new Set();
      for (const entry of observed.move_pp) {
        if (!entry || typeof entry.id !== "string" ||
            ppIds.has(entry.id)) return why("unsupported-exact-own-bench-pp");
        ppIds.add(entry.id);
        const slot = mon.moveSlots.find((move) => move.id === entry.id);
        if (!slot || !Number.isInteger(entry.pp) ||
            entry.pp < 0 || entry.pp > slot.maxpp ||
            entry.maxpp !== slot.maxpp) {
          return why("unsupported-exact-own-bench-pp");
        }
        slot.pp = entry.pp;
      }
      if (observed.active !== mon.isActive) return why("own-active-mismatch", `${ownPath}.active`);
      if (observed.boosts && mon.isActive) {
        if (Object.keys(observed.boosts).some((k) => !supportedBoosts.has(k))) {
          return why("unsupported-own-boost");
        }
        mon.clearBoosts();
        mon.setBoost(observed.boosts);
      }
    }
    const ownMoves = view.request.active || [];
    for (let slot = 0; slot < ownMoves.length; slot++) {
      const mon = own.active[slot];
      if (!mon || !Array.isArray(ownMoves[slot]?.moves)) {
        return why("unsupported-own-move-request");
      }
      for (const requestMove of ownMoves[slot].moves) {
        const moveSlot = mon.moveSlots.find((item) => item.id === requestMove.id);
        if (!moveSlot || !Number.isInteger(requestMove.pp) ||
            requestMove.pp < 0 || requestMove.pp > moveSlot.maxpp ||
            moveSlot.maxpp !== requestMove.maxpp) {
          return why("unsupported-own-pp");
        }
        // Native Pokemon has no PP setter; write to a *live native MoveSlot*,
        // then demand exact request and native serialization roundtrip.
        moveSlot.pp = requestMove.pp;
      }
    }

    // Opponent observations are public constraints. Exact HP is an unknown,
    // so branch over at most two compatible integers per active Pokemon.
    const hpSlots = [];
    for (let slot = 0; slot < view.opponent.active.length; slot++) {
      const observed = view.opponent.active[slot];
      if (!observed || !observed.base_species || typeof observed.fainted !== "boolean") {
        return why("unsupported-opponent-active", `$.opponent.active[${slot}]`);
      }
      const mon = find(foe, observed.base_species);
      if (!mon || !mon.isActive || asId(observed.species) !== asId(mon.species.name)) {
        return why("unsupported-opponent-active", `$.opponent.active[${slot}].species`);
      }
      if (observed.fainted) {
        // Pinned faintMessages() retains a fainted mon in side.active[slot]
        // when no replacement is available, but clears Pokemon.isActive.
        // Zero HP is then an exact PUBLIC fact, not a speculative HP roll.
        if (observed.hp_percent !== 0) {
          return why("contradictory-fainted-opponent-hp",
            `$.opponent.active[${slot}].hp_percent`);
        }
        mon.faint();
        hpSlots.push([0]);
      } else {
        if (!Number.isInteger(observed.hp_percent) ||
            observed.hp_percent < 1 || observed.hp_percent > 100) {
          return why("unsupported-living-opponent-hp",
            `$.opponent.active[${slot}].hp_percent`);
        }
        const hp = [];
        for (let n = 1; n <= mon.maxhp; n++) {
          if (championsPublicHpPercent({ hp: n, maxhp: mon.maxhp }) === observed.hp_percent) hp.push(n);
        }
        if (!hp.length) return why("no-compatible-opponent-hp");
        hpSlots.push([...new Set([hp[0], hp[hp.length - 1]])]);
        // A status incompatible with the proposed native ability is not
        // admitted through ignoreImmunities. Another prior may remain viable.
        if (observed.status && mon.status !== observed.status) {
          if (!mon.setStatus(observed.status, mon)) {
            return why("unsupported-opponent-status");
          }
        } else if (!observed.status && mon.status) {
          mon.clearStatus();
        }
        if (!observed.boosts ||
            Object.keys(observed.boosts).some((k) => !supportedBoosts.has(k))) {
          return why("unsupported-opponent-boost");
        }
        mon.clearBoosts();
        mon.setBoost(observed.boosts);
      }
    }
    for (const seen of view.opponent.revealed) {
      const mon = find(foe, seen.species);
      if (!mon) continue; // unknown team-preview member was not brought
      if (seen.fainted && mon.hp > 0) mon.faint();
      if (!seen.fainted && mon.hp === 0) return why("contradictory-faint-state");
    }

    original.faintMessages(false, false, false);
    // Pinned Battle.checkFainted() is a separate native step after faint
    // resolution: it assigns the canonical "fnt" status and switchFlag.
    // Without it the public view's fainted slot has status "fnt" while
    // this synthetic current turn has status null, failing exact admission.
    original.checkFainted();
    // The natural pinned turn-loop clears an unfulfillable forced switch:
    // with no remaining reserve the fainted member stays in side.active.
    // With a reserve available, this is a forced-switch request, NOT a move
    // phase; do not misrepresent it as a valid current move state.
    for (const side of [original.p1, original.p2]) {
      if (!side.active.some((mon) => mon && mon.fainted)) continue;
      if (original.canSwitch(side)) {
        return why("fainted-slot-requires-forced-switch");
      }
      for (const mon of side.active) {
        if (mon && mon.fainted) mon.switchFlag = false;
      }
    }
    // Derive persistent effects through native pinned setters. Their remaining
    // durations are unknown hypotheses, NEVER historical facts.
    const field = view.field || {};
    const source = own.active.find((mon) => mon && mon.hp) ||
      foe.active.find((mon) => mon && mon.hp);
    if (!source) return why("no-current-effect-source");
    if (field.weather !== original.field.weather) {
      if (!field.weather) original.field.clearWeather();
      else if (!original.field.setWeather(field.weather, source)) {
        return why("unsupported-native-weather");
      }
    }
    if (field.terrain !== original.field.terrain) {
      if (!field.terrain) original.field.clearTerrain();
      else if (!original.field.setTerrain(field.terrain, source)) {
        return why("unsupported-native-terrain");
      }
    }
    if (!Array.isArray(field.pseudo_weather)) return why("unsupported-pseudo-weather");
    for (const effect of Object.keys(original.field.pseudoWeather)) {
      if (!field.pseudo_weather.includes(effect)) original.field.removePseudoWeather(effect);
    }
    for (const effect of field.pseudo_weather) {
      if (!original.field.pseudoWeather[effect] &&
          !original.field.addPseudoWeather(effect, source)) {
        return why("unsupported-native-pseudo-weather");
      }
    }
    for (const [side, effects] of [
      [own, view.player.side_conditions], [foe, view.opponent.side_conditions],
    ]) {
      if (!Array.isArray(effects)) return why("unsupported-side-conditions");
      for (const effect of Object.keys(side.sideConditions)) {
        if (!effects.includes(effect)) side.removeSideCondition(effect);
      }
      for (const effect of effects) {
        if (!side.sideConditions[effect] && !side.addSideCondition(effect, source)) {
          return why("unsupported-native-side-effect");
        }
      }
    }

    if (terrainPlan != null) {
      // Restore after all native switching, which can overwrite terrain.
      // An extender lost since activation needs a separate public domain.
      if (terrainSourceItem === 'terrainextender' && terrainSource.item !== terrainSourceItem) {
        return why('unsupported-terrain-extension-history');
      }
      original.field.clearTerrain();
      if (!original.field.setTerrain(terrainPlan.opening_terrain, terrainSource)) {
        return why('unsupported-native-terrain-start');
      }
      // Native field lifecycle; empty targets exclude Pokemon residuals.
      for (let age = 0; age < terrainPlan.residual_turns; age++) {
        original.fieldEvent('Residual', []);
      }
      if (original.field.terrain !== terrainPlan.opening_terrain) {
        return why('opening-terrain-expired');
      }
    }

    // Unburden's speed multiplier is a VOLATILE, not inferred from the
    // absence of an item alone. The fresh opening may consume Psychic Seed
    // on the initial switch-in and acquire Unburden, whereas the real own
    // Pokemon may have switched out (which clears that volatile) and then
    // returned without an item. Both cases are mechanically possible from
    // present public facts; our OWN cached speed disambiguates this one case.
    // Never change a set/stat or write a made-up speed directly. Use the
    // pinned volatile removal and require the derived speed to match exactly.
    for (let slot = 0; slot < view.player.active_details.length; slot++) {
      const observed = view.player.active_details[slot];
      if (!observed || !Number.isInteger(observed.speed)) continue;
      const mon = own.active[slot];
      if (!mon || !mon.isActive ||
          asId(mon.species.name) !== asId(observed.species) ||
          asId(mon.ability) !== "unburden" ||
          mon.item || !mon.volatiles["unburden"]) continue;
      // getActionSpeed() is signed under active Trick Room. A negative
      // *cached* Speed may also survive its expiry. Compare current native
      // mechanics in the current field, not a sign from an expired cache.
      const targetActionSpeed = original.field.pseudoWeather["trickroom"]
        ? observed.speed : Math.abs(observed.speed);
      const beforeRemoval = mon.getActionSpeed();
      if (beforeRemoval === targetActionSpeed) continue;
      mon.removeVolatile("unburden");
      if (mon.getActionSpeed() !== targetActionSpeed) {
        return why("own-unburden-speed-unresolved",
          `$.player.active_details[${slot}].speed`,
          speedDiagnostic(mon, observed, slot,
            "after-native-unburden-removal", beforeRemoval));
      }
    }

    original.turn = view.turn;
    original.updateSpeed();
    // Native Trick Room reverses cached Speed's sign during turn ordering.
    // Upon expiry pinned Showdown can retain the negative cache even though
    // subsequent action Speed in the current field is positive. Reproduce
    // that cache with native field transitions, not by assigning Pokemon.speed.
    if (!original.field.pseudoWeather["trickroom"] &&
        view.player.active_details.some((mon) => mon && mon.speed < 0)) {
      const source = own.active.find((mon) => mon && mon.hp > 0);
      if (!source || !original.field.addPseudoWeather("trickroom", source)) {
        return why("expired-trick-room-cache-unavailable");
      }
      original.updateSpeed();
      original.field.removePseudoWeather("trickroom");
      // Do NOT updateSpeed after native expiry.
    }
    original.makeRequest("move");
    const choices = original.p2.activeRequest;
    if (exact(choices) !== ownRequested) {
      return why("exact-own-request-mismatch",
        firstMismatchPath(choices, view.request, "$.request"));
    }

    const desiredOwn = view.player;
    const ownProjection = playerView(original, "p2", {
      p1: view.opponent.preview_species,
      p2: view.player.team.map((mon) => mon.species),
    });
    if (exact(ownProjection.player) !== exact(desiredOwn)) {
      const path = firstMismatchPath(ownProjection.player, desiredOwn, "$.player");
      const speedMatch = /^\$\.player\.(active_details|team)\[(\d+)\]\.speed$/.exec(path || "");
      let diagnostic = null;
      if (speedMatch) {
        const slot = Number(speedMatch[2]);
        const isActive = speedMatch[1] === "active_details";
        const mon = (isActive ? own.active : own.pokemon)[slot];
        const observed = (isActive ? desiredOwn.active_details : desiredOwn.team)[slot];
        if (mon && observed && Number.isInteger(observed.speed)) {
          diagnostic = speedDiagnostic(mon, observed, slot,
            "exact-own-projection");
        }
      }
      return why("current-public-mechanics-mismatch", path, diagnostic);
    }
    if (exact(ownProjection.field) !== exact(field)) {
      return why("current-public-mechanics-mismatch",
        firstMismatchPath(ownProjection.field, field, "$.field"));
    }
    if (exact(ownProjection.opponent.side_conditions) !==
        exact(view.opponent.side_conditions)) {
      return why("current-public-mechanics-mismatch",
        firstMismatchPath(ownProjection.opponent.side_conditions,
          view.opponent.side_conditions, "$.opponent.side_conditions"));
    }
    const foeMembers = foe.active.map((mon) => mon && ({
      species: mon.species.name,
      // Public base_species denotes the original team/preview member, not
      // Pokedex baseSpecies. In particular Indeedee-F's Dex base is
      // Indeedee, but its public roster identity remains Indeedee-F.
      base_species: mon.set.species,
      status: mon.status || null,
      boosts: { ...mon.boosts },
    }));
    for (let slot = 0; slot < foeMembers.length; slot++) {
      const expected = view.opponent.active[slot];
      const got = foeMembers[slot];
      const path = `$.opponent.active[${slot}]`;
      if (!expected || !got) {
        return why("current-opponent-mechanics-mismatch", path);
      }
      // These checks remain exact: the path is diagnostic metadata, never
      // an instruction to overwrite a mismatched current native mechanic.
      if (asId(expected.species) !== asId(got.species)) {
        return why("current-opponent-mechanics-mismatch", `${path}.species`);
      }
      if (asId(expected.base_species) !== asId(got.base_species)) {
        return why("current-opponent-mechanics-mismatch", `${path}.base_species`);
      }
      if (expected.status !== got.status) {
        return why("current-opponent-mechanics-mismatch", `${path}.status`);
      }
      if (exact(expected.boosts) !== exact(got.boosts)) {
        return why("current-opponent-mechanics-mismatch",
          firstMismatchPath(got.boosts, expected.boosts, `${path}.boosts`));
      }
    }
    // Preserve two HP endpoints independently, *without* claiming the
    // interval's interior has a historical RNG witness.
    const seen = new Set();
    for (let index = 0; index < limit; index++) {
      const hpPair = hpSlots.map((values, slot) => values[(index >> slot) % values.length]);
      const key = hpPair.join(",");
      if (seen.has(key)) continue;
      seen.add(key);
      const battle = Battle.fromJSON(JSON.stringify(original.toJSON()));
      battle.restart(() => {});
      try {
        for (let slot = 0; slot < hpPair.length; slot++) {
          if (battle.p1.active[slot].hp !== hpPair[slot]) {
            battle.p1.active[slot].sethp(hpPair[slot]);
          }
        }
        const projected = playerView(battle, "p2", {
          p1: view.opponent.preview_species,
          p2: view.player.team.map((mon) => mon.species),
        });
        if (exact(projected.request) !== ownRequested ||
            exact(projected.player) !== exact(desiredOwn) ||
            exact(projected.field) !== exact(field)) continue;
        if (hpPair.some((hp, slot) =>
          championsPublicHpPercent({ hp, maxhp: battle.p1.active[slot].maxhp }) !==
            view.opponent.active[slot].hp_percent
        )) continue;
        const state = battle.toJSON();
        const restored = Battle.fromJSON(JSON.stringify(state));
        restored.restart(() => {});
        try {
          if (exact(playerView(restored, "p2", {
            p1: view.opponent.preview_species,
            p2: view.player.team.map((mon) => mon.species),
          }).request) !== ownRequested) continue;
        } finally {
          restored.destroy();
        }
        candidates.push({ state, hp: hpPair });
      } finally {
        battle.destroy();
      }
    }
    return { outcomes: candidates, reason: candidates.length ? null : "no-native-public-match" };
  } finally {
    original.destroy();
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
  let previewLineage = null;

  if (request.p1_preview || request.p2_preview) {
    if (!request.p1_preview || !request.p2_preview) {
      battle.destroy();
      throw new Error("Both preview choices are required when either is provided");
    }

    const originalPokemon = {
      p1: [...battle.p1.pokemon],
      p2: [...battle.p2.pokemon],
    };
    battle.makeChoices(request.p1_preview, request.p2_preview);
    previewLineage = {
      p1: battle.p1.pokemon.map((pokemon) => originalPokemon.p1.indexOf(pokemon)),
      p2: battle.p2.pokemon.map((pokemon) => originalPokemon.p2.indexOf(pokemon)),
    };
    if (
      previewLineage.p1.some((index) => index < 0) ||
      previewLineage.p2.some((index) => index < 0)
    ) {
      battle.destroy();
      throw new Error("Could not derive preview member lineage");
    }
  }

  const response = {
    state: battle.toJSON(),
    summary: summarize(battle),
  };
  if (previewLineage !== null) response.preview_lineage = previewLineage;
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
  includeRngDrawCount = false,
  damageBucket = null,
  damageEndpoint = null,
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

  // Reachability may request proof that a transition consumed no simulator
  // randomness. Instrument the lowest-level PRNG draw so random(), randomChance(),
  // sample(), shuffle(), and direct PRNG users all flow through the same counter.
  // This is branch-local instrumentation on a restored hypothetical Battle only.
  let rngDrawCount = 0;
  if (includeRngDrawCount) {
    const rng = battle.prng.rng;
    const originalNext = rng.next.bind(rng);
    rng.next = () => {
      rngDrawCount++;
      return originalNext();
    };
  }

  // Endpoint-only what-if evaluation. All effects still run in pinned Showdown.
  if (damageEndpoint !== null) {
    if (!["min-normal", "max-crit"].includes(damageEndpoint) ||
        damageBucket !== null) {
      battle.destroy();
      throw new Error("invalid damage_endpoint");
    }
    const forcedCrit = damageEndpoint === "max-crit";
    const endpointBucket = forcedCrit ? DAMAGE_ROLL_BUCKETS - 1 : 0;
    const getDamage = battle.actions.getDamage.bind(battle.actions);
    battle.actions.getDamage = (source, target, move, suppressMessages) => {
      if (!move || typeof move !== "object" || !("basePower" in move)) {
        return getDamage(source, target, move, suppressMessages);
      }
      const original = move.willCrit;
      move.willCrit = forcedCrit;
      try {
        return getDamage(source, target, move, suppressMessages);
      } finally {
        move.willCrit = original;
      }
    };
    const randomizer = battle.randomizer.bind(battle);
    battle.randomizer = baseDamage => {
      const random = battle.random.bind(battle);
      battle.random = (from, to) => {
        random(from, to); // Consume the normal pinned RNG draw.
        if (from !== DAMAGE_ROLL_BUCKETS || to !== undefined) {
          throw new Error("unexpected damage randomizer domain");
        }
        return endpointBucket;
      };
      try {
        return randomizer(baseDamage);
      } finally {
        battle.random = random;
      }
    };
  }

  // This is a positive-witness probe, not a full transition RNG enumeration.
  // Re-run exact pinned mechanics, forcing only the first Battle#randomizer
  // bucket while consuming its normal PRNG draw. All other randomness keeps its
  // sampled path. PR #139 separately verified the pinned random(16) domain.
  let damageRollCalls = 0;
  if (damageBucket !== null) {
    if (
      !Number.isInteger(damageBucket) ||
      damageBucket < 0 ||
      damageBucket >= DAMAGE_ROLL_BUCKETS
    ) {
      battle.destroy();
      throw new Error("damage_bucket must be a pinned Battle#randomizer bucket");
    }
    const originalRandomizer = battle.randomizer.bind(battle);
    const originalRandom = battle.random.bind(battle);
    battle.randomizer = (baseDamage) => {
      damageRollCalls++;
      if (damageRollCalls !== 1) return originalRandomizer(baseDamage);
      let bucketDraws = 0;
      battle.random = (from, to) => {
        const sampled = originalRandom(from, to);
        if (from !== DAMAGE_ROLL_BUCKETS || to !== undefined) {
          throw new Error("Pinned Battle#randomizer changed its random-call domain");
        }
        bucketDraws++;
        if (bucketDraws !== 1) {
          throw new Error("Pinned Battle#randomizer used multiple random calls");
        }
        if (!Number.isInteger(sampled) || sampled < 0 ||
            sampled >= DAMAGE_ROLL_BUCKETS) {
          throw new Error("Pinned Battle#randomizer sampled invalid bucket");
        }
        return damageBucket;
      };
      try {
        const damage = originalRandomizer(baseDamage);
        if (bucketDraws !== 1) {
          throw new Error("Pinned Battle#randomizer consumed no random(16) call");
        }
        return damage;
      } finally {
        battle.random = originalRandom;
      }
    };
  }

  // Showdown mutates side.pokemon ordering during ordinary switches. Capture the
  // exact parent objects so every returned child state can report a permutation
  // from child party position back to its parent party position. Python composes
  // these permutations across turns into stable turn-one roster identity.
  const parentPokemon = {
    p1: [...battle.p1.pokemon],
    p2: [...battle.p2.pokemon],
  };

  const exactP1Choice = exactChoiceForShowdown(battle, "p1", p1Choice);
  const exactP2Choice = exactChoiceForShowdown(battle, "p2", p2Choice);
  battle.makeChoices(exactP1Choice, exactP2Choice);

  const memberLineage = {
    p1: battle.p1.pokemon.map((pokemon) => parentPokemon.p1.indexOf(pokemon)),
    p2: battle.p2.pokemon.map((pokemon) => parentPokemon.p2.indexOf(pokemon)),
  };
  if (
    memberLineage.p1.length !== parentPokemon.p1.length ||
    memberLineage.p2.length !== parentPokemon.p2.length ||
    memberLineage.p1.some((index) => index < 0) ||
    memberLineage.p2.some((index) => index < 0) ||
    new Set(memberLineage.p1).size !== memberLineage.p1.length ||
    new Set(memberLineage.p2).size !== memberLineage.p2.length
  ) {
    battle.destroy();
    throw new Error("Could not derive stable branch member lineage");
  }

  const response = {
    summary: summarize(battle),
  };
  if (includeState) {
    response.state = battle.toJSON();
    response.member_lineage = memberLineage;
  }
  if (viewSide !== null) {
    const effectivePreviews = previews || {
      p1: battle.p1.pokemon.map((mon) => mon.set.species),
      p2: battle.p2.pokemon.map((mon) => mon.set.species),
    };
    response.view = playerView(battle, viewSide, effectivePreviews);
  }
  if (includeRngDrawCount) {
    response.rng_draw_count = rngDrawCount;
  }
  if (damageEndpoint !== null) response.damage_endpoint = damageEndpoint;
  if (damageBucket !== null) {
    response.damage_roll_calls = damageRollCalls;
    response.damage_bucket = damageBucket;
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
    request.include_rng_draw_count === true,
  );
}


const FINITE_TRANSITION_DOMAIN = "showdown-finite-random-calls-v1";
const FINITE_CONTINUATION_SCHEMA = "showdown-finite-frontier-v2";
const FINITE_MAX_FRONTIER_PATHS = 10000;
const FINITE_MAX_CONTINUATION_BYTES = 4 * 1024 * 1024;

function stableJson(value) {
  if (Array.isArray(value)) {
    return "[" + value.map((item) => stableJson(item)).join(",") + "]";
  }
  if (value !== null && typeof value === "object") {
    const keys = Object.keys(value).sort();
    return "{" + keys.map(
      (key) => JSON.stringify(key) + ":" + stableJson(value[key]),
    ).join(",") + "}";
  }
  return JSON.stringify(value);
}

function normalizedPublicObservationForReachability(view) {
  const normalized = cloneJson(view);
  delete normalized.opponent_last_actions;
  const player = normalized.player;
  const opponent = normalized.opponent;
  const playerName = player && typeof player === "object" ? player.name : null;
  const opponentName = opponent && typeof opponent === "object" ? opponent.name : null;

  if (typeof normalized.winner === "string") {
    if (normalized.winner === playerName) normalized.winner = "player";
    else if (normalized.winner === opponentName) normalized.winner = "opponent";
  }
  if (player && typeof player === "object") delete player.name;
  if (opponent && typeof opponent === "object") delete opponent.name;
  if (
    normalized.request &&
    typeof normalized.request === "object" &&
    normalized.request.side &&
    typeof normalized.request.side === "object"
  ) {
    delete normalized.request.side.name;
  }
  return normalized;
}

class NeedFiniteRandomDecision extends Error {
  constructor(kind, options, metadata) {
    super("finite stochastic transition requires another random decision");
    this.kind = kind;
    this.options = options;
    this.metadata = metadata;
  }
}

class UnsupportedFiniteRandomDecision extends Error {}

function finiteRandomOptions(from, to) {
  if (from === undefined) {
    throw new UnsupportedFiniteRandomDecision(
      "PRNG.random() without a finite integer range is unsupported",
    );
  }
  const lower = to === undefined ? 0 : Math.floor(from);
  const upper = to === undefined ? Math.floor(from) : Math.floor(to);
  if (
    !Number.isSafeInteger(lower) ||
    !Number.isSafeInteger(upper) ||
    upper <= lower
  ) {
    throw new UnsupportedFiniteRandomDecision(
      "PRNG.random received a non-finite or empty integer domain",
    );
  }
  const size = upper - lower;
  if (size > 256) {
    throw new UnsupportedFiniteRandomDecision(
      `PRNG.random domain of ${size} outcomes exceeds finite enumeration limit`,
    );
  }
  return Array.from({ length: size }, (_, index) => lower + index);
}

function resolveFiniteTransitionPath(
  state,
  p1Choice,
  p2Choice,
  viewSide,
  previews,
  path,
) {
  const battle = Battle.fromJSON(JSON.stringify(state));
  battle.restart(() => {});
  const parentPokemon = {
    p1: [...battle.p1.pokemon],
    p2: [...battle.p2.pokemon],
  };
  let pathIndex = 0;

  function choose(kind, options, metadata) {
    if (pathIndex >= path.length) {
      throw new NeedFiniteRandomDecision(kind, options, metadata);
    }
    const supplied = path[pathIndex++];
    if (
      !supplied ||
      supplied.kind !== kind ||
      !options.some((value) => Object.is(value, supplied.value))
    ) {
      throw new Error("finite stochastic decision path no longer matches runtime");
    }
    return supplied.value;
  }

  const prng = battle.prng;
  const lowLevel = prng.rng;
  lowLevel.next = () => {
    throw new UnsupportedFiniteRandomDecision(
      "pinned runtime consumed randomness outside PRNG.random/randomChance",
    );
  };
  prng.random = (from, to) => {
    const options = finiteRandomOptions(from, to);
    return choose(
      "random",
      options,
      { from: from ?? null, to: to ?? null },
    );
  };
  prng.randomChance = (numerator, denominator) => {
    if (
      !Number.isSafeInteger(numerator) ||
      !Number.isSafeInteger(denominator) ||
      numerator < 0 ||
      denominator <= 0
    ) {
      throw new UnsupportedFiniteRandomDecision(
        "PRNG.randomChance received an invalid finite domain",
      );
    }
    const options = [];
    if (numerator > 0) options.push(true);
    if (numerator < denominator) options.push(false);
    if (!options.length) options.push(true);
    return choose(
      "chance",
      options,
      { numerator, denominator },
    );
  };

  try {
    const exactP1Choice = exactChoiceForShowdown(battle, "p1", p1Choice);
    const exactP2Choice = exactChoiceForShowdown(battle, "p2", p2Choice);
    battle.makeChoices(exactP1Choice, exactP2Choice);
    if (pathIndex !== path.length) {
      throw new Error("finite stochastic decision path contains unused decisions");
    }

    const memberLineage = {
      p1: battle.p1.pokemon.map((pokemon) => parentPokemon.p1.indexOf(pokemon)),
      p2: battle.p2.pokemon.map((pokemon) => parentPokemon.p2.indexOf(pokemon)),
    };
    if (
      memberLineage.p1.some((index) => index < 0) ||
      memberLineage.p2.some((index) => index < 0) ||
      new Set(memberLineage.p1).size !== memberLineage.p1.length ||
      new Set(memberLineage.p2).size !== memberLineage.p2.length
    ) {
      throw new Error("Could not derive finite-transition member lineage");
    }
    const effectivePreviews = previews || {
      p1: battle.p1.pokemon.map((mon) => mon.set.species),
      p2: battle.p2.pokemon.map((mon) => mon.set.species),
    };
    return {
      complete: true,
      state: battle.toJSON(),
      member_lineage: memberLineage,
      view: playerView(battle, viewSide, effectivePreviews),
    };
  } catch (error) {
    if (error instanceof NeedFiniteRandomDecision) {
      return {
        complete: false,
        decision: {
          kind: error.kind,
          options: error.options,
          metadata: error.metadata,
        },
      };
    }
    if (error instanceof UnsupportedFiniteRandomDecision) {
      return {
        unsupported: true,
        reason: error.message,
      };
    }
    throw error;
  } finally {
    battle.destroy();
  }
}

const FINITE_WITNESS_SEED_WINDOW_ATTEMPTS = 4096;

function finiteWitnessSeed(path, attempt) {
  const digest = createHash("sha256")
    .update(stableJson(path))
    .update("|")
    .update(String(attempt))
    .digest("hex");
  return `sodium,${digest}`;
}

function finitePathMatchesSeed(path, seed) {
  const prng = new PRNG(seed);
  for (const decision of path) {
    if (!decision || typeof decision !== "object") return false;
    if (decision.kind === "random") {
      const metadata = decision.metadata || {};
      const from = metadata.from;
      const to = metadata.to;
      if (!Number.isSafeInteger(from)) return false;
      const actual = (
        to === null
          ? prng.random(from)
          : prng.random(from, to)
      );
      if (!Object.is(actual, decision.value)) return false;
      continue;
    }
    if (decision.kind === "chance") {
      const metadata = decision.metadata || {};
      const actual = prng.randomChance(
        metadata.numerator,
        metadata.denominator,
      );
      if (!Object.is(actual, decision.value)) return false;
      continue;
    }
    return false;
  }
  return true;
}

function concreteFiniteWitnessWindow(
  state,
  p1Choice,
  p2Choice,
  viewSide,
  previews,
  path,
  wanted,
  startAttempt,
  attemptCount,
) {
  if (
    !Number.isSafeInteger(startAttempt) ||
    startAttempt < 0 ||
    !Number.isSafeInteger(attemptCount) ||
    attemptCount < 1 ||
    attemptCount > FINITE_WITNESS_SEED_WINDOW_ATTEMPTS ||
    startAttempt > (Number.MAX_SAFE_INTEGER - attemptCount)
  ) {
    throw new Error("finite witness seed cursor is outside the safe integer range");
  }
  const endAttempt = startAttempt + attemptCount;
  for (let attempt = startAttempt; attempt < endAttempt; attempt++) {
    const seed = finiteWitnessSeed(path, attempt);
    if (!finitePathMatchesSeed(path, seed)) continue;

    const resolved = resolveBranch(
      state,
      p1Choice,
      p2Choice,
      true,
      seed,
      viewSide,
      previews,
      false,
    );
    const observed = stableJson(
      normalizedPublicObservationForReachability(resolved.view),
    );
    if (observed !== wanted) {
      continue;
    }
    return {
      witness: {
        state: resolved.state,
        view: resolved.view,
        member_lineage: resolved.member_lineage,
        rng_seed: seed,
        random_path: path,
      },
      next_attempt: endAttempt,
    };
  }
  return {
    witness: null,
    next_attempt: endAttempt,
  };
}

function finiteContinuationContext(
  request,
  wanted,
  witnessSeedWindowAttempts,
) {
  return createHash("sha256")
    .update(stableJson({
      domain: FINITE_TRANSITION_DOMAIN,
      state: request.state,
      p1_choice: request.p1_choice,
      p2_choice: request.p2_choice,
      view_side: request.view_side,
      previews: request.previews ?? null,
      wanted,
      witness_seed_window_attempts: witnessSeedWindowAttempts,
    }))
    .digest("hex");
}

function finiteContinuationEntryCount(pending, materializations) {
  return pending.length + materializations.length;
}

function encodeFiniteContinuation(
  context,
  pending,
  materializations,
) {
  if (!Array.isArray(pending) || !Array.isArray(materializations)) return null;
  if (finiteContinuationEntryCount(pending, materializations) === 0) return null;
  if (
    finiteContinuationEntryCount(pending, materializations) >
    FINITE_MAX_FRONTIER_PATHS
  ) {
    return null;
  }
  const token = JSON.stringify({
    schema: FINITE_CONTINUATION_SCHEMA,
    context,
    pending,
    materializations,
  });
  if (Buffer.byteLength(token, "utf8") > FINITE_MAX_CONTINUATION_BYTES) {
    return null;
  }
  return token;
}

function decodeFiniteContinuation(token, expectedContext) {
  if (typeof token !== "string" || !token.length) {
    throw new Error("finite continuation must be a non-empty string");
  }
  if (Buffer.byteLength(token, "utf8") > FINITE_MAX_CONTINUATION_BYTES) {
    throw new Error("finite continuation exceeds the bounded payload size");
  }
  let decoded;
  try {
    decoded = JSON.parse(token);
  } catch {
    throw new Error("finite continuation is not valid JSON");
  }
  if (
    !decoded ||
    typeof decoded !== "object" ||
    decoded.schema !== FINITE_CONTINUATION_SCHEMA ||
    decoded.context !== expectedContext ||
    !Array.isArray(decoded.pending) ||
    !Array.isArray(decoded.materializations) ||
    finiteContinuationEntryCount(
      decoded.pending,
      decoded.materializations,
    ) === 0 ||
    finiteContinuationEntryCount(
      decoded.pending,
      decoded.materializations,
    ) > FINITE_MAX_FRONTIER_PATHS
  ) {
    throw new Error("finite continuation does not match this transition context");
  }
  for (const path of decoded.pending) {
    if (!Array.isArray(path)) {
      throw new Error("finite continuation contains an invalid decision path");
    }
  }
  for (const materialization of decoded.materializations) {
    if (
      !materialization ||
      typeof materialization !== "object" ||
      !Array.isArray(materialization.path) ||
      !Number.isSafeInteger(materialization.next_attempt) ||
      materialization.next_attempt < 0 ||
      materialization.next_attempt > (
        Number.MAX_SAFE_INTEGER - FINITE_WITNESS_SEED_WINDOW_ATTEMPTS
      )
    ) {
      throw new Error(
        "finite continuation contains an invalid seed materialization cursor",
      );
    }
  }
  return {
    pending: cloneJson(decoded.pending),
    materializations: cloneJson(decoded.materializations),
  };
}

function finiteUnresolvedResponse({
  leavesExamined,
  decisionNodes,
  maxDepth,
  reason,
  context,
  pending,
  materializations,
  frontierExhausted = false,
}) {
  const continuation = encodeFiniteContinuation(
    context,
    pending,
    materializations,
  );
  return {
    domain: FINITE_TRANSITION_DOMAIN,
    exhaustive: false,
    witnessed: false,
    leaves_examined: leavesExamined,
    decision_nodes: decisionNodes,
    max_depth: maxDepth,
    reason,
    continuation,
    frontier_exhausted: frontierExhausted && continuation === null,
  };
}

function enumerateFiniteTransitionReachability(request) {
  if (!request.state) {
    throw new Error("finite transition reachability requires a serialized state");
  }
  if (request.view_side !== "p1" && request.view_side !== "p2") {
    throw new Error("finite transition reachability requires view_side p1 or p2");
  }
  if (
    typeof request.p1_choice !== "string" ||
    typeof request.p2_choice !== "string"
  ) {
    throw new Error("finite transition reachability requires exact action strings");
  }
  if (
    !request.expected_public_view ||
    typeof request.expected_public_view !== "object"
  ) {
    throw new Error("finite transition reachability requires an expected public view");
  }
  const maxLeaves = request.max_leaves ?? 4096;
  if (
    !Number.isSafeInteger(maxLeaves) ||
    maxLeaves < 1 ||
    maxLeaves > 10000
  ) {
    throw new Error("finite transition max_leaves must be 1-10000");
  }

  const witnessSeedWindowAttempts = (
    request.witness_seed_window_attempts ??
    FINITE_WITNESS_SEED_WINDOW_ATTEMPTS
  );
  if (
    !Number.isSafeInteger(witnessSeedWindowAttempts) ||
    witnessSeedWindowAttempts < 1 ||
    witnessSeedWindowAttempts > FINITE_WITNESS_SEED_WINDOW_ATTEMPTS
  ) {
    throw new Error(
      "finite witness seed window attempts must be an integer from 1 through 4096",
    );
  }

  const wanted = stableJson(
    normalizedPublicObservationForReachability(request.expected_public_view),
  );
  const continuationContext = finiteContinuationContext(
    request,
    wanted,
    witnessSeedWindowAttempts,
  );
  const resumed = request.continuation !== undefined && request.continuation !== null;
  const decoded = resumed
    ? decodeFiniteContinuation(request.continuation, continuationContext)
    : {
        pending: [[]],
        materializations: [],
      };
  const pending = decoded.pending;
  const materializations = decoded.materializations;
  let leavesExamined = 0;
  let decisionNodes = 0;
  let maxDepth = 0;
  let seedWindowAvailable = true;

  if (materializations.length > 0) {
    const materialization = materializations.shift();
    const attempt = concreteFiniteWitnessWindow(
      request.state,
      request.p1_choice,
      request.p2_choice,
      request.view_side,
      request.previews ?? null,
      materialization.path,
      wanted,
      materialization.next_attempt,
      witnessSeedWindowAttempts,
    );
    if (attempt.witness !== null) {
      return {
        domain: FINITE_TRANSITION_DOMAIN,
        exhaustive: false,
        witnessed: true,
        leaves_examined: leavesExamined,
        decision_nodes: decisionNodes,
        max_depth: maxDepth,
        witness: attempt.witness,
        continuation: null,
        frontier_exhausted: false,
      };
    }
    materializations.push({
      path: materialization.path,
      next_attempt: attempt.next_attempt,
    });
    seedWindowAvailable = false;
  }

  while (pending.length) {
    const path = pending.pop();
    const result = resolveFiniteTransitionPath(
      request.state,
      request.p1_choice,
      request.p2_choice,
      request.view_side,
      request.previews ?? null,
      path,
    );
    maxDepth = Math.max(maxDepth, path.length);

    if (result.unsupported) {
      return finiteUnresolvedResponse({
        leavesExamined,
        decisionNodes,
        maxDepth,
        reason: result.reason,
        context: continuationContext,
        pending,
        materializations,
        frontierExhausted: (
          pending.length === 0 &&
          materializations.length === 0
        ),
      });
    }

    if (!result.complete) {
      decisionNodes++;
      const decision = result.decision;
      for (let index = decision.options.length - 1; index >= 0; index--) {
        pending.push([
          ...path,
          {
            kind: decision.kind,
            value: decision.options[index],
            metadata: decision.metadata,
          },
        ]);
      }
      if (
        finiteContinuationEntryCount(pending, materializations) >
          FINITE_MAX_FRONTIER_PATHS ||
        pending.length + leavesExamined > maxLeaves
      ) {
        const response = finiteUnresolvedResponse({
          leavesExamined,
          decisionNodes,
          maxDepth,
          reason: "finite stochastic branch budget exhausted",
          context: continuationContext,
          pending,
          materializations,
        });
        if (response.continuation === null) {
          response.reason = (
            "finite stochastic frontier exceeded bounded continuation capacity"
          );
          response.frontier_exhausted = true;
        }
        return response;
      }
      continue;
    }

    leavesExamined++;
    const observed = stableJson(
      normalizedPublicObservationForReachability(result.view),
    );
    if (observed === wanted) {
      let nextAttempt = 0;
      if (seedWindowAvailable) {
        const attempt = concreteFiniteWitnessWindow(
          request.state,
          request.p1_choice,
          request.p2_choice,
          request.view_side,
          request.previews ?? null,
          path,
          wanted,
          0,
          witnessSeedWindowAttempts,
        );
        if (attempt.witness !== null) {
          return {
            domain: FINITE_TRANSITION_DOMAIN,
            exhaustive: false,
            witnessed: true,
            leaves_examined: leavesExamined,
            decision_nodes: decisionNodes,
            max_depth: maxDepth,
            witness: attempt.witness,
            continuation: null,
            frontier_exhausted: false,
          };
        }
        nextAttempt = attempt.next_attempt;
        seedWindowAvailable = false;
      }
      materializations.push({
        path,
        next_attempt: nextAttempt,
      });
      if (
        finiteContinuationEntryCount(pending, materializations) >
        FINITE_MAX_FRONTIER_PATHS
      ) {
        return {
          domain: FINITE_TRANSITION_DOMAIN,
          exhaustive: false,
          witnessed: false,
          leaves_examined: leavesExamined,
          decision_nodes: decisionNodes,
          max_depth: maxDepth,
          reason: (
            "finite stochastic frontier exceeded bounded continuation capacity"
          ),
          continuation: null,
          frontier_exhausted: true,
        };
      }
    }
    if (leavesExamined >= maxLeaves && pending.length) {
      return finiteUnresolvedResponse({
        leavesExamined,
        decisionNodes,
        maxDepth,
        reason: "finite stochastic leaf budget exhausted",
        context: continuationContext,
        pending,
        materializations,
      });
    }
  }

  if (materializations.length > 0) {
    const response = finiteUnresolvedResponse({
      leavesExamined,
      decisionNodes,
      maxDepth,
      reason: (
        "finite outcome tree matched public evidence; concrete Showdown " +
        "seed materialization remains pending"
      ),
      context: continuationContext,
      pending,
      materializations,
    });
    if (response.continuation === null) {
      response.reason = (
        "finite seed materialization exceeded bounded continuation capacity"
      );
      response.frontier_exhausted = true;
    }
    return response;
  }

  if (resumed) {
    return {
      domain: FINITE_TRANSITION_DOMAIN,
      exhaustive: false,
      witnessed: false,
      leaves_examined: leavesExamined,
      decision_nodes: decisionNodes,
      max_depth: maxDepth,
      reason: (
        "resumed finite witness frontier exhausted without a concrete witness; " +
        "resumed coverage is positive-only"
      ),
      continuation: null,
      frontier_exhausted: true,
    };
  }

  return {
    domain: FINITE_TRANSITION_DOMAIN,
    exhaustive: true,
    witnessed: false,
    leaves_examined: leavesExamined,
    decision_nodes: decisionNodes,
    max_depth: maxDepth,
    reason: null,
    continuation: null,
    frontier_exhausted: false,
  };
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
            branch.include_rng_draw_count === true,
            branch.damage_bucket ?? null,
            branch.damage_endpoint ?? null,
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


const DAMAGE_ROLL_DOMAIN = "showdown-battle-randomizer-v1";
const DAMAGE_ROLL_BUCKETS = 16;
const DAMAGE_ROLL_BUCKET_WIDTH = 2 ** 28;
const MAX_EXACT_DAMAGE_RANDOMIZER_INPUT = Math.floor(
  Number.MAX_SAFE_INTEGER / 100,
);

function enumerateDamageRolls(request) {
  if (!request.state) {
    throw new Error("enumerate_damage_rolls requires a serialized battle state");
  }
  if (
    !Number.isSafeInteger(request.base_damage) ||
    request.base_damage < 1 ||
    request.base_damage > MAX_EXACT_DAMAGE_RANDOMIZER_INPUT
  ) {
    throw new Error(
      "base_damage exceeds exact Battle#randomizer integer precision",
    );
  }

  const battle = Battle.fromJSON(JSON.stringify(request.state));
  battle.restart(() => {});

  const rng = battle.prng.rng;
  const originalNext = rng.next.bind(rng);
  const originalRandom = battle.random.bind(battle);
  const outcomes = [];

  try {
    for (let bucket = 0; bucket < DAMAGE_ROLL_BUCKETS; bucket++) {
      let rngDrawCount = 0;
      const randomCalls = [];
      rng.next = () => {
        rngDrawCount++;
        if (rngDrawCount > 1) {
          throw new Error(
            "Battle#randomizer consumed more than one low-level PRNG draw",
          );
        }
        return bucket * DAMAGE_ROLL_BUCKET_WIDTH;
      };
      battle.random = (from, to) => {
        const result = originalRandom(from, to);
        randomCalls.push([from ?? null, to ?? null, result]);
        return result;
      };

      const damage = battle.randomizer(request.base_damage);
      if (
        randomCalls.length !== 1 ||
        randomCalls[0][0] !== DAMAGE_ROLL_BUCKETS ||
        randomCalls[0][1] !== null
      ) {
        throw new Error(
          "Pinned Battle#randomizer no longer uses exactly one random(16) call",
        );
      }
      if (randomCalls[0][2] !== bucket) {
        throw new Error(
          "Injected PRNG representative did not map to the intended random(16) bucket",
        );
      }
      if (rngDrawCount !== 1) {
        throw new Error(
          "Pinned Battle#randomizer did not consume exactly one PRNG draw",
        );
      }
      if (!Number.isSafeInteger(damage) || damage < 0) {
        throw new Error("Pinned Battle#randomizer returned invalid damage");
      }
      outcomes.push({
        bucket,
        damage,
        rng_draw_count: rngDrawCount,
      });
    }
  } finally {
    rng.next = originalNext;
    battle.random = originalRandom;
    battle.destroy();
  }

  return {
    domain: DAMAGE_ROLL_DOMAIN,
    source: "Battle#randomizer",
    base_damage: request.base_damage,
    domain_size: DAMAGE_ROLL_BUCKETS,
    exhaustive: true,
    outcomes,
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
    const p1Choice = exactChoiceForShowdown(battle, "p1", request.p1_choice);
    const p2Choice = exactChoiceForShowdown(battle, "p2", request.p2_choice);
    battle.makeChoices(p1Choice, p2Choice);
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
    case "validate_team":
      return validateTeamText(request);
    case "move_metadata":
      return moveMetadata(request);
    case "create":
      return createBattle(request);
    case "branch":
      return branchBattle(request);
    case "branch_many":
      return branchMany(request);
    case "enumerate_damage_rolls":
      return enumerateDamageRolls(request);
    case "enumerate_finite_transition":
      return enumerateFiniteTransitionReachability(request);
    case "legal_choices":
      return legalChoices(request);
    case "validate_choices":
      return validateRequestedChoices(request);
    case "materialize_recovery_stat_proposals":
      return materializeRecoveryStatProposals(request);
    case "materialize_recovery_opening_stat_proposals":
      return materializeRecoveryOpeningStatProposals(request);
    case "validate_recovery_stat_candidate":
      return validateRecoveryStatCandidate(request);
    case "validate_recovery_opening_authority":
      return validateRecoveryOpeningAuthority(request);
    case "validate_recovery_opening_stat_candidate":
      return validateRecoveryOpeningStatCandidate(request);
    case "materialize_current_hp_hypotheses":
      return materializeCurrentHpHypotheses(request);
    case "materialize_present_hypotheses":
      return materializePresentHypotheses(request);
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
