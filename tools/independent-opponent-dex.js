"use strict";
// Public, static Champions data only. No Battle/session/native-state input.
const path = require("node:path");
const {TeamValidator} = require(path.resolve(__dirname, "../external/pokemon-showdown/dist/sim/team-validator"));
const dex = TeamValidator.get("gen9championsvgc2026regmc").dex;
console.log(JSON.stringify({
  species: Object.fromEntries(dex.species.all().filter(s => s.exists).map(s => [s.id, {
    name: s.name, baseSpecies: s.baseSpecies, baseStats: s.baseStats, types: s.types,
    abilities: s.abilities, heightm: s.heightm, weightkg: s.weightkg,
  }])),
  moves: Object.fromEntries(dex.moves.all().filter(m => m.exists).map(m => [m.id, {
    name: m.name, basePower: m.basePower, type: m.type, category: m.category,
    accuracy: m.accuracy, pp: m.pp, priority: m.priority, target: m.target,
    flags: m.flags, boosts: m.boosts, multihit: m.multihit,
  }])),
}));
