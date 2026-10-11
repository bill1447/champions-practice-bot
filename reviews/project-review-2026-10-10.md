# Project review — October 10, 2026

Reviewed checkout: `ddfea3a84221ebf40a3a4f81625f98509ca36aea` (merge #236).
Pinned Showdown: `a5df8274e85b0889bf2a9b3422a08b39732374fc`.

## Assessment

This is a substantial, playable local research prototype. The battle engine, Python/Node bridge, sealed decision workflow, public-information boundaries, dataset tooling, and regression infrastructure are implemented. The next milestone should be mechanically faithful decision-state reconstruction and measured coverage, followed by stronger opponents and a broader practice experience.

It is not yet established as a reliable competitive training opponent. Native simulation is exact for its input state, but accepted reconstructed states can lose mechanics that affect subsequent turns. Passing tests and beating the current baseline do not resolve that distinction.

## Scope and verification

Inspected the architecture and main runtime paths: demo HTTP/session handling; controller admission, decision, timeout and fallback paths; current-state reconstruction; native worker materialization and projections; tactical search; benchmark identity/reporting; corpus and semantic training tooling; CI; roadmap and earlier review evidence. This is a project-level review of critical paths, not a claim of exhaustive line-by-line proof or an independently staffed milestone review. No production implementation was changed.

Executed:

- Full unit suite: **1,383 passed in 3.23 seconds** outside the sandbox. Initial sandbox collection hung in the Windows socket pair created by `poke_env` import; a stack dump identified the cause. This was an environment limitation, not a test failure.
- Ruff: **all checks passed** for `src` and `tests`.
- Node syntax check: **passed** for `tools/showdown-search-worker.js`.
- Runtime provenance gate: **passed** for the pinned Showdown build.
- Native session smoke: **passed** independent preview choices, sanitized views and live-session/exact-fork parity.
- Native reconstruction negative control: **reproduced an admitted state losing the repeat-Protect counter and changing terrain duration**, detailed below. Saved script: `reviews/native-reconstruction-probe.py`; output: `reviews/native-reconstruction-evidence.json`. Run with `.venv/Scripts/python.exe reviews/native-reconstruction-probe.py`. Native reference state is an offline oracle; only its sanitized view enters materialization.

The entire CI smoke matrix and new full strength leagues were not executed in this review. Benchmark figures below come from existing immutable local reports at the reviewed commit, not newly run games. External replay/model stores were not audited for their current size or model quality.

## Current measured behavior

Both local reports bind this exact commit, Showdown pin, seed 15601, eight games and an eight-second decision budget.

| Fixture | Results | Search | Fallback | Forced wait | Simulated branches | Mean / p95 decision time |
|---|---:|---:|---:|---:|---:|---:|
| Current roster mirror | 7 wins / 1 loss | 32 / 51 | 5 / 51 | 14 / 51 | 42,059 | 2.93 / 7.78 seconds |
| Synthetic spread uncertainty | 6 wins / 2 losses | 67 / 92 | 13 / 92 | 12 / 92 | 78,427 | 2.84 / 7.77 seconds |

Sources: `runs/strength-league/4e126a3f7833d0db066b/report.json` and `runs/strength-league/74ebf18b86b33046d259/report.json`.

Fallback rates are 9.8% and 14.1% of all decisions; excluding forced waits, 13.5% and 16.3%. Mirror fallback reasons: three forced-switch phases, one exact own request ability mismatch, one own active-state mismatch. Synthetic fallback reasons: ten forced-switch phases and three own benched Mega restoration failures. Strategy plans were attached on only one and four decisions respectively; this measures reported plan attachment, not whether every other action lacked strategic reasoning.

These are narrow fixtures against `attacking-mega-legal-v1`. Eight games per fixture are useful regression evidence but do not establish ladder strength. The reported win-rate confidence intervals are broad: approximately 53–98% and 41–93%.

## Findings in priority order

### P1 — Reconstruction drops repeat-Protect state and admission accepts it

**Runtime reproduced.** `ownPokemon()` in `tools/showdown-search-worker.js:750` exports HP, PP, stats and abilities but omits the native `stall` volatile. `materializePresentHypotheses()` restores present observations on a fresh opening without restoring this publicly evidenced repeat history. Python admission in `src/champions_practice/present_rebase.py:67` accepts equal projections and legal menus without checking this mechanic.

Reproduction: create pinned mirror teams with `team 2135` on both sides; resolve turn one with `move protect, move followme` on both sides; obtain the p2 public view; materialize it from a fresh identical opening. At turn two the native reference Sneasler has `stall.counter = 3`; the accepted candidate has no `stall` volatile. Native legal menus are equal and `_positive_mechanics_rejection()` returns `None`.

Pinned `data/conditions.ts:439` uses that counter to make a consecutive protection attempt succeed with probability 1/3. Omitting the counter represents a fresh attempt. The controller's existing repeat-Protect mitigation reads `_protect_chain_slots()` from reconstructed worlds (`belief_controller.py:3114`), so the missing counter also defeats that trigger.

**Required fix:** retain public protection-attempt/success and switch/reset evidence, derive the supported current chain state, and construct it through pinned mechanics. Reject unsupported chain domains before tactical search. Add native negative controls for consecutive attempts, failed attempts, interruption/reset, switch-out/back, opponent uncertainty and serialization. Use sealed native counters only as offline comparison oracles.

### P1 — Timed effects remain identity-matched without remaining-duration authority

**Source confirmed, terrain mismatch runtime reproduced; carried forward from #220.** `tools/showdown-search-worker.js:2294` reconciles weather, terrain, pseudo-weather and side conditions through native setters. Existing opening effects can retain opening counters; newly added effects receive setter-created counters. Admission compares visible identities, not justified remaining-duration domains. `public_effect_timing.py:23` explicitly reports `duration_proven=False` and its evidence helper is not connected to production admission. In the same native turn-two probe, actual Psychic Terrain has remaining duration 4 while the admitted reconstructed world has duration 5, despite identical legal menus and successful Python admission.

An expiring Trick Room, Tailwind or terrain can therefore be represented as lasting longer than public history permits. This can affect even the next turn's residual effects and board evaluation as well as continuation search. Exact current request equality does not prove expiration behavior.

**Required fix:** connect public timing evidence to explicit duration hypotheses, including resets and extensions. Where supported native construction cannot represent the domain, return `unsupported-public-effect-duration`. Require native expiration/roundtrip negative controls. This review reproduced a counter mismatch but did not run the complete expiration, reset and extension matrix.

### P2 — Forced-switch and own Mega/ability reconstruction still interrupt search

**Current-commit benchmark confirmed.** `present_rebase.py:224` supports only move phase, so forced replacement reliably falls back. The native own benched Mega restoration and exact request/active checks also retain the failures enumerated above. #235/#236 improved restoration and diagnostic labels but the reports show they did not eliminate these cases.

Failing closed is appropriate; these are coverage deficiencies, not grounds to relax admission. The fallback policy (`belief_controller.py:614`) ranks a legal command string with coarse attack/defense and friendly-target checks. It does not evaluate board quality or replacement synergy.

**Required fix:** freeze each remaining rejection into a native public-input fixture; establish exact own Mega, ability, faint and active-position lifecycle behavior; then support native forced-switch roots. Track search coverage separately for move and switch phases. Re-run paired fixtures with unchanged configuration after each correction.

### P2 — Strength report caching does not bind uncommitted implementation changes

**Source confirmed.** `_git_commit()` at `strength_league.py:152` records HEAD but does not verify cleanliness. `run_league()` at line 767 returns a cached report for that commit/configuration. Editing tracked code without committing can return a previously generated report; `refresh=True` can instead generate changed-code results still labeled with the unchanged commit.

This does not invalidate the clean-checkout reports used above, but it can undermine future comparison evidence.

**Required fix:** require a clean tracked checkout for authoritative reports, or bind a source-content/dirty-tree digest into report identity and explicitly label exploratory runs. Test both cached and refreshed dirty runs.

### P2 — Local HTTP mutations lack application-level request-origin protection

**Source confirmed; cross-browser exploitation not executed.** `demo_server.py:1497` parses JSON without checking Content-Type, Origin or Host. `do_POST()` exposes start, end, commit and transport-abort operations without a browser/session credential. Loopback binding limits network reachability but does not authenticate the requesting webpage. A simple cross-origin POST with a JSON string under a safelisted content type is not rejected by this handler; browser private-network policies vary.

**Required fix:** validate local Host and same-origin Origin for mutations, require JSON content type, and use an unpredictable session/CSRF token. Add request-level negative tests for foreign-origin start/end/abort, malformed length/body and oversized input.

### P3 — Invalid JSON returns the wrong response status

**Source confirmed.** `demo_server.py:1547` catches `ValueError` before `json.JSONDecodeError`, which subclasses it. Malformed JSON returns 409 through the broad handler; the intended 400 branch is unreachable.

**Required fix:** catch decode errors first and distinguish malformed bodies (400), conflicting battle state (409), and unsupported content types (415).

## Architecture and product status

Strengths worth preserving:

- Delegating mechanics to a pinned native engine, including built-runtime provenance checks.
- Keeping live sealed decisions separate from public hypothetical search inputs.
- Exact own request/PP/legal-menu checks and explicit degraded fallbacks.
- Treating sampled misses and missing priors as unresolved rather than logical exclusion.
- Replay-disjoint semantic data tooling, artifact hashes and distinct sampled retrieval metrics.
- Deterministic benchmark seeds, configuration-bound reports, cleanup/timeout tests and substantial CI smoke coverage.

The principal architectural weakness is using projection equality as a proxy for future mechanical equivalence. Public projections necessarily omit latent counters and volatile state. The Protect reproduction proves the gap is broader than timer names. Maintain an explicit inventory of persistent mechanics, their public evidence, uncertainty domains and construction support.

Maintainability also needs attention after correctness: `belief_controller.py` exceeds 4,500 lines and the Node worker approaches 3,900. The controller mixes current decision roots with historical recovery diagnostics, orchestration, transport ownership and strategy. Split these by responsibility while preserving characterization tests. Move demo HTML/JavaScript out of the Python string when improving browser behavior; current UI assertions often verify literal strings rather than actual interactions.

The demo uses a fixed team matchup and fixed AI preview. The training pipeline produces an offline semantic prior; the reviewed production controller/search paths do not load that learned model. Neither arbitrary team practice nor learned-policy gameplay improvement should be counted as completed. CLI milestone text and the top roadmap review marker also need updating: the checkout has reached #236, while the roadmap still says the next review is #220. Only the #220 review artifact is present in tracked `reviews/`; this checkout does not establish whether #230 received an external review elsewhere.

## Recommended sequence and completion gates

1. **Correctness:** fix repeat protection state and timed-effect domains. Require native negative controls and public-only construction; no admission relaxation.
2. **Coverage:** address the five non-phase rejection events across the paired reports and support forced-switch decisions. Acceptance: each frozen failure produces a valid admitted state or a specific justified unsupported result, with measured paired coverage.
3. **Evidence:** bind reports to actual source content, carry P1 findings into the next milestone review, and preserve comparable runs. Add a correctness gate before treating win-rate gains as progress.
4. **Strength:** broaden teams, opponent policies, seeds and held-out matchups. Evaluate tactical quality, replacement choices, fallback quality and latency. Integrate the semantic prior only as a candidate/response-ranking aid and measure an on/off gameplay ablation while preserving native legality.
5. **Practice product:** add team import, preview intelligence, better move/target controls and useful postgame explanations. Add browser interaction tests for queue/restart/end races and address local request-origin protection before wider distribution.
6. **Maintenance:** split the controller/worker, pin reproducible Python dependency versions, simplify launchers around shared routines, update current-status documentation and choose a project license before distribution.

Do not schedule work by accumulated PR count alone. Each mechanics change should identify the public authority it uses, a native rejection/negative control, a lifecycle fixture, and its paired benchmark effect. The immediate success criterion is trustworthy search-state behavior, followed by improved measured coverage and stronger play.
