# Queue retention correctness and full-game coverage

The queue-aware history prototype passes its bounded native correctness controls,
but does **not** improve complete-game coverage over the baseline history shadow.
Keep it offline. Production admission and decision behavior are unchanged.

## What changed

Positive native witnesses are grouped by opponent set and the entire serialized
pending queue, including move, target, order, speed and transformation flags.
Each represented queue class keeps at least one witness. Stochastic samples have
a separate bound. If the classes exceed capacity, the result is unresolved with
no installable batch; low probability does not justify discarding a class.

The offline shadow conditions each sampled queue class independently. A witness
for one class cannot certify another. At an owned pivot pause it can probe an
existing native continuation only when the opponent's sole legal command is
wait. Bounded misses, unsupported evidence and deadlines remain unresolved.
Negative evidence applies to represented native histories, not all histories of
the underlying opponent set. Older states stop counting as current immediately
after an unresolved transition.

The production controller's optional partial finite-recovery flag defaults to
false. Only the offline caller enables it. The new native correctness smoke is
an independent CI step with the same prerequisite and cancellation guard as the
other admission/lifecycle controls.

## Correctness evidence

Three native seeds create two public-equivalent pivot states with different
queued opponent moves. Ordinary one-slot resampling drops one; that dropped
history is deliberately designated the true oracle history for the control.
Queue retention preserves it in **3/3** cases. Native conditioning witnesses it
without a false exclusion in **3/3** cases.

All retained matching continuations have the same public observation, owned
legal menu, HP, status counters, boosts, volatiles, ability, item, active tenure,
last move and PP as the oracle. Paired continuations use three additional seeds
per fixture and compare those native fields and the next public boundary.
An oversized queue domain produces zero installable particles. Unit negatives
also cover unsupported evidence, incomplete finite probes and opponents that
still have new command choices.

These controls use known native hypothetical origins and fixture RNG as oracle
inputs. They establish the tested queue-retention behavior, not general history
completeness or a production correctness percentage. The gameplay shadows do
not receive live native state, selected opponent commands or actual battle RNG.

## Full-game measurement

Four complete local games use three fixtures and three opponent policies. Each
game runs production, the baseline history shadow and the queue-aware shadow on
the **same production trajectory**. Both shadows have an eight-second transition
budget; queue capacity is 24 and the decision cap is 64. Neither shadow chooses
production actions. These four cells are below the proposed 12-game milestone.

| Fixture / policy | Actionable decisions | Production fallbacks | Fallback percent | Current baseline / queue checkpoints |
| --- | ---: | ---: | ---: | ---: |
| Bounded / attack-first | 25 | 18 | 72.0% | 3 / 3 |
| Bounded / seeded-mixed | 8 | 0 | 0.0% | 3 / 3 |
| Balance / support-switch | 22 | 21 | 95.5% | 8 / 3 |
| Mirror / attack-first | 6 | 5 | 83.3% | 2 / 2 |
| **Total** | **61** | **44** | **72.1%** | **16 / 11** |

There are 17 production search decisions and 12 forced waits. The primary
fallback denominator excludes forced waits: 44/61. Including waits gives 44/73
(60.3%), which must not be substituted for actionable fallback percentage.

Production fallback reasons: unsupported own status 17; Stomping Tantrum history
18; unfinished switch boundary 3; opponent bench history 1; owned Unburden 2;
Flash Fire 2; Trace 1. These are admission reasons, not independently proved root
causes of every lost history witness.

The final baseline is current at 16/61 actionable checkpoints (26.2%); the queue
prototype at 11/61 (18.0%). This is public/menu alignment, not proof of equivalent
future mechanics. Queue retention has worse availability in this final run.
An earlier exploratory run had 11/61 for both, with the same production fallback
counts. Budgeted sampling can vary with machine load; neither run supports an
improvement claim. The queue prototype's first failures are a partial
queue witness at the bounded attack-first pivot, no complete witness in the
mixed and mirror cases, and the conditioning deadline in balance. Last-good
states are retained only for diagnostics and never counted as current.

## What this means for the next change

The evidence confirms that preserving queue classes alone is insufficient. Do
not enable history maintenance or claim fallback recovery yet. Replay the two
failing pivot checkpoints with recorded hypothetical parent batches and identify
which native history distinctions remain unresolved within a queue class. Keep
the native true-history survival and continuation controls as acceptance gates.
Separately, own-status and Stomping Tantrum rejection account for 35/44 measured
fallbacks; they deserve explicit lifecycle support investigations, with negative
controls retained until exact reconstruction or maintained-history equivalence
is demonstrated. Opponent possibilities must remain represented or unresolved.

## Validation and reproducibility

- Full pytest: **1,589 passed**; Ruff passes.
- Native queue-retention, persistent admission and recovery-soundness smokes pass.
- Parent commit: `be79f9725911149c440741b50a888cd3de51c7ac`.
- Pinned Showdown: `a5df8274e85b0889bf2a9b3422a08b39732374fc`.
- A compact machine-readable measurement and source identity are tracked in
  `reviews/queue-retention-metrics-2026-10-11.json`.
- Full sanitized traces are local ignored artifacts under
  `runs/queue-retention-audit/`. Reproduce with
  `.venv/Scripts/python.exe -m champions_practice.state_maintenance_audit --queue-aware --max-decisions 64 --output runs/queue-retention-audit/final-report.json`.
- Runtime identity hashes the executed source tree before the run. Decisions
  involving deadlines may vary with machine load; this sample is not a strength
  estimate, a baseline win comparison or an arbitrary-team support claim.
