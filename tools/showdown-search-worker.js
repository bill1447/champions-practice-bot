"use strict";

const readline = require("readline");
const path = require("path");

const root = path.resolve(__dirname, "..");
const showdownRoot = path.join(root, "external", "pokemon-showdown");
const { Battle } = require(path.join(showdownRoot, "dist", "sim", "battle"));
const { Teams } = require(path.join(showdownRoot, "dist", "sim", "teams"));

function importTeam(text) {
  const team = Teams.import(text);
  if (!team || !Array.isArray(team) || team.length === 0) {
    throw new Error("Could not import Showdown team text");
  }
  return team;
}

function summarize(battle) {
  function sideSummary(side) {
    return {
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

function createBattle(request) {
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

  const battle = new Battle(options);

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

function branchBattle(request) {
  if (!request.state) {
    throw new Error("branch requires a serialized battle state");
  }
  if (typeof request.p1_choice !== "string" || typeof request.p2_choice !== "string") {
    throw new Error("branch requires p1_choice and p2_choice strings");
  }

  const battle = Battle.fromJSON(JSON.stringify(request.state));
  battle.restart(() => {});

  battle.makeChoices(request.p1_choice, request.p2_choice);

  const response = {
    state: battle.toJSON(),
    summary: summarize(battle),
  };
  battle.destroy();
  return response;
}

function handle(request) {
  switch (request.op) {
    case "ping":
      return { pong: true };
    case "create":
      return createBattle(request);
    case "branch":
      return branchBattle(request);
    default:
      throw new Error(`Unknown operation: ${request.op}`);
  }
}

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
