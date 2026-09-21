"use strict";

const readline = require("readline");
const path = require("path");

const root = path.resolve(__dirname, "..");
const showdownRoot = path.join(root, "external", "pokemon-showdown");
const { Battle } = require(path.join(showdownRoot, "dist", "sim", "battle"));
const { Teams } = require(path.join(showdownRoot, "dist", "sim", "teams"));

const sessions = new Map();
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

function publicActive(mon) {
  if (!mon) return null;
  return {
    species: mon.species.name,
    hp_percent: hpPercent(mon),
    fainted: mon.fainted,
    status: mon.status || null,
    boosts: { ...mon.boosts },
  };
}

function ownPokemon(mon) {
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
    active: mon.isActive,
  };
}

function playerView(battle, sideId = "p1") {
  if (sideId !== "p1") {
    throw new Error("Only the p1 practice-player view is exposed right now");
  }

  return {
    turn: battle.turn,
    phase: battle.requestState || (battle.ended ? "ended" : ""),
    ended: battle.ended,
    winner: battle.winner || null,
    field: {
      weather: battle.field.weather || null,
      terrain: battle.field.terrain || null,
      pseudo_weather: Object.keys(battle.field.pseudoWeather || {}),
    },
    request: cloneJson(battle.p1.activeRequest),
    player: {
      name: battle.p1.name,
      active: battle.p1.active.map((mon) => (mon ? mon.species.name : null)),
      team: battle.p1.pokemon.map(ownPokemon),
    },
    opponent: {
      name: battle.p2.name,
      preview_species: battle.p2.pokemon.map((mon) => mon.baseSpecies.name),
      active: battle.p2.active.map(publicActive),
    },
  };
}

function summarize(battle) {
  function sideSummary(side) {
    return {
      name: side.name,
      active: side.active.map((mon) =>
        mon
          ? {
              species: mon.species.name,
              hp: mon.hp,
              maxhp: mon.maxhp,
              fainted: mon.fainted,
              status: mon.status || null,
            }
          : null,
      ),
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

function validateChoice(state, sideId, candidate) {
  const branch = Battle.fromJSON(JSON.stringify(state));
  branch.restart(() => {});
  const side = sideId === "p1" ? branch.p1 : branch.p2;
  try {
    if (candidate === "") {
      return side.requestState === "" ? "" : null;
    }
    if (!side.choose(candidate) || !side.isChoiceDone()) return null;
    return side.getChoice();
  } catch {
    return null;
  } finally {
    branch.destroy();
  }
}

function enumerateLegalChoices(battle, sideId) {
  if (sideId !== "p1" && sideId !== "p2") {
    throw new Error("side must be p1 or p2");
  }
  if (battle.ended) return [];
  const state = battle.toJSON();
  const side = sideId === "p1" ? battle.p1 : battle.p2;
  const legal = new Set();
  for (const candidate of proposedChoices(battle, side)) {
    const canonical = validateChoice(state, sideId, candidate);
    if (canonical !== null) legal.add(canonical);
  }
  return [...legal].sort();
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

function resolveBranch(state, p1Choice, p2Choice, includeState = true) {
  if (!state) {
    throw new Error("branch requires a serialized battle state");
  }
  if (typeof p1Choice !== "string" || typeof p2Choice !== "string") {
    throw new Error("branch requires p1_choice and p2_choice strings");
  }

  const battle = Battle.fromJSON(JSON.stringify(state));
  battle.restart(() => {});

  battle.makeChoices(p1Choice, p2Choice);

  const response = {
    summary: summarize(battle),
  };
  if (includeState) response.state = battle.toJSON();
  battle.destroy();
  return response;
}

function branchBattle(request) {
  return resolveBranch(
    request.state,
    request.p1_choice,
    request.p2_choice,
    request.include_state !== false,
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
            false,
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
  sessions.set(sessionId, battle);

  return {
    session_id: sessionId,
    view: playerView(battle),
  };
}

function sessionView(request) {
  const battle = getSession(request.session_id);
  return {
    session_id: request.session_id,
    view: playerView(battle),
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
    view: playerView(battle),
  };
}

function closeSession(request) {
  const battle = getSession(request.session_id);
  battle.destroy();
  sessions.delete(request.session_id);
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
