# Offline native frontier generation

The public-first frontier experiment does not justify promotion. It improves
checkpoint coverage on the original fixtures, regresses on the additional seed
and policy suite, and improves neither suite's complete-game ancestry count.
Production search, admission safeguards and the existing guided reference remain
unchanged. The sampled default also remains unchanged.

## Reproduce

With the pinned Showdown build and project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m champions_practice.native_stochastic_audit --generation guided --output runs/native-frontier/guided.json
.\.venv\Scripts\python.exe -m champions_practice.native_stochastic_audit --generation frontier --output runs/native-frontier/frontier.json
.\.venv\Scripts\python.exe scripts/native_frontier_compare.py --baseline runs/native-frontier/guided.json --candidate runs/native-frontier/frontier.json --output runs/native-frontier/comparison.json
```

Repeat both audits with `--oracle-seed-offset 1 --include-mixed-policy` for the
additional validation suite. The offset changes only the isolated reference
battle seed, never tracker inputs. The mixed policy uses independently seeded
command selection. Run `scripts/native_frontier_lineage_probe.py` to reproduce
the two targeted ancestry diagnoses under both generators.

`frontier` preserves guided discovery until the first publicly compatible child,
then rotates between the original pending frontier and independently ordered
parent lanes in 24-call quanta. Only public observations trigger that rotation;
oracle mechanical verdicts never feed generation. `spread` rotates from the
start and `stratified` systematically varies the first three nontrivial chance
decisions before sampling the rest. Both are failed experimental controls, not
recommended alternatives. None changes production chance handling.

Telemetry records native calls per parent, first public match, lane work and
speed-order/damage-history diversity before and after retention. These subsets
are diagnostic counts, not sufficient equivalence classes or calibrated weights.
The full conservative mechanical comparison remains authoritative for the audit.

The paired comparator requires identical runtime fingerprints, simulator pin,
budgets, cases and public observation/command traces. It checks checkpoint and
continuous-ancestry claims against raw validator results. CI runs the frontier
audit and comparison independently after prerequisites, even if another smoke
fails. A safe unresolved result passes; an invariant failure does not.

Controls include a reachable initially unsampled outcome, finite exhaustive
rejection, incomplete enumeration, zero time, privacy canaries, public discovery
parity before the first match, and a one-byte particle budget. Public matches
that cannot be stored remain unresolved with an explicit storage-budget reason.

See `reviews/native-frontier-generation-2026-10-11.md` for frozen results. All
limits and hidden-information boundaries from the Phase 11B document still
apply: finite chance tapes do not certify a single cryptographic seed, future
PRNG streams are samples, and proposal weights are not a posterior. Exhausted
sampling cannot disprove a public possibility. Correctness here is tested
mechanical equivalence, not a claim of bot strength or production fallback rate.
