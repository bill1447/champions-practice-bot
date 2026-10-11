# Phase 11B: continuous native state with unknown RNG

This is an offline architecture experiment. Known teams and submitted commands
are inputs; the actual battle seed, PRNG state and serialized oracle state are
not. Production search, fresh-state admission and fallbacks are unchanged.

## Run

Build the pinned Showdown checkout with the normal project setup, then run:

```powershell
.\.venv\Scripts\python.exe -m champions_practice.native_stochastic_audit --output runs/native-stochastic/report.json
```

Defaults are 96 sampled branches per checkpoint, a cooperative 600 ms budget,
12 retained particles and 2 MiB of serialized particle storage. CLI bounds are
512 samples and 5,000 ms. The transport has an eight-second timeout. The deadline
is checked between native branches, not inside one branch; this is not a hard
process memory limit. Worker RSS/heap and Python traced allocations are reported
separately. Python memory includes the accumulated audit report; it is not total
process RSS.

The bounded follow-up uses the same call/time/storage caps:

```powershell
.\.venv\Scripts\python.exe -m champions_practice.native_stochastic_audit --generation guided --output runs/native-stochastic/guided-report.json
```

In sampled mode, a call proposes a complete random tape. In guided mode, a call
evaluates a finite tape prefix, so it may stop at another random decision without
completing a branch. The report distinguishes incomplete prefixes, completed
branches and public-prefix pruning. Comparing the two is a bounded generator
comparison, not a comparison of equal numbers of completed stochastic outcomes.

Guided mode starts from distinct current mechanical parent classes, enumerates
finite decision prefixes in independent deterministic option order, and checks
already emitted sanitized public mechanics events at each random call. A prefix
contradiction is rejected only when the partial ledger has the same turn as the
target ledger. It never constrains an earlier turn against a later ledger. Final
particles still require the entire public signature and own request to match.
There are additional caps of 4,096 pending paths and 128 decisions per prefix;
these bounds remain unresolved. Exhausting a guided advance never grants global
disproof authority. Equivalent parent PRNG streams are collapsed only for this
finite-tape exploration, not interpreted as an inferred actual stream.

CI runs the complete audit independently after test prerequisites succeed, even
when another smoke fails. Reports, including failure diagnostics, go under
`runs/` and are uploaded by the existing artifact step. A safe unresolved result
does not fail CI; violated privacy, observation, menu, native replay or future
continuation invariants do.

## Capability boundary and ancestry

`native_stochastic_tracker.py` launches `tools/native-stochastic-worker.js`.
Its operation allowlist has no session API or inbound native-state operation.
The Python API has no seed/state parameter. The worker also rejects privileged
keys recursively, including in nested public-view objects. Five transport
canaries exercise these rejections. These are capability boundaries, not an OS
security sandbox against a malicious process with filesystem access.

Fixture genders are made explicit using static Dex data before either battle is
initialized. Twelve opening hypotheses use independently generated seeds. Every
retained child is produced by executing the known commands through the pinned
native simulator from its retained parent. Root, lineage and depth identify
ancestry; no HP, counters, queues, status or item patches repair a child. A
failed transition freezes the last hypotheses as stale, and stale hypotheses
cannot count as current witnesses. Catch-up is not implemented.

The audit driver and two validator processes may inspect the oracle. They send
the tracker only known fixture inputs, commands and sanitized p1 observations.
Their state comparisons, chance tapes, fingerprints and verdicts never feed
back into branch generation or retention. Outbound tracker hypotheses are
inspected by the validator. The separate privileged chance validator checks
ordinary native execution against traced execution and tape replay at every
reference transition, including transitions after tracker coverage is lost.
That checker also enables public-prefix conditioning on the actual oracle tape
and asserts it does not prune that reachable trajectory.

## What a stochastic history means here

The experimental resolver samples valid inputs to native `PRNG.random` and
`randomChance`. It advances the hypothesis's independently initialized PRNG by
one native draw per intercepted call. Unrecognized low-level RNG access or an
unsupported finite domain remains unresolved. The production resolver keeps
its existing seed-materialization behavior; the extra chance options are only
used by the offline executables.

**A finite chance tape is not proof that one cryptographic seed generates the
entire tape.** This experiment represents native mechanical trajectories under
valid finite chance inputs, an overapproximation of seeded trajectories. It
does not establish a calibrated posterior over seeds or certify reachability
from one seed. That limitation remains an architecture gate, not something to
hide behind a matching public view.

The stored hypothesis PRNG is a sampled future, not an inferred actual future.
Validation removes PRNG and protocol/log bookkeeping, retaining the remaining
native state, including speed order, damage history, queues and counters. This
is a conservative comparison, not a proven minimal equivalence relation: some
mismatches may prove irrelevant to a particular continuation. Such mismatches
are reported unresolved rather than called defects or contradictions.

For current mechanical witnesses, the validator tests next commands with two
coupled, independently chosen future seeds. This checks continuation parity;
it does not predict the real next roll or prove parity for every possible future.

## Outcomes and controls

| Outcome | Authority |
| --- | --- |
| Witnessed | At least one retained particle matches public observations, the own legal menu and the conservative native mechanical projection. |
| Unresolved | Sampling, unsupported randomness, missing mechanical coverage, staleness or a resource bound prevents establishing a witness. |
| Disproved | Only the finite control exhausts a finite possibility tree without a public match, scoped to one retained parent and finite chance inputs. |

The tracker calls a public match `public-witness`; only the isolated validator
can establish a mechanical witness. Sampled misses never become disproof.
Absence from a bounded particle set cannot exclude the actual battle history.

The positive control deliberately samples a Will-O-Wisp miss while the oracle
realizes a reachable burn. It must report unresolved. A separate finite control
then finds a native burn witness with matching mechanics and different PRNG
serialization. An all-Protect negative control exhausts its finite tree and
disproves that burn observation only within its stated scope. A one-node budget
control must remain unresolved.

## Evidence and next experiment

The full report contains every checkpoint, including openings, forced switches,
stale checkpoints and terminal states. Ten reference games span mirror,
balance, rain and sand teams with attack-first and support/switch policies,
plus scripted burn/bench/return and simultaneous pivot cases. There is one
oracle seed per matrix fixture; this is not a broad strength benchmark.

The report records all public-matching proposal fingerprints before retention.
If the oracle fingerprint was proposed but discarded, the first loss is
selection loss. If not, it is an unrepresented mechanical history; no public
match is a public-conditioning sampling miss. These diagnostics are oracle-only.

Every reference game records a fingerprint of its public observation/command
sequence to verify strategies faced identical games. Pointwise mechanical
witnesses, matching terminal states, and an unbroken mechanically matching
ancestry chain are reported separately. A terminal witness after an earlier
lineage loss does not count as continuous maintenance. Ancestry-chain validation
is audit-only and never influences tracker retention.

See `reviews/continuous-native-stochastic-maintenance-2026-10-11.md` for the
measured results and the bounded follow-up acceptance criteria. Do not add
hidden-team/action inference, production admission or new fresh-constructor
mechanic support on the strength of this experiment.
