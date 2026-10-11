# Present-state production support

Fresh midgame construction currently preserves visible projections but cannot
establish every latent native counter. A matching own request and legal menu
therefore remain necessary checks, not sufficient production admission.

`BeliefDecisionEngine._try_present_public_rebase` now applies
`unsupported_present_mechanics` before creating a hypothetical worker. It
uses only the sanitized observation and never reads a live snapshot, native
counter, opponent private set or historical particle.

The following fresh midgame inputs deliberately use a legal fallback:

- Active weather, unsupported terrain, unsupported pseudo-weather or side conditions:
  `fresh-public-world:unsupported-public-effect-duration`.
- Protection history whose complete ordered success/reset evidence is unavailable:
  `fresh-public-world:unsupported-public-protection-chain`.
- Missing, empty, incomplete or stale execution evidence:
  `fresh-public-world:unsupported-public-protection-history`.
- Missing effect projection:
  `fresh-public-world:unsupported-public-effect-projection`.
- Replacement requests without a current public end-of-turn marker:
  `fresh-public-world:unsupported-public-switch-boundary`.
- Unrepresented current Trace copies or their activation histories:
  `fresh-public-world:unsupported-public-trace-state`.

Protection now has a public lifecycle support path. Ordered channel-visible
move, cant, switch/drag and single-turn success/failure events establish the shared
stall chain, including Quick/Wide Guard. Every earlier completed turn needs a
move-phase completion snapshot. A current replacement window is supported only
after its channel-visible `upkeep` marker, which proves residual processing has
finished. Pivot and other unfinished-turn replacement windows remain unsupported.
One confirmed attempt per actor/turn is supported, including called attempts.
Multiple attempts, missing evidence, actor swaps and unrelated native residual
effects remain unsupported. Side conditions are also conservative:
the current projection cannot establish unknown durations or hazard layers.
None of these reasons proves a hidden world impossible.

Turn-one native openings and exact native forks remain available. Fresh move
states and certified post-residual replacement states can use tactical search.
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
When ordered upkeep markers are available, terrain age counts the residuals
after activation rather than subtracting turn labels. A Surge activation during
a replacement after upkeep starts with zero elapsed residuals. This avoids
premature expiration in later move phases.

The native constructor validates the source against its approved hypothetical
set, restores terrain after switching, then advances the pinned
`fieldEvent('Residual', [])` lifecycle. Pokemon residual callbacks are excluded.
Native expiration rejects the proposal; timers are never assigned directly.
Extension items remain native set hypotheses. Public Terrain Extender inventory
changes are unsupported pending an extension timing domain. Native controls
cover opening and overwrite starts, same-terrain entry without refresh,
reactivation after another terrain, retained extenders, several remaining
durations, expiration and serialization. This is limited terrain support,
not a claim that every source or duration domain has been covered. Weather,
pseudo-weather other than the bounded Trick Room path below, and side effects
remain outstanding.

Ordered public Trace disclosures identify the copied ability and opposing donor.
The supported copy set is the four Surge abilities, inactive Unburden and Pixilate.
Switches and Mega evolution clear current copies. A historical terrain start keeps
its original Trace source even after that source evolves or leaves the field;
native terrain start receives the disclosed Surge effect while retaining the
source's current ability. Current copies use native `setAbility`. Lost-item
Unburden activation and other borrowed abilities remain unsupported. Public Mega
events restore opponent evolution and its disclosed stone, including benched Mega
members. Public returning Mega identities use static native species metadata.

Trick Room uses canonical public starts, toggle ends and subsequent upkeep markers.
Complete evidence establishes zero through four elapsed residuals; unknown starts,
missing boundaries and extension annotations remain unsupported. The constructor
uses native `addPseudoWeather` and field residual operations. Joint terrain and
Trick Room reconstruction activates younger effects later in the same residual
timeline, so restoring one does not over-age the other. Native Persistent sources
are rejected until their extension domain is represented. Expired Trick Room can
leave mixed signed owned speed caches after replacements; only owned members whose
observed cache is negative receive native speed updates under temporary Trick Room.
No speed or duration counter is assigned directly. Native controls cover both
sides, reactivation, source switch, expiration, retained terrain extension, Mega
bench/return and a measured forced-replacement sequence.

A publicly prevented action with a pinned `cant` reason, such as flinching,
cannot refresh native stall. The prior duration-one stall expires on that turn's
residual. Native `addVolatile('stall')` start/restart callbacks establish observed
chain counts, capped at the pinned maximum. A native residual transition then
establishes the current duration before exact HP/status/boost restoration. Native
counters are never assigned or imported from an oracle.

For certified replacement states, the constructor lets the native turn loop
process a residual and pause on the fainted slot's replacement request before
restoring observed current HP/status/field. This establishes the native empty
queue and mid-turn resume state without copying a historical move queue. Exact
request, owned projection and legal-menu checks still apply. The replacement
control verifies that submitting replacements advances to the next turn once
and does not age terrain or protection a second time. Fainted own active flags
are checked after native faint resolution, including a fainted Mega and a
fainted member retained in its slot when no reserve remains.

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
