# Offline strength league

The strength league is the common gameplay measurement surface for future bot changes.

Its purpose is deliberately narrower than replay-policy recall, strategic unit tests, or
recovery soundness. Those measurements answer whether a component behaves as intended.
The league asks whether a concrete bot configuration actually wins more games under a fixed,
reproducible benchmark.

## V1 scope

The first league is intentionally small:

- fixture: `current-roster-mirror-v1`;
- bot: the production sealed belief/search/strategy stack as `p2`;
- opponent: `public-fallback-v1`, which chooses only from the baseline side's public legal
  command list;
- both sides use the current smoke/practice roster;
- both sides use the fixed demo preview;
- battle and particle seeds are deterministic.

This is a regression instrument, not a calibrated ladder-strength estimate. A high win rate
against `public-fallback-v1` does not mean the bot is high-ladder strength.

The current belief controller is p2-oriented, so v1 does not claim side-swapped fairness.
Future league fixtures should add side-generic policies before treating matchup ratings as
portable Elo-like strength.

## What is frozen in each run

A run ID binds:

- repository commit SHA;
- pinned Showdown revision;
- format ID;
- fixture ID;
- bot and baseline IDs;
- exact team-text hashes;
- battle count;
- deterministic seed;
- belief-world/particle limits;
- candidate/response limits;
- strategic limits;
- decision and conditioning budgets.

The report also stores every generated battle seed and particle seed. Re-running the same
configuration on the same commit reuses the immutable report unless `-Refresh` is supplied.

Generated reports live under:

`runs/strength-league/<run-id>/report.json`

and the most recently selected report is mirrored to:

`runs/strength-league/latest-report.json`

The entire `runs/` tree remains gitignored.

## Metrics

The v1 report includes:

- wins, losses, draws, and score rate;
- decisive-game win rate with a 95% Wilson interval;
- mean/median/max turn count;
- total decisions and exact-search decisions;
- forced-wait decisions;
- fallback count, rate, and reasons;
- belief-degraded turns and rate;
- decisions that retained a strategic-plan label;
- total exact-search branch count;
- decision-time mean/p50/p95/max;
- conditioning-time mean/p50/p95/max.

Fallback and degraded rates are first-class metrics. A challenger that appears stronger only
because it repeatedly misses its decision budget or loses posterior quality is not a clean
improvement.

## Running

A normal local baseline run:

```powershell
.\strength-league.ps1
```

A quick infrastructure check:

```powershell
.\strength-league.ps1 -Battles 1 -WorldLimit 2 -MaxParticles 2 `
    -CandidateLimit 2 -ResponseLimit 2 `
    -DecisionBudgetSeconds 3 -ConditioningBudgetSeconds 3
```

A larger comparison run can increase `-Battles` while leaving every other parameter fixed.

## Promotion rule

Do not promote a new search, strategy, policy, value, or equilibrium component merely because
its internal metric improves.

The intended comparison is:

1. freeze a champion configuration and benchmark run definition;
2. run the challenger with the same fixture, seeds, budgets, and Showdown pin;
3. compare gameplay outcome together with fallback, latency, and degraded-belief metrics;
4. promote only when the result is large enough and stable enough to justify the change.

V1 does not automate a statistical promotion threshold because eight default games are far
too few for one. Larger benchmark suites and stronger opponents should be added before the
league is used as a formal gate.

## Planned extensions

The next extensions should be driven by measurement needs rather than breadth for its own
sake:

- multiple fixed team/archetype fixtures;
- exact-team evaluation-pool fixtures without leaking hidden truth into priors;
- stronger public-only baseline opponents;
- a side-generic production controller so each matchup can be role-swapped;
- persistent champion/challenger snapshots;
- decision provenance for baseline-, strategy-, and learned-policy-reserved candidates;
- shadow logging of minimax versus matrix-game/equilibrium recommendations.

Replay-policy recall remains an offline model metric. The strength league is where a policy
integration must demonstrate that spending search budget on learned candidates improves
actual play.
