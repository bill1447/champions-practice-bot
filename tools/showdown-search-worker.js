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

    if (["-damage", "-heal"].includes(event)) {
      const condition = publicCondition(parts[3]);
      applyCondition(observation, condition);
      slotConditions.set(slot, condition);
    } else if (event === "-status") {
      observation.status = toId(parts[3]);
    } else if (event === "-curestatus") {
      observation.status = null;
    } else if (event === "move") {
      observation.moves.add(toId(parts[3]));
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
      team: own.pokemon.map(ownPokemon),
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

function moveTargetLocations(battle) {
  const locations = [];
  for (let slot = 1; slot <= battle.activePerHalf; slot++) {
    locations.push(slot, -slot);
  }
  return locations;
}

function availableSwitches(request) {
  return request.side.pokemon
    .map((pokemon, index) => ({ pokemon, slot: index + 1 }))
    .filter(({ pokemon }) => !pokemon.active && !isFainted(pokemon))
    .map(({ slot }) => `switch ${slot}`);
}

function moveSlotCandidates(battle, request, slot) {
  const active = request.active[slot];
  const pokemon = request.side.pokemon[slot];
  if (!active || isFainted(pokemon) || pokemon.commanding) return ["pass"];

  const choices = [];
  for (const move of active.moves) {
    if (move.disabled) continue;
    const targets = battle.actions.targetTypeChoices(move.target) ?
      moveTargetLocations(battle) : [0];
    const events = [""];
    if (active.canMegaEvo) events.push("mega");
    if (active.canMegaEvoX) events.push("megax");
    if (active.canMegaEvoY) events.push("megay");
    if (active.canUltraBurst) events.push("ultra");

    for (const target of targets) {
      for (const event of events) {
        const parts = [`move ${move.id}`];
        if (target) parts.push(String(target));
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
  return request.forceSwitch.map((mustSwitch) => mustSwitch ? switches : ["pass"]);
}

function proposedChoices(battle, side) {
  const request = side.activeRequest;
  if (!request || request.wait) return [""];
  if (request.teamPreview) return previewCandidates(battle, side);
  if (request.forceSwitch) return cartesian(switchCandidates(request));
  if (request.active) {
    return cartesian(
      request.active.map((_, slot) => moveSlotCandidates(battle, request, slot)),
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
          if (side.requestState === "") legal.add("");
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

function enumerateLegalChoices(battle, sideId) {
  if (sideId !== "p1" && sideId !== "p2") {
    throw new Error("side must be p1 or p2");
  }
  if (battle.ended) return [];
  const side = sideId === "p1" ? battle.p1 : battle.p2;
  return validateChoices(battle.toJSON(), sideId, proposedChoices(battle, side));
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
  const previews = {
    p1: battle.p1.pokemon.map((mon) => mon.set.species),
    p2: battle.p2.pokemon.map((mon) => mon.set.species),
  };
  sessions.set(sessionId, battle);
  sessionPreviewSpecies.set(sessionId, previews);

  return {
    session_id: sessionId,
    view: playerView(battle, "p1", previews),
  };
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

  battle.makeChoices(request.p1_choice, request.p2_choice);

  return {
    session_id: request.session_id,
    view: playerView(
      battle,
      "p1",
      sessionPreviewSpecies.get(request.session_id),
    ),
  };
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
    case "state_view":
      return stateView(request);
    case "session_start":
      return startSession(request);
    case "session_view":
      return sessionView(request);
    case "session_snapshot":
      return sessionSnapshot(request);
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
      }) + "\n",
    );
  }
});
