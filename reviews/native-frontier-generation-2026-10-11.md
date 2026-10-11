# Phase 11B follow-up: frontier diversity

Decision: retain the guided reference and keep all alternatives offline. The
public-first candidate fails to generalize and does not improve full-battle
mechanical ancestry. This experiment is complete; the replacement architecture
is not ready for production.

## Paired results

| Suite / generator | Mechanical witnesses | Unresolved | Continuous checkpoints | Continuous games | Terminal witnesses |
| --- | --- | --- | --- | --- | --- |
| Original / guided | 68/196 | 65.3% | 38/196 | 2/10 | 3/10 |
| Original / public-first frontier | 86/196 | 56.1% | 40/196 | 2/10 | 3/10 |
| Additional seed + mixed policy / guided | 106/255 | 58.4% | 51/255 | 1/14 | 6/14 |
| Additional seed + mixed policy / frontier | 94/255 | 63.1% | 51/255 | 1/14 | 5/14 |

On the original suite, early stratification gives 35/196 witnesses and cold
lane rotation gives 29/196; neither preserves continuous ancestry in any game.
The candidate was developed on the original ten games. The additional fourteen
change oracle seeds and add a seeded mixed policy to attack-first and
support/switch policies; they are a limited validation suite, not statistical
proof of generalization. Four team compositions and two scripted lifecycle
cases are exercised. Each reference battle reaches terminal even if tracking
fails. Each paired run uses identical public observations and commands.

Terminal/current-state witnesses can recover through a different retained
history after losing a mechanically matching ancestry. They must not be counted
as continuously correct battles. Production fallback percentage is not measured
by this offline experiment; unresolved percentages above are not fallback rates.

## First ancestry losses

The separate lineage probe uses the same validation traces for rain/mixed and
pivot-queue, completes all four reference games, and does not feed oracle
verdicts to either generator. Guided generation assigns zero native calls to
the previously mechanically matching parent at rain checkpoint 4 and pivot
checkpoint 3. Parent starvation is directly demonstrated in those cases.

Frontier generation assigns 24 calls to the matching parent at those same
checkpoints, but still loses continuously matching ancestry. A current-state
witness remains, descended from a different parent. Work distribution therefore
does not establish sufficient continuation coverage. These observations do not
distinguish bounded branch-generation failure from discarded equivalent-state
provenance; deduplication is a hypothesis requiring another test, not a proven
defect. No particle-selection cap losses are recorded in the six main runs.

Next: instrument generated children before deduplication and retention, record
all predecessor provenance for equivalent children, and compare parent-balanced
discovery against guided generation on both fixed suites. Preserve native speed
order and damage history until future-continuation evidence justifies removing
them. Do not add fresh reconstruction patches or promote based on pointwise
coverage. Complete-game ancestry is the primary objective.

## Correctness and resources

All six main audits pass: 1,226 isolated reference transitions reproduce native
state under their actual chance tapes, and 802 coupled future comparisons pass.
There are zero observed false exclusions. All privacy, unsampled reachable,
finite negative, incomplete-budget, public-discovery-parity and storage-budget
controls pass. These establish the tested invariants, not exhaustive coverage
of stochastic histories. Unit tests: 1,616 passed. Ruff and JavaScript syntax
checks pass, as do native finite-transition, finite-conditioning, session and
queue-retention smokes.

Every main checkpoint has a 96-call / cooperative 600 ms budget, 12 retained
particles and 2 MiB serialized storage. Original guided/frontier runs report
5/1 deadline exhaustions; both validation runs report zero. Maximum processing
time across six runs is 608.6 ms; deadlines are checked between native calls.
Maximum worker RSS is 300,695,552 bytes (286.8 MiB); maximum serialized storage
is 383,689 bytes. RSS is observed, not hard limited. Raw files retain per-checkpoint
calls, prefixes, particle counts, bytes, timing and memory measurements.

All six reports have runtime fingerprint
`e82d996972a113d169c3799155dde64bab07dceec097a883b626c804154cfcb4`,
based on main `29215b7d2320e93331f2d36acf3f6b6d362be931`, with experimental
changes present. Simulator pin:
`a5df8274e85b0889bf2a9b3422a08b39732374fc`.
The full reports are preserved as `native-frontier-*-2026-10-11.json`, with
checkpoint objects compacted only for readable diffs. Two paired comparisons
and the lineage probe accompany them. The runtime fingerprint covers native
worker and Python runtime sources, not documentation or analysis scripts.

Current mechanics and actual PRNG identity remain separate. Finite-tape
realizability by one cryptographic seed, calibrated uncertainty weights,
hidden-team/action inference and production promotion remain open.
