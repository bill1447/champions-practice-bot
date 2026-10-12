"use strict";

// Isolated 11B executable. No session operations and no inbound native-state API.
const readline = require("node:readline");
const { createHash } = require("node:crypto");
const path = require("node:path");
const core = require("./showdown-search-worker");
const { Dex } = require(path.join(__dirname, "../external/pokemon-showdown/dist/sim/dex"));
let particles = [];
let previews = null;
let proposal = 0;
let blocked = false;
let initialized = false;
let step = 0;
const OMIT = new Set(["prng", "prngSeed", "inputLog", "log", "messageLog",
  "sentLogPos", "sentEnd", "sentRequests", "hints"]);
const hash = value => createHash("sha256").update(JSON.stringify(value)).digest("hex");
const ownSeed = label => `sodium,${createHash("sha256").update(`11b-independent-v1:${label}`).digest("hex")}`;
function mechanics(state) {
  return Object.fromEntries(Object.entries(state).filter(([key]) => !OMIT.has(key)));
}
function signature(view) {
  return JSON.stringify(core.normalizedPublicObservationForReachability(view));
}
function damageHistory(state) {
  return { totalDamage: state.lastMove?.totalDamage,
    sides: state.sides.map(side => side.pokemon.map(pokemon => ({
      lastDamage: pokemon.lastDamage, attackedBy: pokemon.attackedBy,
      lastMoveTargetLoc: pokemon.lastMoveTargetLoc,
    }))) };
}
function diversity(states) {
  return { speed_order_classes: new Set(states.map(state => hash(state.speedOrder))).size,
    damage_history_classes: new Set(states.map(state => hash(damageHistory(state)))).size };
}
function rejectPrivate(value) {
  if (!value || typeof value !== "object") return;
  for (const [key, child] of Object.entries(value)) {
    if (["seed", "prng", "prngSeed", "state", "serialized_state", "session_id"].includes(key)) {
      throw new Error(`privileged input forbidden: ${key}`);
    }
    rejectPrivate(child);
  }
}
function keys(request, allowed) {
  for (const key of Object.keys(request)) {
    if (!["id", "op", ...allowed].includes(key)) throw new Error(`unexpected input: ${key}`);
  }
  rejectPrivate(request);
}
function limits(request) {
  const config = { samples: request.samples ?? 96, maxParticles: request.max_particles ?? 12,
    milliseconds: request.milliseconds ?? 600, maxBytes: request.max_bytes ?? 2 * 1024 * 1024 };
  if (!Number.isInteger(config.samples) || config.samples < 1 || config.samples > 512 ||
      !Number.isInteger(config.maxParticles) || config.maxParticles < 1 || config.maxParticles > 32 ||
      !Number.isInteger(config.milliseconds) || config.milliseconds < 0 || config.milliseconds > 5000 ||
      !Number.isInteger(config.maxBytes) || config.maxBytes < 1 || config.maxBytes > 8 * 1024 * 1024) {
    throw new Error("invalid bounded-resource configuration");
  }
  return config;
}
function metrics() {
  return { particles: particles.length, particle_bytes: Buffer.byteLength(JSON.stringify(particles)),
    worker_rss_bytes: process.memoryUsage().rss, worker_heap_bytes: process.memoryUsage().heapUsed };
}
function canonicalTeam(text, format) {
  const team = core.importTeam(text);
  const dex = Dex.forFormat(format);
  for (const pokemon of team) {
    // These explicit genders become known fixture inputs before either battle exists.
    pokemon.gender = dex.species.get(pokemon.species).gender || "M";
  }
  return core.Teams.export(team);
}
function initialize(request) {
  keys(request, ["format", "p1_team", "p2_team", "p1_preview", "p2_preview", "view", "max_particles"]);
  if (initialized) throw new Error("opening may only be initialized once per worker");
  const roots = request.max_particles ?? 12;
  if (!Number.isInteger(roots) || roots < 1 || roots > 32) throw new Error("invalid opening particle count");
  initialized = true;
  const started = performance.now();
  const t1 = core.importTeam(request.p1_team), t2 = core.importTeam(request.p2_team);
  previews = { p1: t1.map(p => p.species), p2: t2.map(p => p.species) };
  for (let index = 0; index < roots; index++) {
    const state = core.createBattle({ ...request, seed: ownSeed(`opening:${index}`) }).state;
    const view = core.stateView({ state, side: "p1", previews }).view;
    if (signature(view) === signature(request.view)) {
      particles.push({ state, root: hash(state), lineage: hash(state), depth: 0 });
    }
  }
  blocked = particles.length === 0;
  return { outcome: blocked ? "unresolved" : "public-witness", current: !blocked,
    reason: blocked ? "opening-sampling-incomplete" : null, roots_generated: roots,
    coverage_exhaustive: false, processing_ms: performance.now() - started,
    generated_branches: 0, deadline_exhausted: false, selection_losses: 0, ...metrics() };
}
function advance(request) {
  keys(request, ["p1_choice", "p2_choice", "view", "samples", "max_particles",
    "milliseconds", "max_bytes", "force_chance_false", "generation"]);
  if (!initialized) throw new Error("initialize an independent opening first");
  const config = limits(request);
  const wasBlocked = blocked;
  const generation = request.generation ?? "sampled";
  if (!["sampled", "guided", "stratified", "spread", "frontier"].includes(generation)) throw new Error("unknown generation strategy");
  const started = performance.now(), deadline = started + config.milliseconds;
  const parents = particles;
  const parentCalls = parents.map(() => 0);
  const retained = new Map();
  const mismatches = {};
  const publicMatchMechanics = new Set();
  const publicSpeedOrders = new Set(), publicDamageHistories = new Set();
  let generated = 0, matched = 0, unsupported = 0, selectionLoss = 0, bytes = 0;
  let depth = 0;
  let pruned = 0, incomplete = 0;
  let firstPublicMatch = null;
  const parentClasses = new Map();
  for (const parent of parents) {
    const key = core.stableJson(mechanics(parent.state));
    if (!parentClasses.has(key)) parentClasses.set(key, parent);
  }
  const pending = [...parentClasses.values()].map(parent => ({ parent, chance: [] }));
  const distinctParents = [...parentClasses.values()];
  const lanes = generation === "frontier" ? [
    { pending: [...pending], restart: 0, parentClass: null, calls: 0 },
    ...[...distinctParents].reverse().map((parent, parentClass) => ({
      pending: [{ parent, chance: [] }], restart: 1, parentClass, calls: 0,
    })),
  ] : Array.from({ length: 4 }, (_, restart) =>
    [...distinctParents].reverse().map((parent, parentClass) => ({
      pending: [{ parent, chance: [] }], restart, parentClass, calls: 0,
    }))).flat();
  let laneIndex = 0, quantumUsed = 0;
  const fair = ["spread", "frontier"].includes(generation);
  const totalPending = () => fair
    ? lanes.reduce((sum, lane) => sum + lane.pending.length, 0) : pending.length;
  let pendingCap = false;
  if (!blocked) {
    for (let attempt = 0; attempt < config.samples; attempt++) {
      if (performance.now() >= deadline) break;
      if ((generation === "guided" || fair) && !totalPending()) break;
      let lane = null;
      if (fair) {
        while ((quantumUsed >= 24 && !(generation === "frontier" && firstPublicMatch === null)) ||
               !lanes[laneIndex].pending.length) {
          laneIndex = (laneIndex + 1) % lanes.length; quantumUsed = 0;
        }
        lane = lanes[laneIndex]; lane.calls++; quantumUsed++;
      }
      const work = lane ? lane.pending.pop() : generation === "guided" ? pending.pop() : null;
      const parent = work ? work.parent : generation === "stratified"
        ? distinctParents[attempt % distinctParents.length] : parents[attempt % parents.length];
      parentCalls[parents.indexOf(parent)]++;
      let result;
      try {
        result = core.resolveFiniteTransitionPath(parent.state, request.p1_choice,
          request.p2_choice, "p1", previews, work?.chance ?? [], {
            ...(work ? { expectedPublicDelta: request.view.public_event_delta }
              : { sampleSeed: ownSeed(`proposal:${proposal++}`) }), consumeNativeDraws: true,
            ...(generation === "stratified" ? {
              expectedPublicDelta: request.view.public_event_delta,
              stratumIndex: Math.floor(attempt / distinctParents.length),
            } : {}),
            forceChanceFalse: request.force_chance_false === true,
          });
      } catch (error) {
        if (!error.message.includes("[Invalid choice]")) throw error;
        result = { unsupported: true, reason: "represented-parent-command-rejected" };
      }
      generated++;
      if (result.pruned) { pruned++; continue; }
      if (result.unsupported) { unsupported++; continue; }
      if (!result.complete) {
        if (!work) throw new Error("sampled finite chance path did not complete");
        incomplete++;
        // Independent deterministic option ordering avoids always preferring
        // the lowest roll. This is enumeration, not a calibrated posterior.
        const orderKey = value => hash({ chance: work.chance, value,
          ...(lane?.restart ? { restart: lane.restart } : {}) });
        const options = [...result.decision.options].sort((a, b) => orderKey(a).localeCompare(orderKey(b)));
        if (totalPending() + options.length > 4096 || work.chance.length >= 128) {
          pendingCap = true; break;
        }
        for (const value of options) (lane ? lane.pending : pending).push({ parent, chance: [...work.chance,
          { kind: result.decision.kind, value, metadata: result.decision.metadata }] });
        continue;
      }
      depth = Math.max(depth, result.random_path.length);
      if (signature(result.view) !== signature(request.view)) {
        const key = JSON.stringify(result.view.public_event_delta?.events?.slice(0, 3));
        mismatches[key] = (mismatches[key] || 0) + 1;
        continue;
      }
      matched++;
      if (firstPublicMatch === null) {
        firstPublicMatch = generated;
        // Preserve ordinary guided discovery until a public match exists.
        // Only then share its remaining budget with alternate prefix lanes.
        if (generation === "frontier") quantumUsed = 24;
      }
      publicSpeedOrders.add(hash(result.state.speedOrder));
      publicDamageHistories.add(hash(damageHistory(result.state)));
      const key = createHash("sha256").update(core.stableJson(mechanics(result.state))).digest("hex");
      publicMatchMechanics.add(key);
      if (retained.has(key)) continue;
      const child = { state: result.state, root: parent.root, depth: parent.depth + 1,
        parent_lineage: parent.lineage,
        lineage: hash({ parent: parent.lineage, p1: request.p1_choice, p2: request.p2_choice,
          chance: result.random_path, child: hash(result.state) }) };
      const size = Buffer.byteLength(JSON.stringify(child));
      if (retained.size >= config.maxParticles || bytes + size > config.maxBytes) {
        selectionLoss++; continue;
      }
      retained.set(key, child); bytes += size;
    }
  }
  if (retained.size) { particles = [...retained.values()]; step++; }
  else blocked = true;
  return { outcome: retained.size ? "public-witness" : "unresolved", current: retained.size > 0,
    reason: retained.size ? null : generated === 0 ? (wasBlocked ? "stale-after-unresolved" : "deadline-exhausted")
      : matched > 0 && selectionLoss > 0 ? "particle-storage-budget-exhausted"
        : unsupported === generated ? "branch-generation-unsupported-domain"
        : generation === "guided" || fair ? "public-conditioning-enumeration-incomplete" : "public-conditioning-sampling-incomplete",
    generated_branches: generated, public_matches: matched, unsupported_branches: unsupported,
    generation, public_prefix_pruned: pruned, incomplete_prefixes: incomplete,
    public_match_diversity: { speed_order_classes: publicSpeedOrders.size,
      damage_history_classes: publicDamageHistories.size, native_mechanical_classes: publicMatchMechanics.size },
    retained_diversity: diversity([...retained.values()].map(particle => particle.state)),
    parent_diversity: diversity(parents.map(particle => particle.state)),
    first_public_match_call: firstPublicMatch,
    parent_call_counts: parentCalls, distinct_parent_classes: distinctParents.length,
    frontier_lanes: fair ? lanes.map(lane => ({
      parent_class: lane.parentClass, restart: lane.restart, calls: lane.calls, pending: lane.pending.length,
    })) : [],
    completed_branches: generated - pruned - unsupported - incomplete,
    pending_paths: generation === "guided" || fair ? totalPending() : 0,
    pending_cap_exhausted: pendingCap,
    maximum_chance_depth: depth, parent_particles: parents.length, selection_losses: selectionLoss,
    coverage_exhaustive: false, sampled_miss_disproved: false,
    deadline_exhausted: !wasBlocked && performance.now() >= deadline,
    budget_ms: config.milliseconds,
    processing_ms: performance.now() - started, mismatch_examples: mismatches,
    public_match_mechanical_keys: [...publicMatchMechanics], ...metrics() };
}
function finiteControl(request) {
  keys(request, ["p1_choice", "p2_choice", "view", "max_nodes", "milliseconds"]);
  if (!initialized || !particles.length) throw new Error("finite control requires a retained parent");
  const maxNodes = request.max_nodes ?? 4096, ms = request.milliseconds ?? 1000;
  if (!Number.isInteger(maxNodes) || maxNodes < 1 || maxNodes > 10000 ||
      !Number.isInteger(ms) || ms < 0 || ms > 5000) throw new Error("invalid finite budget");
  const started = performance.now(), pending = [[]];
  let nodes = 0, leaves = 0, unsupported = false;
  while (pending.length && nodes < maxNodes && performance.now() - started < ms) {
    const chance = pending.pop(); nodes++;
    const result = core.resolveFiniteTransitionPath(particles[0].state, request.p1_choice,
      request.p2_choice, "p1", previews, chance, { consumeNativeDraws: true });
    if (result.unsupported) { unsupported = true; break; }
    if (!result.complete) {
      for (const value of result.decision.options) {
        pending.push([...chance, { kind: result.decision.kind, value, metadata: result.decision.metadata }]);
      }
      if (pending.length > 4096) break;
    } else {
      leaves++;
      if (signature(result.view) === signature(request.view)) {
        return { outcome: "witnessed", exhaustive: false, nodes, leaves, chance_path: chance,
          witness: result.state, proof_scope: "one-retained-parent/finite-chance-inputs" };
      }
    }
  }
  const exhaustive = pending.length === 0 && !unsupported;
  return { outcome: exhaustive ? "disproved" : "unresolved", exhaustive, nodes, leaves,
    pending_paths: pending.length, unsupported,
    deadline_exhausted: performance.now() - started >= ms,
    proof_scope: "one-retained-parent/finite-chance-inputs" };
}
function handle(request) {
  if (request.op === "ping") { keys(request, []); return { pong: true }; }
  if (request.op === "canonical_team") {
    keys(request, ["team", "format"]); return { team: canonicalTeam(request.team, request.format) };
  }
  if (request.op === "initialize") return initialize(request);
  if (request.op === "advance") return advance(request);
  if (request.op === "inspect") { keys(request, []); return { ...metrics(), current: !blocked, particles }; }
  if (request.op === "finite_control") return finiteControl(request);
  throw new Error(`unsupported experimental operation: ${request.op}`);
}
const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
rl.on("line", line => {
  let id = null;
  try {
    const request = JSON.parse(line); id = request.id ?? null;
    process.stdout.write(JSON.stringify({ id, ok: true, result: handle(request) }) + "\n");
  } catch (error) {
    process.stdout.write(JSON.stringify({ id, ok: false, error: error.message }) + "\n");
  }
});
