# PR #245 review follow-up: spread friendly fire

PR #245 was already merged at `1518a61` when this review was handled. This
follow-up starts from current main, including #244 and #245; no unresolved
ROADMAP or CI reconciliation remains. Production behavior is unchanged.

V2 now discounts living partner exposure for damaging moves with the pinned Dex
target `allAdjacent`, including Earthquake and Surf. It retains the existing
direct ally-target penalty. Opponent-only spread moves such as Rock Slide remain
unpenalized. Utility discounts account for partner species typing and visible
health, with a minimum uncertainty penalty even for assumed Dex immunity.
Partner Protect and switches do not remove the penalty: the policy lacks a
certified lifecycle, action-order or protection model. This is conservative
heuristic risk scoring, not a calculated damage distribution or guaranteed
avoidance of all friendly fire.

Four regression cases cover Earthquake, Surf, opponent-only spread, and joint
Protect/switch commands. The native control verifies the pinned target classes
and executes a legal Earthquake while both opponents Protect. The unprotected
Metagross partner falls from 157 to 43 HP; V2 explicitly reports its exposure.
The control runs independently in CI and preserves a diagnostic artifact.

Both frozen pilot suites were regenerated after the policy change; previous
snapshots remain historical evidence. Results are unchanged: V2 wins 26/36 and
28/36, compared with fallback 10/36 and 12/36. All 144 games complete, all 1,374
decisions remain legal, and ranking deadline exhaustions are zero. Maximum
observed ranking time is 2.440 ms. Those fixture rosters do not exercise the
ally-hitting spread case; unchanged pilot results cannot substitute for the new
dedicated regressions/native control. These remain weak-baseline pilot results,
not full-production or competitive strength comparisons.

The regenerated reports share runtime source fingerprint
`365f3900095268e8e7befc6d631166892f232166e554e9d271d7a6f464483351`.
They are `agent-v2-spread-pilot-2026-10-12.json` and
`agent-v2-spread-validation-2026-10-12.json`. Native evidence is in
`agent-v2-spread-native-control-2026-10-12.json`.
Validation: all 1,631 tests pass; Ruff and the native spread control pass.

The next development assignment remains stronger, held-out evaluation against
the existing production bot. No new native reconstruction support is introduced.
