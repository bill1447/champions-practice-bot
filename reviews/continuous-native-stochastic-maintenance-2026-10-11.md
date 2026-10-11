# Phase 11B: unknown RNG and bounded public-guided generation

The random-tape baseline does not maintain mechanically matching histories
through any of ten complete reference games. A bounded public-event guided
generator improves checkpoint coverage and maintains matching native ancestry
through two games. This is partial recovery evidence, not a production admission
or strength result. Keep the experiment offline.

## Scope and reproducibility

The isolated branch starts at merged #242 (`4223a09`). Production selectors,
search, fallback behavior and the closed fresh-state support contract are
unchanged. No new fresh reconstruction support is introduced. Older uncommitted
work in the original checkout is outside this PR.

Showdown is pinned to `a5df8274e85b0889bf2a9b3422a08b39732374fc`. All three
reports bind runtime source contents to SHA-256
`c9398a83f8f686d9d0d66a5cdbddbc5fbf1e3370325db05ccc547073ce9159d7`.
They were generated before committing, so their Git commit identifies the base
and their runtime content fingerprint identifies the implementation actually
tested. Generated reports/review documents are excluded from that fingerprint.

Each run completes ten reference games: mirror, balance, rain and sand against
balance under attack-first and support/switch policies, plus burn/bench/return
and simultaneous-pivot scripts. One oracle seed per matrix fixture is tested.
All three runs have identical public observation/command trace fingerprints
for each reference game. This establishes a paired generator comparison; it
does not establish generalization across seeds, teams or policies.

Full checkpoint reports:

- `continuous-native-stochastic-small-2026-10-11.json`
- `continuous-native-stochastic-default-2026-10-11.json`
- `continuous-native-stochastic-guided-2026-10-11.json`

Run commands and capability details are in
`docs/continuous-native-stochastic-maintenance.md`.

## Correctness and coverage

| Generator / call cap / time budget | Mechanical witnesses | Unresolved | Terminal witnesses | Continuous matching lineages through terminal |
| --- | --- | --- | --- | --- |
| Sampled / 48 / 250 ms | 29/196 (14.8%) | 167/196 (85.2%) | 0/10 | 0/10 |
| Sampled / 96 / 600 ms | 35/196 (17.9%) | 161/196 (82.1%) | 0/10 | 0/10 |
| Public guided / 96 / 600 ms | 68/196 (34.7%) | 128/196 (65.3%) | 3/10 | 2/10 |

The denominator includes ten openings, terminal states, forced-switch phases
and stale checkpoints. Excluding openings, default sampling witnesses 25/186
(13.4%) and guided generation witnesses 58/186 (31.2%). These are offline state
coverage percentages, **not production fallback percentages**. Production has
not adopted this tracker and its fallback percentage was not remeasured.

The guided continuous cases are mirror/support-switch and rain/support-switch.
Burn/bench/return ends with a mechanically matching terminal state after losing
matching ancestry at checkpoint 2; it does not count as a maintained complete
game. A current witness after a gap cannot restore the continuous-lineage count.

All runs pass:

- Five privileged-input canary rejections at the tracker transport boundary.
- A deliberately unsampled, reachable Will-O-Wisp burn remains unresolved.
- Finite exploration finds that burn with native mechanical parity and different
  PRNG serialization; guided generation also retains a mechanical burn witness.
- A finite all-Protect negative control exhausts 15 nodes / 8 leaves and
  disproves the burn only for one retained parent and finite chance inputs.
- One-node finite and zero-time sampled controls remain unresolved.
- Every retained current particle matches public observations and the own
  authoritative legal menu.
- Each of 186 reference transitions passes isolated ordinary execution versus
  native chance trace/replay parity. Public-prefix conditioning never rejects
  the actual oracle tape in these checks. Oracle tapes/states/verdicts do not
  flow back into the tracker.

The default run also passes 70 coupled hypothetical next-boundary comparisons;
guided generation passes 130. These use independent future seeds and do not
predict the actual next roll. Zero sampled misses receive disproof authority.
These observations do not prove exhaustive history coverage or safety for
untested mechanics.

## First losses identify the next bottleneck

At 96 sampled calls, five games first lose public compatibility and five first
lose mechanical coverage despite public matches. None of those first losses,
or any measured retention operation, drops a class because of the particle or
serialized-state cap. Increasing retention capacity is not the demonstrated
remedy.

Guided generation rejects already emitted public-event contradictions while
enumerating chance prefixes. It improves coverage but still has eight first
mechanical/public coverage losses:

| Fixture / policy | First checkpoint | Diagnosis |
| --- | --- | --- |
| Mirror / attack | 1 | No completed public-compatible branch under the call cap |
| Balance / attack | 4 | Public matches, missing native speed-order class |
| Balance / support | 1 | Public matches, different native damage history |
| Rain / attack | 3 | Public matches, different native damage history |
| Sand / attack | 1 | No completed public-compatible branch under the call cap |
| Sand / support | 1 | No completed public-compatible branch under the call cap |
| Burn/bench/return | 2 | Public matches, missing native speed-order class |
| Pivot queue | 3 | Public matches, missing native speed-order class |

The listed differences are conservative native projection mismatches, not
proven gameplay defects. The full reports preserve exact mismatch paths. Speed
order participates in native handler ordering and must not be removed simply
to inflate coverage. Other fields also require continuation evidence before
being collapsed. An absence from sampled/generated proposals is unresolved,
never proof that the actual possibility is impossible.

## Resources

Default sampling generates 5,184 complete proposals; guided generation executes
11,762 native prefix/complete calls and rejects 2,108 public prefixes. Equal
caps therefore do not mean equal numbers of completed outcomes. The guided run
performs more total work because it stays public-current longer.

Both retain at most 12 particles and 349,345 serialized bytes in the measured
checkpoints. Default maximum processing is about 335 ms and guided about 607 ms.
Guided generation records five cooperative deadline exhaustions; default
records none. A branch already executing can overrun 600 ms, so this is not a
hard 600 ms deadline.

Checkpoint maximum tracker RSS is about 283 MiB in each run. The 2 MiB particle cap
does not bound the simulator, Dex cache or total process memory. Worker RSS/heap,
Python traced allocations, processing time, branch/particle counts and deadline
status appear at every checkpoint. Python traced peak is about 14 MiB and
includes report accumulation. Memory and timing are environment-specific.

## Architecture gate and next bounded experiment

The experiment executes valid finite chance inputs through native mechanics.
It **does not certify that one cryptographic seed realizes an entire retained
tape**, and it does not provide calibrated posterior weights. Its independent
stored PRNG is a hypothetical future, not the actual stream. Current mechanical
equivalence is assessed separately from PRNG serialization, using a conservative
projection rather than a proven minimal equivalence relation.

Consequently the milestone establishes some native lifecycle/conditioning
correctness and improved finite-tape coverage. It does not satisfy a general
complete-battle maintenance or production promotion gate. Hidden teams/actions,
learned priors, strength claims and fresh-constructor expansion remain deferred.

The next experiment should diversify early unresolved chance prefixes rather
than spending the entire depth-first budget within one speed-order subtree.
Compare a fair/stratified frontier against both current generators on the same
ten trace fingerprints, call/time/storage caps and continuous-lineage metric.
Do not patch a speed-order counter or damage history into a child. Preserve
native alternatives and use public observations to prune them.

Required evidence before broadening scope:

1. Preserve the reachable-but-unsampled and deadline controls; no false global
   exclusions and no privileged oracle feedback.
2. Improve continuous lineage survival, not just terminal matches or projections.
3. Inspect speed-order and damage-history diversity before/after generation and
   retention, with future continuation checks for any proposed equivalence.
4. Report resource overruns and regressions in the existing successful games.
5. Replicate across additional oracle seeds and policy/team combinations before
   treating an improvement as general. Resolve seeded-tape realizability and
   weighting explicitly before a production belief distribution is claimed.

## Validation

1,606 unit tests pass, including RNG/mechanics separation, privileged Python
input rejection, conservative counter/queue distinctions and ancestry-gap
regressions. Ruff, JavaScript syntax and diff whitespace checks pass. Existing
finite-transition, finite-conditioning, persistent-session and queue-retention
native smokes validate the unchanged production resolver path. Both experimental
complete-game audits are mandatory independent CI steps after prerequisites
succeed; safe unresolved coverage does not turn into a false CI success claim
about architecture readiness.
