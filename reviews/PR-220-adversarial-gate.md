# PR #220 — Adversarial review gate: #213–#219

Baseline: main `a2ad475272009983190926d24a069046b9981c59` (merge #219), pinned Showdown `a5df8274e85b0889bf2a9b3422a08b39732374fc`.

## Review authority and limitations

This is a **source-based internal adversarial review and independent-review handoff**, not a completed independent third-party assessment. I inspected the merged source and existing smoke-test assertions through the GitHub repository, but did **not** execute a fresh native simulator run, both frozen leagues, or a separately staffed adversarial review. The #217/#219 CI-success assertions are evidence of their test success, **not** proof of complete timer coverage. No negative-control runtime execution is claimed here.

### Frozen baseline evidence (historical, not current-main results)

Available recorded strength-league reports at commit `1b9b1beaf63ae1fb9066ee15dc4a911bfc588b9f`, before #213–#219, both 8 battles, 8-second decision budget, seed 15601, pinned Showdown:
- `synthetic-spread-uncertainty-v1`: 8 wins / 0 losses, 86 total decisions, 65 tactical searches, 5 fallbacks, 69,327 branches. Fallbacks: 3 exact-own-request ability mismatches, 2 unsupported public phases.
- `current-roster-mirror-v1`: 8 wins / 0 losses, 109 total decisions, 49 tactical searches, 44 fallbacks, 60,102 branches. Fallbacks: 41 missing Indeedee-F public set prior, 3 unsupported public phases.

Both reports are **stale relative to #220**. They cannot prove improvement or regression at `a2ad475`. Current-main paired leagues and full configuration/report artifacts are a required outstanding #220 gate, not presumed passing.

## Severity-ranked findings

### P1 — Timed effects are not duration-faithful in admitted present worlds (confirmed source gap)

**Evidence:** `tools/showdown-search-worker.js` constructs field weather/terrain/pseudo-weather and side conditions with native setters; matching `playerView(...).field` checks effect identities, not native remaining-turn counters. `src/champions_practice/public_effect_timing.py` explicitly returns `duration_proven=False` and is not connected to `build_present_rebase` or native materialization. The #219 probe prints possible mismatches but does not fail admission based on them.

**Impact:** A freshly created full-duration Trick Room/Tailwind/terrain hypothesis may simulate a different future than an expiring live effect. Exact current own request/legal choice equality does not close this multi-turn defect.

**Reproduction/acceptance:** Capture genuine pinned turns with Trick Room at at least two remaining durations and test the same public current projection gate. Require enumerated public-justified timer domain or reject `unsupported-public-effect-duration` before search; test expiration after one and multiple searched turns, roundtrip, overwrite, and relevant abilities/items. Never copy sealed oracle counters into the model. Until fixed, mark this P1 unresolved and block feature claims about accurate multi-turn tactics.

### P1 — Public prior gaps still cause large observed mirror fallback (confirmed historical benchmark; current rate unverified)

**Evidence:** Historical mirror report at `1b9b1be` recorded 41/109 decision fallbacks with `no public set prior matches revealed information for Indeedee-F`. `current_state_proposals.py` constructs priors using revealed move requirements; `belief_worlds.py` rejects candidates whose move list omits an observed move. This is correct fail-closed handling but a major coverage gap; the specific uncovered move and current-main frequency have not been logged/proven in this review.

**Acceptance:** Log non-private missing observed move IDs, preserve uncertainty, add independently public-licensed candidates, rerun same mirror fixture, and show coverage improvement without weakening the public/private boundary.

### P1 investigation — Own Mega ability/identity mismatch unresolved (historical)

**Evidence:** Historical synthetic report recorded 3/86 fallback decisions at `$.request.side.pokemon[2].ability`; no #213–#219 patch here establishes ability lifecycle correctness for active/benched Mega returns. #212 fixed an earlier identity barrier, but did not resolve this proof obligation.

**Acceptance:** Show actual versus expected OWN ability and native Mega lifecycle for Mega Gardevoir/Metagross including switch out/in and bench; require exact owned request and current legal moves, no guessed ability mutation.

### P2 — Timing helper is evidence, not a duration-domain engine (source confirmed)

**Evidence:** `public_pseudo_weather_timing` only captures `move:<id>` `-fieldstart/-fieldend` from retained mechanics records, and constructs `activation_age_turns` by subtracting recorded start from current turn. It explicitly does not validate contiguous observations, detect every reset source, or infer the native duration domain. No claim that all modifier identities, terrains, weather, and side conditions are covered is supported by tests.

**Acceptance:** Table-drive canonical actual producer events, duplicate repeated last-turn deltas, missing turns, end/restart in same turn, Trick Room/terrain/weather/Tailwind, public extension evidence. Keep unknown as unknown.

### P2 — Native status and bench PP regressions require negative controls (coverage gap, not confirmed bug)

**Evidence:** #214 removed `setStatus(..., true)` immunity bypass. #215 added owned PP inventory and a schema validator. Existing green CI demonstrates tested behaviors only. No executed negative case in this review shows immunity incompatibility rejected on both sides, nor a depleted benched move restored after switch and kept depleted after native fork.

**Acceptance:** Add pinned negative controls for immune status candidate and benched PP=0 with switch-back search; assert no illegal world admitted. Extend schema tests for omitted, duplicate, out-of-bounds and mismatched PP.

## Invariants and release gate

- Pinned Showdown > exact tactical search > public reachability evidence > strategy priors.
- Do not reconstruct historical RNG ancestry as the basis for current inference.
- No sealed session, opponent private set, or native oracle counter may enter the proposal builder.
- Own-side exact request, active state, PP, abilities and legal-choice equality remain hard gates.
- Sampled RNG miss and missing prior remain **unresolved**, never evidence of logical impossibility.
- **#220 is NOT an all-clear.** P1 issues above remain open; implement correctness remediations before new feature work. #230 reviews #221–#229 and carries forward open findings.

## Review completion checklist

- [x] Inspect merged source for native timer setter path and public timer helper.
- [x] Compare historical frozen report counts for the two required fixtures.
- [x] Distinguish source-confirmed findings from unevaluated hypotheses.
- [ ] Run both frozen fixtures at baseline `a2ad475` with identical seed/config, archive full reports.
- [ ] Run targeted pinned negative controls for expired timers, status immunities, bench PP, Mega lifecycle.
- [ ] Obtain separately authored independent adversarial review and attach objections/reproductions.
