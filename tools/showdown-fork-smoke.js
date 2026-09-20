"use strict";

const path = require("path");

const root = path.resolve(__dirname, "..");
const showdownRoot = path.join(root, "external", "pokemon-showdown");
const { Battle } = require(path.join(showdownRoot, "dist", "sim", "battle"));

const FORMAT = "gen9championsvgc2026regmc";
const SEED = "sodium,00000001000000020000000300000004";

function team() {
  return [
    {
      species: "Indeedee-F",
      ability: "psychicsurge",
      item: "colburberry",
      moves: ["psychic", "followme", "trickroom", "imprison"],
      nature: "Relaxed",
      evs: { hp: 32, def: 32, spe: 2 },
      level: 50,
    },
    {
      species: "Sneasler",
      ability: "unburden",
      item: "psychicseed",
      moves: ["closecombat", "direclaw", "rockslide", "protect"],
      nature: "Adamant",
      evs: { hp: 2, atk: 32, spe: 32 },
      level: 50,
    },
    {
      species: "Gardevoir",
      ability: "trace",
      item: "gardevoirite",
      moves: ["expandingforce", "hypervoice", "mysticalfire", "protect"],
      nature: "Modest",
      evs: { hp: 4, spa: 32, spe: 30 },
      level: 50,
    },
    {
      species: "Armarouge",
      ability: "flashfire",
      item: "lifeorb",
      moves: ["expandingforce", "armorcanon", "wideguard", "protect"],
      nature: "Quiet",
      evs: { hp: 32, spa: 32, spd: 2 },
      level: 50,
    },
    {
      species: "Rillaboom",
      ability: "grassysurge",
      item: "sitrusberry",
      moves: ["grassyglide", "woodhammer", "highhorsepower", "protect"],
      nature: "Careful",
      evs: { hp: 32, atk: 2, spd: 32 },
      level: 50,
    },
    {
      species: "Metagross",
      ability: "clearbody",
      item: "metagrossite",
      moves: ["psychicfangs", "steelroller", "stompingtantrum", "protect"],
      nature: "Adamant",
      evs: { hp: 2, atk: 32, spe: 32 },
      level: 50,
    },
  ];
}

function createBattle() {
  return new Battle({
    formatid: FORMAT,
    seed: SEED,
    strictChoices: true,
    p1: { name: "Fork P1", team: team() },
    p2: { name: "Fork P2", team: team() },
  });
}

function restore(serialized) {
  const battle = Battle.fromJSON(serialized);
  battle.restart(() => {});
  return battle;
}

function hpSnapshot(battle) {
  return {
    p1: battle.p1.active.map((mon) => (mon ? mon.hp : null)),
    p2: battle.p2.active.map((mon) => (mon ? mon.hp : null)),
  };
}

const source = createBattle();

// Bring Indeedee / Sneasler / Gardevoir / Rillaboom, with Indeedee + Sneasler leading.
source.makeChoices("team 1235", "team 1235");

if (source.turn !== 1) {
  throw new Error(`Expected turn 1 after team preview, got ${source.turn}`);
}

const serialized = JSON.stringify(source);
const branchA = restore(serialized);
const branchB = restore(serialized);

const branchBBefore = JSON.stringify(hpSnapshot(branchB));

// Branch A: defensive redirection + spread pressure.
branchA.makeChoices(
  "move followme, move rockslide",
  "move psychic 1, move rockslide",
);

if (JSON.stringify(hpSnapshot(branchB)) !== branchBBefore) {
  throw new Error("Advancing branch A mutated branch B");
}

// Branch B: direct double-target pressure.
branchB.makeChoices(
  "move psychic 1, move closecombat 1",
  "move psychic 1, move rockslide",
);

if (branchA.turn !== 2 || branchB.turn !== 2) {
  throw new Error(
    `Expected both forks to advance to turn 2; got A=${branchA.turn}, B=${branchB.turn}`,
  );
}

const stateA = JSON.stringify(branchA.toJSON());
const stateB = JSON.stringify(branchB.toJSON());

if (stateA === stateB) {
  throw new Error("Distinct choices produced identical forked battle states");
}

console.log("Showdown state fork smoke test");
console.log(`Format:  ${FORMAT}`);
console.log("Snapshot: serialized after team preview");
console.log("Branch A: Follow Me + Rock Slide");
console.log("Branch B: Psychic + Close Combat");
console.log(`A HP:    ${JSON.stringify(hpSnapshot(branchA))}`);
console.log(`B HP:    ${JSON.stringify(hpSnapshot(branchB))}`);
console.log("RESULT:  Battle.toJSON/fromJSON supports independent exact branches");

source.destroy();
branchA.destroy();
branchB.destroy();
