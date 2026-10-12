# PR #247: frozen competitive evaluation

V2 substantially outperforms the current full production bot on this tested
suite. It is not yet a competitive player: the related pressure challenger beats
V2 in 19/30 common-opponent games. Keep V2 isolated pending the next gameplay
improvements and broader independent opponents; neither policy is changed here.

## Results

| Stratum | V2 wins | Production wins | Complete games |
| --- | --- | --- | --- |
| Held-out direct V2 vs production | 30/30 | 0/30 | 30/30 |
| Reference direct V2 vs production | 9/10 | 1/10 | 10/10 |
| Each versus common pressure challenger | 11/30 | 0/30 | 60/60 |

The direct comparison is **39/40 wins for V2**. It uses current full production
search with its existing defaults and fallback, not an emergency-fallback-only
opponent. All 100 games terminate; zero games are failures, draws or submission
caps. All 1,866 submitted actions are in their request-derived public menus.
There are zero transport timeouts and zero decision-budget overruns.

Both agents receive eight seconds per decision. Native seeds, selected-four
order and teams are paired. The suite reverses actual p1/p2 policy assignments.
Five seeds are tested per matchup. New compositions include Earthquake, Surf and
bulk-oriented stat variants outside the frozen published-set catalog; species
are familiar. Reference teams retain the earlier mirror/balance fixtures. This
is not arbitrary unseen-species evaluation or a representative competition field.
The pressure challenger shares frozen public utility and adds a fixed target-focus
bonus, so it is related to V2 rather than an independent learned opponent.

## Reliability, latency and decision quality

| Metric | V2 | Production |
| --- | --- | --- |
| Actionable decisions | 544 | 572 |
| Fallbacks | 0/544 (0%) | 498/572 (87.1%) |
| Search decisions | 0 (independent policy) | 74 |
| Decision p50 | 0.527 ms | 0.462 ms |
| Decision p95 | 1.286 ms | 5,377 ms |
| Maximum decision wall time | 1.917 ms | 7,784 ms |
| Bounded material-dominance flags | 46/432 diagnosed | 214/451 diagnosed |

Fallback denominators exclude forced waits. V2 fallback here means an unranked
deadline incumbent; no native-search coverage is required by that policy.
Production also records **16 conditioning-budget overruns**, outside decision
latency. These are not transport failures or decision timeouts. Initialization
and per-turn conditioning timings are retained separately in the archive.

Material flags compare the actual chosen command with up to three public-policy
alternatives under two coupled independent future seeds and the fixed submitted
opponent response, using isolated native oracle state after decisions are sealed.
They flag strict improvement of survivors or opponent KOs without worsening the
other count on both samples. They are hindsight, bounded, conditional diagnostics,
not strategic-error ground truth, exhaustive regret or calibrated probabilities.

Ten of production's 74 search decisions have a bounded alternative advantage;
all 74 search decisions occur on turn one, including intermediate requests.
In those ten, the public V2 shadow action supplies an improving alternative.
This does not prove V2 is always better than correctly admitted tactical search.
The whole-game advantage reflects production's limited search availability as
well as decision quality. We do not weaken its admission safeguards to improve
its benchmark score.

## Validation and provenance

The runtime sources for both policies and existing search workers are unchanged
from main `680a005`. The driver calls the unchanged production decision engine's
preview/choose/observation path. A separate full-game check through the actual
`SealedBattleFacade` reproduces every public observation, chosen action, mode and
winner for `direct-0-0-p1`. Production search is observed on both real sides
(39 p1 and 35 p2 search decisions). Its p1 adapter changes only copied public
side/slot labels, not numeric facts or relative commands. It is evaluation-only.

All 1,641 tests pass; Ruff passes. Pair validation checks the complete manifest,
equal seeds/teams/budgets, side-swapped and common-opponent assignments, and action
legality. Failed games remain explicit and never become scored losses. CI runs
the two-game side-swapped smoke and paired-analysis validation independently.
No win-rate threshold promotes a policy.

Runtime fingerprint:
`84d10d8ee3346c442b8a923270f9ce3692e0db358cf26015da3c3a6a1ad41d0a`.
Simulator pin: `a5df8274e85b0889bf2a9b3422a08b39732374fc`.
Policy and controller fingerprints, prior/team identities, all case seeds,
latency/failure summaries and compressed-archive checksums are in
`competitive-evaluation-summary-2026-10-12.json`.

The full 100-game trace is preserved losslessly in
`competitive-evaluation-2026-10-12.json.gz` (23,100,553 uncompressed bytes).
It retains own/public inputs, menus, selected actions, public V2 shadow rankings,
search/admission/fallback telemetry, timing and oracle diagnostic scalars. Actual
native snapshots are never persisted or passed to policies. The companion
analysis and facade-parity files are readable JSON. To inspect the archive:

```python
import gzip, json
with gzip.open("reviews/competitive-evaluation-2026-10-12.json.gz", "rt", encoding="utf-8") as stream:
    report = json.load(stream)
```

Descriptive matchup/seed-cluster resampling bands account for side correlation,
but are not population confidence intervals. Constant observed outcomes give
degenerate bands and cannot establish certainty about general strength.

## Next direction

Use the preserved V2 losses against pressure opponents to improve joint targeting,
threat/survival reasoning, Protect and positioning in a separate policy PR.
Retain this suite and add independent opponents and more held-out teams for the
on/off comparison. Do not put fresh reconstruction or native ancestry recovery
back on the gameplay critical path. This PR answers the comparison with the
current bot on a controlled suite; production promotion remains a separate gate.
