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
    protect: !!m.flags.protect,
    charge: !!m.flags.charge,
    modifiesMove: typeof m.onModifyMove === "function",
  }])),
  species: Object.fromEntries(dex.species.all().filter(s => s.exists).map(s => [s.id, s.types])),
  base_stats: Object.fromEntries(dex.species.all().filter(s => s.exists).map(s => [s.id, s.baseStats])),
  support: Object.fromEntries(dex.species.all().filter(s => s.exists).map(s => {
    const moves = new Set(dex.species.getFullLearnset(s.id).flatMap(l => Object.keys(l.learnset)));
    return [s.id, ["protect", "tailwind", "trickroom", "followme", "ragepowder"].filter(m => moves.has(m))];
  })),
  types: Object.fromEntries(dex.types.all().map(t => [t.name, t.damageTaken])),
}));
