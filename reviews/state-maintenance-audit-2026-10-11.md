# State maintenance architecture audit

The primary midgame dependency is deliberate, not an observed particle collapse.
Since #197, `observe_public_turn` drops all particles at turn two and later, and
`choose_ai_action` discards them again before fresh construction. Native history
conditioning is retained as offline/legacy machinery. Thus repairing an old
conditioning failure cannot improve current production coverage by itself.

The #196 result was 17/207 searches and 181/207 fallbacks. Reverting #197 without
new evidence would restore a previously ineffective path. The fresh-world support
contract must remain closed while alternatives are evaluated.

## New experiment

`python -m champions_practice.state_maintenance_audit` runs four passive shadow
cells, eight decisions each, with an eight-second conditioning budget. The shadow
initializes native hypotheses independently from the same sanitized opening,
owned team and declared public prior catalog. It observes only public checkpoints
and the bot's committed action. It never receives the real opponent command,
live native state, real RNG seed or an oracle particle. The fixture driver alone
selects opponent commands. No shadow result influences the production action.

The bounded fixture has two publicly possible Dragonite item sets. Other cells
use the shipped balance and mirror pools. These are finite prior catalogs, not
exhaustive opponent coverage or arbitrary import tests.

| Fixture / policy / seed | Production search / fallback / wait | Actionable decisions | Shadow current public/menu matches |
| --- | --- | --- | --- |
| Bounded / attack-first / 24101 | 3 / 2 / 3 | 5 | 3 |
| Bounded / seeded-mixed / 24102 | 6 / 0 / 2 | 6 | 3 |
| Balance / support-switch / 24103 | 1 / 4 / 3 | 5 | 3 |
| Mirror / attack-first / 7 | 1 / 5 / 2 | 6 | 2 |

Total: 32 decisions, 22 actionable, 11 production searches and 11 fallbacks.
The passive shadow has 11 current actionable checkpoints. Four overlap production
fallbacks; four production searches occur after the shadow has become unresolved.
This measures complementary coverage, not stronger play or a replacement search
rate. No shadow tactical search is run. A current public/menu match alone is not
a claim of complete latent mechanical equivalence.

All four primary shadows stop advancing at their first unresolved transition.
Last-good particles are retained for diagnosis, never counted as current coverage
at later decisions. No historical catch-up or fresh reset masks that failure.

## Confirmed structural loss: queued commands

At the bounded attack-first cell's turn-two switch pause, the previous positive
witness batch contained 24 particles. Each remaining set world had six distinct
queued Incineroar commands, including Parting Shot and Darkest Lariat with
different targets. Four-particle resampling retained only one distinct queued
command per set world. After the owned pivot replacement, the public channel
revealed the opponent's Parting Shot. The retained batch could not produce a
complete posterior; both worlds remained unresolved.

An independent, bounded probe of the previous **unpruned** batch witnessed that
same next public checkpoint for both remaining set worlds. It used ordinary
public-only conditioning with fresh hypothetical RNG samples, not the actual
opponent command or actual RNG. This probe did not advance the primary shadow.

The balance support-switch cell exhibited the same structural problem: the
18-particle positive batch had nine queued alternatives per remaining world;
pruning retained two per world. The primary continuation witnessed only part of
the set uncertainty. Probing the unpruned batch witnessed both remaining worlds.

This demonstrates a recoverable loss of discrete pending-command alternatives.
It does not prove that every public-compatible history was enumerated, that
retaining every RNG sample is practical, or that a larger global particle cap
would solve state maintenance. Search-ready histories need to distinguish team
uncertainty, queued command uncertainty and stochastic history.

## Remaining failures and limits

The bounded mixed-policy cell stalls on its turn-three transition with no complete
witness. Public opponent commands are incomplete there; observed boosts, fainting
and event histories differ among proposed continuations. The mirror cell stalls
at turn two despite complete public opponent command evidence: HP and secondary
effect histories fail to match within bounded probing. These are unresolved
coverage failures, not proofs that the real battle is impossible. They require
separate deterministic reproductions before attributing them to specific bugs.

Historical ancestry cannot replace the fresh contract without its own admission
argument. Positive native history witnesses preserve mechanics from a genuine
hypothetical origin, but bounded sampling can still omit possible worlds and
histories. Extend true-world survival controls across pivots and queued actions,
including public-equivalent hypotheses with different later outcomes.

## Work order and playable milestone

1. Prototype queue-aware witness retention **offline**. Preserve each distinct
   pending command and target within each remaining set world. Bound stochastic
   samples separately. If the required discrete coverage cannot fit the budget,
   report unresolved instead of silently dropping that coverage.
2. Replay both frozen pivot failures and require complete public-only positive
   witnesses for all remaining set worlds. Add native true-world survival and
   next-turn outcome controls, including switch waits, simultaneous pivots,
   fainted replacements and newly revealed queued moves.
3. Diagnose the mixed-policy and mirror stochastic failures independently. A
   persistent path needs bounded catch-up or explicit unresolved handling; older
   states must never be used as though current.
4. Evaluate a hybrid only after those gates: maintain validated histories while
   they advance; use default-deny fresh reconstruction for supported recovery.
   Unburden and consumed-item reconstruction remain the next fresh-path domains.
5. Proposed playable milestone: two explicitly supported team compositions,
   three opponent policies and two seeds each, **12 complete local games**.
   Target at least 90% tactical search among actionable decisions, zero illegal
   actions and zero observed unsafe admissions, with native lifecycle/outcome
   controls and no measured false true-world exclusions. Count every fallback
   reason and pause separately. This is an engineering target, not achieved
   performance or a strength claim.

Learned priors, broad import and strength claims remain behind correctness and
complete-game coverage gates. Preserve publicly possible opponent uncertainty.

## Validation and identity

- Parent commit: `d0d9ec26d28e44a68f1b1179394a78aadba235ba`.
- Pinned Showdown: `a5df8274e85b0889bf2a9b3422a08b39732374fc`.
- Executed runtime source SHA-256:
  `c6cf88850d4a6faaacf9e0865003677930f3ce4a3719fbc4acdc14dd87548c2e`.
- New offline audit module and six tests; full pytest **1,575 passed**.
- Ruff passes. Report: `runs/state-maintenance-audit/report.json` (local ignored
  artifact containing sanitized failure checkpoints and hypothetical diagnostics).
- Production decisions, gates, simulator and worker authority were unchanged.
- Validation was completed before the audit commit and push. No deployment or
  merge was performed.
