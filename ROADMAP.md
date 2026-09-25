# Champions Practice Bot Roadmap

The simulator is exact. The decisions are not yet proven optimal: recommendations are
bounded, one-ply searches over sampled public-belief worlds, adversarial replies, and RNG
futures using an evolving board evaluator.

## Phase 1 — Exact simulator foundation — complete

Official Pokémon Showdown owns mechanics, serialized state, restoration, branching,
deterministic RNG sampling, legal-action generation, and persistent battle sessions.

## Phase 2 — Public-information boundary and beliefs — complete

Player-specific views expose only legal public information. Public priors create weighted
set and bring-four hypotheses. Anti-cheat regressions prove hidden truth cannot change the
belief state or the current turn-one recommendation.

## Phase 3 — Bounded belief-aware exact search — complete for one-ply decisions

The engine autonomously reduces both sides' complete legal spaces into strategically
diverse shortlists, preserves target alternatives and focus fire, samples RNG, simulates
exact Showdown branches, and aggregates results across belief worlds.

This is exact branch resolution, not exhaustive game solving.

## Phase 4 — Search performance foundation — complete for now

Persistent workers, batched validation, legal-choice caching, family-first pruning, and
honest timing make the current search practical. Optimize again only when gameplay data
identifies a real latency problem.

## Phase 5 — Position visibility and decision evidence — complete for current search

Every recommendation must expose:

- the public turn and request phase;
- all active Pokémon, public HP, status, and stat stages;
- terrain, weather, room effects, and side conditions;
- shortlist coverage and an explicit non-optimality warning;
- the top alternatives, aggregate scores, and representative worst replies.

The smoke report now includes the full final shortlist, per-world worst replies, named
score components, the chosen worst resulting board, and a pruning audit that distinguishes
cheap screening scores from final belief-search scores.

## Phase 6 — Selective continuation — complete as a bounded principal-variation probe

The strongest one-ply candidates are extended from their current worst sampled
world/reply/RNG branch. The exact resulting Showdown state preserves turn progression,
forced-switch requests, and consecutive-Protect state. A fresh bounded adversarial search
then exposes the proposed next action, reply, leaf board, branch cost, and whether the
one-ply recommendation survives.

This is deliberately not exhaustive two-ply minimax. Benchmarks must determine whether to
extend additional first-turn worlds and responses or replace the probe with a broader
selective tree.

## Phase 7 — Persistent live belief state — complete

The live controller now carries exact public-belief particles across turns instead of
reconstructing from complete command history. Independent RNG histories, persistent public
HP/status evidence, bounded resampling, hard decision/conditioning deadlines, legal
fallbacks, and multi-turn posterior updates are covered by real Showdown integration
smokes.

Replay reconstruction remains available only for controlled diagnostics and tests.

## Phase 8 — RNG-robust live conditioning — complete

Production conditioning now samples fresh bounded RNG continuations, adaptively expands
after zero-match batches, preserves surviving hidden-world diversity, retains the last good
posterior after sampling misses, and retries unresolved public transitions.

Current hardening uses channel-filtered public move/target observations to constrain opponent
responses before exact replay. Fully observed doubles move turns validate a tiny reconstructed
candidate set directly in Showdown instead of enumerating the entire legal response space,
then spend the saved budget on additional RNG futures. Stale move observations are excluded
from switch-only transitions by comparing the previous and current public views. The
production damaging-turn smoke now requires public damage on both sides in one turn.

## Phase 9 — Strategic reasoning layer — feature baseline complete

Add explicit strategic state and plan generation: threat assessment, resource valuation,
win conditions, desired future boards, speed-control objectives, sacrifice/trade logic,
cleanup pieces, mode selection, and multi-turn plan candidates. Exact Showdown search
remains the tactical verifier rather than the sole source of strategy.

Completed so far:
- read-only strategic state, resource roles, desired boards, win conditions, and plans;
- posterior-aware sacrifice/trade and plan evaluation;
- soft plan-to-tactics guidance that can reserve candidate coverage without displacing the
  tactically strongest screened action;
- exact strategic plan probes over bounded candidates, adversarial replies, belief worlds,
  and RNG futures;
- explicit unsupported/unresolved evidence reporting before a plan can receive sampled
  robust authority;
- strategic desirability is separated from mere feasibility for supported plans;
- speed-control plans require a favorable exact speed relationship;
- equally sampled-robust plans compare exact resulting-board utility before deterministic
  ties;
- unsupported one-turn plans are filtered before the live plan budget;
- DesiredBoard can now require an active pairing, a newly safe-entered resource, and
  purpose-specific endgame resources such as a cleanup piece held in back;
- exact plan evidence records active and newly active resources and evaluates those richer
  positioning requirements;
- a labeled strategic benchmark corpus now spans speed control, sacrifice, resource
  preservation, targeting, positioning, and cleanup-role generation while keeping the
  remaining unfinished capability explicit;
- executable benchmarks can now run the production-shaped strategy path from public
  assessment through generation, exact plan probing, supported-plan selection, and scoring;
- CI includes a real-Showdown strategic smoke so at least one labeled strategy case crosses
  the Python/Showdown boundary rather than relying only on synthetic branch summaries;
- live strategic probes now sample two deterministic RNG futures instead of one, and probe
  authority is labeled sampled robust rather than proven robust;
- executable benchmarks now cover Protect-based preservation and switching a unique
  resource when Protect is unsafe;
- boosted-threat targeting now has one-turn exact evidence for neutralization and public
  boost snowball, turning that benchmark from known gap into a resolved regression;
- active-pair/safe-entry generation now derives a positioning objective from active and
  benched unique-role resources, with exact evidence deciding whether the entry is safe;
- support-sacrifice generation now activates only for heavily spent active support pieces
  with a healthy benched unique-role endgame resource, while exact evidence decides whether
  the trade is worthwhile;
- offensive cleanup-role generation now derives a finisher from own offensive density,
  health, public opposing HP, and the current speed mode;
- the initial 11-case strategic benchmark corpus now has zero known gaps.

Current work:
- freeze further strategy expansion until gameplay produces concrete failures;
- preserve exact belief search as the final command selector;
- keep the completed Phase 9.5 hardening as the authority/isolation baseline;
- keep the 11-case strategic corpus as a regression floor rather than evidence that strategy
  is complete or optimal.

Next:
- build the interactive battle tech demo on the restricted sealed-choice boundary;
- expose only public battle state and an opaque AI-locked status before human commitment;
- reveal the AI decision and diagnostics only after both choices are submitted to Showdown;
- use complete demo games to identify the next strategy/search improvements.

## Phase 9.5 — Pre-demo authority and isolation hardening — final PR pending

The strategy feature baseline is frozen until complete-game evidence justifies new strategic
capabilities. PR #78 is the final pre-demo correctness hardening pass. Exact belief search
remains the final command authority; strategy may add candidate coverage and explanatory
evidence but may not suppress the protected tactical baseline.

Final authority rules:

- secure an unguided exact tactical result before optional strategy work;
- build shared strategic opposition against the union of the protected baseline shortlist
  and every supported plan's guided shortlist;
- screen that opposition against every candidate reference in the union;
- use the full tactical opponent-response limit for the final shared evidence rather than
  the smaller strategic-probe default;
- evaluate the baseline shortlist, selected guided shortlist, and selected probe winner
  together in one final exact search using the same opponent replies and RNG futures;
- attach a strategic-plan label only when the final exact winner both matches the selected
  guidance and was robust in that plan's probe.

The live battle boundary is now a synchronized sealed state machine behind
`SealedBattleFacade`. The human-facing surface exposes public state, legal human choices,
an opaque ready token, commitment, reconciliation, and close operations. It does not expose
the raw decision engine, live worker, session identifier, or sealed command. The AI decision
and diagnostics are returned only after the human action has been accepted and both commands
have been submitted.

Failure handling retains the sealed action across recoverable live-session failures, avoids
resubmitting an already advanced turn, serializes failed-turn reconciliation, and obtains the
human-facing post-turn view before mutating belief state so a retry cannot condition the same
turn twice. Real-session coverage includes invalid-token and illegal-action negative controls,
multi-turn sealed play, tiny-budget fallback, forced-switch transitions, terminal resolution,
and refusal to lock another action after battle end.

Runtime hardening now verifies both the pinned clean Showdown source revision and the exact
generated `dist/` tree through a build digest stamp. Absolute decision/conditioning deadlines
use bounded worker termination and lifecycle checks for leaked Node processes and executor
threads.

Two threat-model limits are explicit rather than disguised as guarantees:

- the sealed demo boundary protects a browser/client that receives only serialized façade
  outputs; arbitrary hostile Python executing inside the server process could still use
  language-level introspection and would require process/service isolation;
- worker startup counts against the absolute budget once construction returns, but a
  pathological hang inside synchronous process construction itself is not forcibly
  interruptible by the current helper.

Those limits do not justify more architecture work before gameplay unless CI or the demo
shows a concrete failure.

Current gate:

- final static audit complete on the #78 branch;
- pull-request CI is still required for unit tests, Ruff, runtime provenance, persistent
  sealed play, forced-switch/terminal behavior, timeout cleanup, and the existing search and
  conditioning smokes;
- once #78 is green and merged, freeze strategy and architecture work and build the playable
  local multi-turn demo;
- use complete games and post-commit decision traces as the next source of intelligence work.

## Phase 10 — Benchmark and playing-strength development — started

The first labeled strategic benchmark corpus is in place. It records expected plans,
actions, desired boards, preserved resources, and capability gaps independently from the
live controller. The initial 11-case corpus currently has no known gaps; future missing
capabilities should still be added explicitly rather than hidden from CI.

The benchmark harness now supports production-shaped execution:
public view -> StrategicAssessment -> generated plans -> one-turn support filtering ->
exact plan probes -> supported-plan selection -> labeled scoring. CI also runs a dedicated
real-Showdown benchmark smoke for neutral Trick Room versus resource preservation.

Continue adding labeled positions and complete games. Compare bounded belief search with
exhaustive search where tractable and with perfect-information search only as a diagnostic
oracle. Track missed KOs, sacrifices, targets, switches, Protects, speed control, field
control, setup recognition, conservatism, strategic-plan quality, and latency.

## Phase 11 — Selective deeper reasoning

Add only what benchmark failures justify: selective two-ply search, adaptive world/RNG
budgets, transposition caching, better public priors and probability updates, stronger
response modeling, or parallel branching.

## Phase 12 — Practice interface and review tools

Build the local browser client: team import, preview, battlefield, move/target/switch/Mega
controls, thinking state, battle log, replay, postgame review, belief inspection, decision
traces, and optional perfect-information postgame analysis.

Current sequence:

**Simulator → public beliefs → bounded exact search → autonomous pruning → position evidence
→ selective continuation → persistent live particles → RNG-robust conditioning → strategy
→ benchmarks/tuning → selective depth → GUI**
