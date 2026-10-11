# Public ledger protocol recovery — 2026-10-11

This update preserves public evidence through resistance-berry consumption and
ability-protected stat-drop failures. The previous diversity run's balance game
invalidated its ledger at Shuca Berry's public `[weaken]` event, then recorded
21 ledger-unavailable fallbacks. The same game later emitted Inner Focus's
`-fail ... unboost atk` event, which was independently unsupported by the schema.
Fixing the berry marker alone would have lost the ledger again at that later
event.

## Evidence and exact support

Pinned `data/items.ts` resistance-berry callbacks emit a second
`-enditem <actor> <berry> [weaken]` after native `eatItem()`. The validator now
accepts that exact four-token form only for the 18 pinned resistance berries
and a canonical public actor/item. Other items, `-item` events, combined markers,
marker payloads and unknown tags remain rejected. The raw public event remains
in the ledger; it is neither deleted nor translated into an invented counter.

Pinned `data/abilities.ts` emits `-fail <actor> unboost [stat]
[from]:ability:<ability> [of]:<actor>` for stat-drop prevention. The validator
accepts the exact source/stat/self-actor relationships of Big Pecks, Hyper Cutter,
Illuminate, Inner Focus, Keen Eye, Mind's Eye, Oblivious, Own Tempo, Scrappy,
Clear Body, Full Metal Body and White Smoke. The final three use the native
statless form. Incorrect stats, other abilities, missing fields and another
source actor remain rejected.

This changes passive public protocol validation. Native construction, exact
owned request/legal-menu checks, persistent-effect support gates and negative
exclusion authority remain intact. Accepting these public facts does not prove
their hidden counterfactual worlds or timers.

## Regression evidence

All 1,539 pytest tests pass, including four new canonical-shape controls and
ten invalid-shape controls. Ruff and diff checks pass. Native controls generate
Inner Focus's actual Intimidate failure and a Shuca Berry's actual weaken event,
then initialize/advance the unmodified public ledger. This standalone control is
included in CI.

The optional frozen-game replay reconstructs the previous balance game using its
original public action sequence and offline fixture seed. Every before/after
public checkpoint matches the original saved checkpoint, and all 29 decisions
retain the growing evidence history. This replay is diagnostic; the saved
opponent action sequence and exact fixture truth never become production input.

Two known-real transition controls with the new event forms are witnessed and
survive exclusion evaluation. The existing five-case true-world smoke also
passes (four witnessed, one unresolved; zero false exclusions), as does sampled
conditioning survival. Human Mega remains eight searches and zero fallbacks.
Native execution authority, Trace/Trick Room and replacement controls pass.

## Measurement

The final nine-cell diversity matrix completed under unchanged configuration:
seed 15701, fixed previews, all three policies and eight-second decision budgets.

| Metric | Previous diversity run | This update |
| --- | ---: | ---: |
| Games completed / failed | 9 / 0 | 9 / 0 |
| Search decisions | 39 | 44 |
| Forced waits | 16 | 16 |
| Fallbacks / all decisions | 83/138 (60.1%) | 64/124 (51.6%) |
| Search / action decisions | 39/122 (32.0%) | 44/108 (40.7%) |
| Ledger-unavailable fallbacks | 21 | 0 |
| Admitted midgame checkpoints | 28 | 33 |

The affected balance/attack-first cell changes from 23 fallbacks in 29 decisions
to 3 in 13, with searches rising from 3 to 7. The frozen command replay establishes
that the original 29-decision history also stays valid; the new game follows a
different trajectory once recovery works. Aggregate differences therefore do
not represent 19 independently repaired mechanics.

The admission audit has no errors. Construction tries 48 roots and generates 67
native candidates, admitting 63 independently positive matches/particles before
resampling. Historical witnesses and exhaustive exclusions remain zero. Search
generates 28,110 branches. Remaining fallbacks are 46 unsupported field durations,
9 unsupported protection residual effects, 4 unsupported Trace states, 2 mid-turn
replacement boundaries, 2 exact owned move-disabled mismatches and 1 legal-menu
mismatch. The broad support limits remain visible rather than bypassed.

Report: `runs/diversity-league/adbf6b8f50a5e049b4bb/report.json`. It binds parent
commit `b28db0e59c96cc9d9c3edd57c0db04a0613de2c2` and dirty runtime fingerprint
`d04c8d66896138396101965009f582696e6fd23c081cae10c0155a240429e2f8`.
Runtime sources stayed unchanged during measurement. Small samples, changed
trajectories and wall-clock search budgets limit causal/strength claims.

Both frozen eight-game fixtures also completed with unchanged configuration,
seed 15601 and eight-second budgets:

| Fixture | Search | Wait | Fallback | Admitted midgame checkpoints |
| --- | ---: | ---: | ---: | ---: |
| Mirror `81f191550de3b072bdaf` | 34 | 14 | 0/48 | 26 |
| Synthetic `9b43c2591625e1bf3a67` | 52 | 11 | 0/63 | 44 |

Unlike the original pre-telemetry runs, these reports directly record native
admission. Mirror tries 37 roots and admits all 71 generated native candidates;
synthetic tries 82 roots and admits all 127. Both trace/admission consistency
audits have no errors, and neither records historical witnesses or exhaustive
exclusions. Decision p95 remains within budget at 7.777 and 7.779 seconds.
Reports are under `runs/strength-league/<run-id>/report.json`, bound to the same
runtime fingerprint and parent commit as the diversity matrix. Search coverage
on both frozen fixtures remains complete for decisions requiring an action.

## Remaining scope

The affected balance matchup still rejects exact owned move-disabled mismatches
and an unfinished-turn replacement. Those checks should stay in place. Next,
derive the public entry/reset lifecycle needed by Fake Out's native eligibility
and review the saved legal-menu mismatch. Weather/Tailwind duration domains and
other residual/Trace histories remain separate support work. Continue to measure
recovery on broader teams rather than treating one narrow fixture as universal
mechanics coverage.

No deployment was performed for this update. This implementation review does
not replace the independent milestone review required before PR #240 is ready.
