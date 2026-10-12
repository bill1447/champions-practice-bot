"use strict";
// Static public data only: no Battle, session, seed or serialized state input.
const path = require("node:path");
const root = path.resolve(__dirname, "../external/pokemon-showdown/dist");
const {TeamValidator} = require(path.join(root, "sim/team-validator"));
const dex = TeamValidator.get("gen9championsvgc2026regmc").dex;
console.log(JSON.stringify({
  moves: Object.fromEntries(dex.moves.all().filter(m => m.exists).map(m => [m.id, {
    category: m.category, type: m.type, power: m.basePower, priority: m.priority,
    accuracy: m.accuracy === true ? 100 : m.accuracy, target: m.target,
  }])),
  species: Object.fromEntries(dex.species.all().filter(s => s.exists).map(s => [s.id, s.types])),
  types: Object.fromEntries(dex.types.all().map(t => [t.name, t.damageTaken])),
}));
