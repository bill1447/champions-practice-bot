# Independent V2 public-state policy pilot

The first migration slice is implemented and operates independently of native
reconstruction. Production is unchanged. V2 is used only in offline shadow and
actual-play pilot games; it is not yet the live fallback or the main controller.

| Suite | Baseline fallback wins | V2 wins | Complete games | Legal decisions |
| --- | --- | --- | --- | --- |
| Seed indices 0–1 | 10/36 | 26/36 | 72/72 | 692/692 |
| Additional seed indices 2–3 | 12/36 | 28/36 | 72/72 | 682/682 |

Each suite pairs the same native seeds, teams, fixed `1234` selections, opponent
policy and side for fallback and V2 games. Side-swapped games are correlated,
not independent statistical samples. The matchups are balance versus rain,
rain versus sand, and sand versus balance; opponent policies are attack-first,
seeded-mixed and support/switch. Command-selector seed is fixed at 52101.
V2 was not tuned between these two suites. Changed actions naturally consume
different future random streams even when initial seeds are paired.

The baseline is `choose_public_fallback`, not full production search. The
opponent policies are weak synthetic baselines. These results support continuing
the independent-policy approach, not competitive strength or production
promotion. The unfavorable balance/rain matchup remains a strategy target;
this heuristic does not infer opposing speeds, predict responses or calculate
survival. More held-out teams, independent policies, seeds and comparisons with
the full existing bot are required before changing production behavior.

Baseline games also record V2 shadow decisions without changing submissions.
V2 disagrees on 314 and 306 baseline decisions respectively. Across both suites
there are zero illegal actions or ranking deadline exhaustions. Maximum ranking
time is 3.544 ms against a cooperative 100 ms budget; static metadata startup
is excluded. Native reconstruction/search is not called by this policy.

The immutable decision input retains typed public/owned facts and legal choices,
not a raw simulator observation or state. The adapter explicitly discards
opponent private moves, items, abilities, speed and exact HP. A mutation control
injects different private data and verifies identical input and chosen action.
Other focused controls exercise expired deadlines, changing visible targets,
ally damage, redundant Tailwind, numeric moves, Mega, preview, switch and wait.
The full test suite passes 1,617 tests; Ruff and metadata-tool syntax checks pass.
CI independently runs the default 36-game shadow/paired pilot and uploads traces.

Frozen JSON preserves each typed input, authoritative menu, alternatives,
reasons, score margin, ranking coverage, elapsed time, submitted command and
terminal outcome. The exact raw payload is preserved with one decision per
line. No score is described as a probability or certified damage calculation.

Baseline main: `29215b7d2320e93331f2d36acf3f6b6d362be931` (PR #243).
PR #244 passed CI but was not merged when this slice was started.
Runtime source fingerprint:
`c812f5e603cc0dba56d3afe9e479756ba6f8065c1dc1dfc069f8870a404fa3f9`.
Showdown pin: `a5df8274e85b0889bf2a9b3422a08b39732374fc`.
Static metadata fingerprint:
`a3796bc8d5f8b2b052415d81c3dea0b3ae4d4c7bd91d530fa3811be1ae678326`.

Next: freeze this policy and broaden comparative/adversarial evaluation before
a production fallback hook. Persistent revealed evidence, uncertainty calibration,
verified tactical advice and learned policy/value are subsequent capabilities.
