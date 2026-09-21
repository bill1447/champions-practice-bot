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
    case "session_start":
      return startSession(request);
    case "session_view":
      return sessionView(request);
    case "session_snapshot":
      return sessionSnapshot(request);
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
