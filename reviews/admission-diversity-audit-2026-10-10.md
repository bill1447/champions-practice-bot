# Admission telemetry and expanded coverage — 2026-10-10

## Audit of the two published runs

The original saved traces reconcile with every aggregate decision and branch
count. Every chosen action is in its checkpoint's public selectable menu; every
search has particles and generated branches. Modes are:

| Original run | Search | Forced wait | Fallback | Branches |
| --- | ---: | ---: | ---: | ---: |
| Mirror `994b4fea1a9fe1d50fe5` | 34 | 14 | 0 | 43,198 |
| Synthetic `ad00076b5cdc9a623926` | 52 | 11 | 0 | 55,866 |

The original reports do **not** persist native admission counters. They cannot
directly prove how many proposals were generated, rejected or admitted at runtime.
Those entries remain `not-recorded`; no old report was rewritten.

An independent offline audit rebuilt every saved midgame action checkpoint from
its sanitized observation, cumulative public ledger, fixed public priors and
known own team. It used the production support gate and constructor, then exact
own request/state, public opponent and legal-menu admission checks. It read no
sealed live state or actual opponent team selection.

| Offline reconstruction | Admitted checkpoints | Phase | Native candidates / positive matches |
| --- | ---: | --- | ---: |
| Mirror | 26/26 | 25 move, 1 switch | 71 / 71 |
| Synthetic | 44/44 | 39 move, 5 switch | 127 / 127 |

Eight opening searches per fixture are outside midgame reconstruction. Forced
waits require no state admission. Mirror tried 37 roots; synthetic tried 82.
Both audits produced zero historical RNG witnesses and zero exhaustively
excluded worlds. Positive current candidates do not establish historical
reachability or exhaustive opponent coverage. This offline audit also does not
reproduce the original wall-clock admission deadline.

Audits are in `runs/admission-audit/<original-run-id>/report.json`, with original
and audit source fingerprints recorded separately. The audit source includes
the bounded telemetry and public-boundary fixes described below.

New per-decision admission telemetry records the constructor path/status,
attempted roots, native candidate count, independently positive matches,
admitted particles and bounded rejection reasons. It exports no native state or
private set values. Forced waits explicitly say admission is not required;
opening decisions are separate from present-state construction. Mode, branch
and public-menu reconciliation is automated in the new audit module.

## Regression checks

Human-Mega passes with eight search decisions and zero fallbacks. Native Trace,
Trick Room, protection, terrain source/reactivation, replacements, own Mega,
called-move execution authority, unsupported-counter negative controls and
sealed transitions pass. Public structural target/hidden-disable legality also
passes. The true-world recovery smoke retains all five known-real boundaries
(four witnessed, one unresolved) with zero false exclusions; sampled
conditioning retains its true world too. That five-case smoke is not a diverse
team-corpus soundness measurement.

All 1,525 pytest tests pass; Ruff, native syntax and diff checks pass. The new
native diversity boundary smoke is included in CI. No independent milestone
review, deployment, commit or push was performed.

## Expanded team and policy coverage

The matrix covers balance, rain and sand rosters containing 13 species, each
validated by pinned Champions M-C. Each opponent roster faces attack-first,
seeded mixed commands and a support/switch policy. Own rosters also rotate.
All nine cells retain the existing eight-second decision budget. The fixed
synthetic public catalog is independent of match selection, and policies see
only request-derived command strings. One seed per cell is coverage rather
than a calibrated strength comparison.

The first pass exposed two concrete public-boundary defects:

1. Intimidate emits a bare `boost` marker after its ability identity. The public
   opponent producer incorrectly recorded `boost` as a second ability, causing
   ledger schema rejection. The producer now validates that optional second
   identity against static native ability metadata; Trace's disclosed origin
   remains available. A native opening control verifies that Intimidate alone
   is recorded and the ledger initializes.
2. A charging Electro Shot request supplies only move name/id. Choosing by move
   id still requires a target: pinned `Side.chooseMove` defaults missing target
   metadata to `normal` before resolving the locked target. Public candidate
   generation and structural selection now follow that public-request rule.
   The native charge/continuation control verifies an explicit target and an
   accepted command, without querying private opponent state.

The incomplete discovery pass is preserved under
`runs/diversity-league/5c08d01a5527a554ac95/partial-report.json`. Its first four
games completed and its fifth cell stopped at the Electro Shot rejection.
It is not treated as a completed league report.

The final source-bound matrix `1c6863d86f648698d526` completed all nine games,
with zero failed sealed commands. It generated 138 decisions: 39 searches,
16 forced waits and 83 fallbacks (60.1% of all decisions; 68.0% of action
decisions). Search covered 39/122 action decisions. This broader matrix is not
the same population as the two frozen fixtures, so its fallback rate is not a
like-for-like regression against their zero-fallback measurements.

| Opponent roster | Policy | Own roster | Search | Wait | Fallback |
| --- | --- | --- | ---: | ---: | ---: |
| Balance | Attack-first | Balance | 3 | 3 | 23 |
| Balance | Seeded mixed | Rain | 3 | 3 | 7 |
| Balance | Support/switch | Sand | 2 | 2 | 5 |
| Rain | Attack-first | Rain | 4 | 2 | 5 |
| Rain | Seeded mixed | Sand | 3 | 1 | 6 |
| Rain | Support/switch | Balance | 3 | 1 | 10 |
| Sand | Attack-first | Sand | 13 | 1 | 13 |
| Sand | Seeded mixed | Balance | 6 | 1 | 5 |
| Sand | Support/switch | Rain | 2 | 2 | 9 |

The 13-species preview catalog selected 12 distinct base species into battles;
Rillaboom was present in preview but not selected by these fixed four-member
previews. Policies submitted 60 distinct commands. Future coverage should vary
preview selection as well as roster and policy. These are simple synthetic
command policies, not trained or calibrated opponents.

Explicit native telemetry records 28 admitted present-state checkpoints, 83
rejected checkpoints, 11 opening-path decisions and 16 waits. Construction tried
42 roots, generated 55 native candidates and admitted 51 independently positive
matches/particles before resampling. Historical witnesses and exhaustive
exclusions stayed at zero. All trace/summary/public-choice/admission consistency
checks pass. No own-speed diagnostic transport errors occurred. Search generated
32,790 branches. Aggregate decision p95 was 4.648 seconds, dominated by quick
fallbacks; it must not be read as a search-latency improvement. Search-only p95
was 7.627 seconds, within the eight-second budget.

Fallback causes are 45 unsupported field durations, 21 persistent ledger
unavailability, 9 unsupported protection residual effects, 4 unrepresented Trace
states, 2 unfinished-turn replacement boundaries, 1 own disabled-move request
mismatch and 1 legal-menu mismatch. The 21 ledger fallbacks arise in the same
balance game after the unsupported berry marker, rather than 21 independent
failures. The other eight games retain their ledger throughout.

The final report is `runs/diversity-league/1c6863d86f648698d526/report.json`.
It binds parent commit `1531e5c3e3323bad890d3ccc148bcda7eef2542f` and dirty runtime
source fingerprint
`9833eb8373149c459203999024f5dafd936449d2623e7a83bbc957cc1ee38124`.
Runtime sources stayed unchanged during this measurement. Remaining explicit
gates are retained; broader coverage does not justify relaxing latent-counter,
exact owned-state or private-information checks.

## Follow-up priorities

Public berry effect markers such as `-enditem ... [weaken]` currently invalidate
the ledger after initial evidence was accepted. Preserve that evidence while
adding exact pinned protocol support and negative controls. Ledger invalidation
persists for the rest of a game, amplifying one unsupported marker into many
fallbacks. Also investigate current own move-disabled reconstruction failures
using their saved public checkpoints.

Weather and Tailwind need public duration/source domains and native residual
controls before admission. Pivot replacements require the unresolved native
action queue to be represented; an end-of-turn replacement root cannot substitute
for a mid-turn Parting Shot queue. Sleep and other latent status/activation timers
need dedicated adversarial review before claiming these broader mechanics are
fully reconstructed. Follow those repairs with repeated matrix seeds, further
archetypes, validated external public priors and diverse true-world survival
measurement. The narrow two-fixture result remains valid within its scope.
