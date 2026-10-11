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
- Protection history whose complete ordered success/reset evidence is unavailable:
  `fresh-public-world:unsupported-public-protection-chain`.
- Missing, empty, incomplete or stale execution evidence:
  `fresh-public-world:unsupported-public-protection-history`.
- Missing effect projection:
  `fresh-public-world:unsupported-public-effect-projection`.

Protection now has a public lifecycle support path. Ordered channel-visible
move, cant, switch/drag and single-turn success/failure events establish the shared
stall chain, including Quick/Wide Guard. Every completed turn needs a move-phase
completion snapshot; partial replacement windows cannot authorize a final counter.
One confirmed attempt per actor/turn is supported, including called attempts.
Multiple attempts, missing evidence, actor swaps and unrelated native residual
effects remain unsupported. Side conditions are also conservative:
the current projection cannot establish unknown durations or hazard layers.
None of these reasons proves a hidden world impossible.

Turn-one native openings and exact native forks remain available. Fresh move
states without these unsupported mechanics can still use tactical search.
Old particles are discarded before the gate, so they cannot silently bypass it.

## Diagnostics versus production

Production construction receives the independently derived terrain and protection
plans after the public support gate. The low-level materializer also remains an
offline diagnostic surface: calling it without plans does not establish counters.
Exact own state/request, legal menu and public projection checks remain required.
`present_mechanics_smoke` includes repaired native controls and a missing-history
negative control at the actual production boundary.

Terrain now has a public-evidence recovery path. The ledger retains field and
public source snapshots at every observed turn. Continuous terrain from turn one
authorizes its age. Later canonical Surge starts identify a public source side,
species, ability and turn. Source identity is tracked through ordered public
switches rather than assigned from the final occupant of a slot. Repeated start
occurrences remain distinct; snapshots of a growing delta retain its full prefix.
Unknown starts, missing turns and unsupported events remain rejected.

The native constructor validates the source against its approved hypothetical
set, restores terrain after switching, then advances the pinned
`fieldEvent('Residual', [])` lifecycle. Pokemon residual callbacks are excluded.
Native expiration rejects the proposal; timers are never assigned directly.
Extension items remain native set hypotheses. Public Terrain Extender inventory
changes are unsupported pending an extension timing domain. Copied-ability
sources such as Trace can also fail the native source check. Native controls
cover opening and overwrite starts, same-terrain entry without refresh,
reactivation after another terrain, retained extenders, several remaining
durations, expiration and serialization. This is limited terrain support,
not a claim that every source or duration domain has been covered. Weather,
pseudo-weather and side effects remain outstanding.

A publicly prevented action with a pinned `cant` reason, such as flinching,
cannot refresh native stall. The prior duration-one stall expires on that turn's
residual. Native `addVolatile('stall')` start/restart callbacks establish observed
chain counts, capped at the pinned maximum. A native residual transition then
establishes the current duration before exact HP/status/boost restoration. Native
counters are never assigned or imported from an oracle.

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
