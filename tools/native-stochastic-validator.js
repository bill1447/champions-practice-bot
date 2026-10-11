"use strict";

// Privileged audit executable, separate from the tracker. It reports scalar
// validation only; oracle states, seeds and chance tapes never go to the tracker.
const readline = require("node:readline");
const core = require("./showdown-search-worker");
function comparable(state) {
  const result = JSON.parse(JSON.stringify(state));
  result.log = result.log.map(line => line.startsWith("|t:|") ? "|t:|<clock>" : line);
  return core.stableJson(result);
}
function validate(request) {
  const ordinary = core.resolveBranch(request.state, request.p1_choice, request.p2_choice, true);
  const traced = core.resolveFiniteTransitionPath(request.state, request.p1_choice,
    request.p2_choice, "p1", request.previews, [], { traceNative: true,
      expectedPublicDelta: core.stateView({ state: ordinary.state, side: "p1", previews: request.previews }).view.public_event_delta });
  if (traced.pruned) throw new Error("public-prefix conditioning falsely pruned actual oracle trajectory");
  if (traced.unsupported) return { supported: false, reason: traced.reason };
  const replayed = core.resolveFiniteTransitionPath(request.state, request.p1_choice,
    request.p2_choice, "p1", request.previews, traced.random_path, { consumeNativeDraws: true });
  if (comparable(ordinary.state) !== comparable(traced.state) ||
      comparable(ordinary.state) !== comparable(replayed.state)) {
    throw new Error("isolated oracle chance trace/replay diverged from ordinary native resolution");
  }
  return { supported: true, trace_replay_native_equal: true, draws: traced.random_path.length };
}
const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
rl.on("line", line => {
  let id = null;
  try {
    const request = JSON.parse(line); id = request.id ?? null;
    const result = request.op === "ping" ? { pong: true }
      : request.op === "validate_chance_trace" ? validate(request)
      : (() => { throw new Error("unsupported validator operation"); })();
    process.stdout.write(JSON.stringify({ id, ok: true, result }) + "\n");
  } catch (error) {
    process.stdout.write(JSON.stringify({ id, ok: false, error: error.message }) + "\n");
  }
});
