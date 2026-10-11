# Present-state production support

Fresh midgame construction currently preserves visible projections but cannot
establish every latent native counter. A matching own request and legal menu
therefore remain necessary checks, not sufficient production admission.

`BeliefDecisionEngine._try_present_public_rebase` now applies
`unsupported_present_mechanics` before creating a hypothetical worker. It
uses only the sanitized observation and never reads a live snapshot, native
counter, opponent private set or historical particle.

The following fresh midgame inputs deliberately use a legal fallback:

- Active weather, unsupported terrain, pseudo-weather or side conditions:
  `fresh-public-world:unsupported-public-effect-duration`.
- A protection-family move in the just-completed public execution delta,
  including Quick Guard/Wide Guard's shared native stall counter:
  `fresh-public-world:unsupported-public-protection-chain`.
- Missing, empty, incomplete or stale execution evidence:
  `fresh-public-world:unsupported-public-protection-history`.
- Missing effect projection:
  `fresh-public-world:unsupported-public-effect-projection`.

Failed, prevented and called protection attempts are conservatively unsupported;
the gate does not guess a counter reset. Side conditions are also conservative:
the current projection cannot establish unknown durations or hazard layers.
None of these reasons proves a hidden world impossible.

Turn-one native openings and exact native forks remain available. Fresh move
states without these unsupported mechanics can still use tactical search.
Old particles are discarded before the gate, so they cannot silently bypass it.

## Diagnostics versus production

`build_present_rebase` and the low-level native materializer remain experimental
offline diagnostic constructors. Their output is projection-compatible evidence,
not proof of complete persistent mechanics. Existing Unburden/Mega/faint tests
continue to isolate those mechanics; their successes do not waive this production
gate. The new `present_mechanics_smoke` tests the actual decision engine boundary
against both native counter defects.

Terrain now has a public-evidence recovery path. The ledger retains field and
public source snapshots at every observed turn. Continuous terrain from turn one
authorizes its age. Later canonical Surge starts identify a public source side,
species, ability and turn; continuous observations after that start establish age.
Unknown starts, missing turns and unsupported events remain rejected.

The native constructor validates the source against its approved hypothetical
set, restores terrain after switching, then advances the pinned
`fieldEvent('Residual', [])` lifecycle. Pokemon residual callbacks are excluded.
Native expiration rejects the proposal; timers are never assigned directly.
Extension items remain native set hypotheses; an extender lost since activation
is unsupported. Native controls cover opening and overwrite starts, several
remaining durations, expiration and serialization. Weather, pseudo-weather,
side effects and protection-chain reconstruction remain outstanding.

A publicly prevented action with a pinned `cant` reason, such as flinching,
cannot refresh native stall. The prior duration-one stall expires on that turn's
residual. Missing execution history and executed protection attempts remain
unsupported.

Recovery is measured by fallback rate and midgame search coverage on both frozen
fixtures. Do not remove correctness checks to recover benchmark numbers.

## Re-enabling support

For each mechanic, implement a public-derived state/domain with explicit unknown
history. Derive effects from canonical public starts, ends, turn boundaries,
switch/reset events, called moves and public extension evidence. Do not copy
private native counters or require historical RNG witnesses.

Establish construction through supported pinned operations, reject unsupported
domains, and require native lifecycle/serialization controls. Protection tests
must include successful and failed chains, interruption, called moves,
Quick/Wide Guard, switch-out/back and opponent uncertainty. Timer tests must
include both sides, activation/expiration, reset/overwrite and relevant
item/ability extensions. Then demonstrate public-only production admission and
compare both frozen eight-game fixtures with unchanged configuration.
