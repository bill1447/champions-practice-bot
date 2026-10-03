# Offline recovery soundness

The recovery soundness harness measures one property before experimental recovery is allowed
to influence live belief admission:

> Given an exact hidden world that we know generated a public transition, can our conditioning
> or reachability machinery incorrectly remove that true world?

This is an offline validation surface. It has no live particle-install or live-session
authority.

## Two failure channels

The harness measures two different ways the true world could be lost.

### 1. Reachability authority

A known-real exact pre-state, action pair, and public observation are evaluated through the
current isolated reachability boundary.

For true-world survival:

- `WITNESSED` survives;
- `UNRESOLVED` survives;
- `UNSUPPORTED` survives;
- only `EXHAUSTIVELY_DISPROVED` excludes the world.

This intentionally treats ambiguity as survival. A finite RNG miss is not negative evidence.

### 2. Production-shaped sampled conditioning

The harness can also start from an explicit particle set containing a tagged true
`world_id` and run the same `condition_particles` path used by production. Each case
supplies deterministic RNG batches; the harness accumulates misses and stops at the first
nonempty batch, mirroring the production adaptive-conditioning shape.

It then emulates the live controller's current one-transition update semantics:

- when no sampled branch matches at all, retain the last-good particles and mark degraded;
- when at least one sampled branch matches, replace/resample from those matching children.

The second case is important: a wrong world can happen to receive a matching sampled RNG
outcome while the true world does not. If that replacement posterior contains no particle
with the tagged true `world_id`, the harness records a conditioning false exclusion.

The harness does not change that production behavior in this PR. It measures it.

## Primary metric

For either channel:

`true-world survival rate = surviving known-real boundaries / evaluated known-real boundaries`

The target for authoritative recovery is effectively zero false exclusions. Witness/coverage
rates are secondary; unresolved or unsupported cases are acceptable until mechanics support
is expanded.

Reports expose:

- total boundaries;
- surviving boundaries;
- false exclusions;
- reachability witness / unresolved / unsupported counts;
- conditioning degraded-retention count;
- true-world survival rate.

## Deterministic hard cases

Every detected false exclusion can be serialized as a self-contained JSON regression.

Reachability regressions preserve:

- exact pre-state;
- state fingerprint;
- exact action pair;
- actual public observation;
- actual and probe RNG seeds;
- actual RNG draw count;
- preview context;
- reachability status and coverage.

Conditioning regressions additionally preserve:

- all starting particles;
- tagged true `world_id`;
- fixed adaptive conditioning RNG batches;
- resample limit/seed;
- branch/mismatch counters;
- resulting posterior world IDs.

CI writes any smoke-test false exclusion to:

`.runtime/recovery-hard-cases/`

which is included in the existing CI artifact upload. Larger local/corpus runs should write
hard cases under the external data root, for example:

`F:\Showdown replay data\recovery-hard-cases\`

and should not commit those generated cases to Git unless one is deliberately minimized into
a curated test fixture.

## Current pinned-Showdown smoke

```powershell
.\recovery-soundness-smoke.ps1
```

The smoke:

1. creates a known exact Champions hidden world in pinned Showdown;
2. generates a real stochastic public transition from that world;
3. verifies the exact RNG continuation is a positive reachability witness;
4. finds a different RNG seed that produces a distinct public outcome;
5. verifies that sampled miss remains `UNRESOLVED`, not impossible;
6. chains additional exact true-world boundaries;
7. runs production-shaped conditioning with both a matching RNG sample and a known sampled
   miss;
8. requires the true world to survive every tested boundary.

This fixed smoke is only the baseline. The next step is to generate many cases from the
external exact-team corpus and track survival by team, turn, mechanic family, and observation
shape.

## Scope

This harness is not the independent Showdown differential validator from the roadmap. The
current fixtures can be generated and evaluated by the same pinned Showdown runtime. It is
therefore a soundness monitor for our exclusion/conditioning logic, not an independent proof
that Showdown itself or our public-observation producer is correct.
