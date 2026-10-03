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

## Phase 8 — RNG-robust sampled live conditioning — complete baseline

Production conditioning now samples fresh bounded RNG continuations, adaptively expands
after zero-match batches, preserves surviving hidden-world diversity, retains the last good
posterior after sampling misses, and retries unresolved public transitions.

Current hardening uses channel-filtered public move/target observations to constrain opponent
responses before exact replay. Fully observed doubles move turns validate a tiny reconstructed
candidate set directly in Showdown instead of enumerating the entire legal response space,
then spend the saved budget on additional RNG futures. Stale move observations are excluded
from switch-only transitions by comparing the previous and current public views. The
production damaging-turn smoke now requires public damage on both sides in one turn.

Finite RNG coverage is deliberately not proof of mechanical impossibility. A sampled match
is positive evidence that a hidden world is reachable; exhausting a finite seed sample is
only inconclusive. Complete negative authority is reserved for separately proven exhaustive
mechanics domains.

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
- keep strategy feature expansion frozen while belief/recovery authority is hardened;
- use complete demo games and benchmarks to collect difficult positions and concrete failures;
- preserve exact belief search as final command authority while experimental reachability and
  recovery remain isolated from live particle admission;
- resume strategy expansion only when gameplay demonstrates a specific missing capability.

## Phase 9.5 — Pre-demo authority and isolation hardening — complete

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

Final gate:

- PR #78 passed the full Windows CI workflow and merged to `main`;
- strategy and architecture feature work remain frozen unless complete-game evidence exposes a
  concrete failure;
- the playable local multi-turn demo has since been built and exercised;
- subsequent belief-collapse investigations identified sampled stochastic conditioning, not
  strategy breadth, as the next correctness bottleneck;
- post-commit decision traces and complete games remain an important source of hard examples.

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

Playing-strength expansion is not the current critical path. The benchmark corpus remains a
regression floor while mechanics-authoritative belief recovery is hardened.

## Phase 10.5 — Mechanics-authoritative reachability and recovery — in progress

The live bot can already play complete games, but sampled exact replay is not sufficient to
decide whether a hidden-world hypothesis is mechanically impossible. A real collapse showed
that normal conditioning could sample zero matching branches while a larger RNG search later
found an exact witness. The recovery target is therefore:

`Could this observed public transition occur under this hidden-world hypothesis?`

rather than:

`Did one bounded set of sampled RNG seeds happen to reproduce it?`

Foundation merged through PR #138:

- static recovery rebuilds hypotheses from authoritative pre-opening inputs rather than
  mutating already-started states;
- finite recovery RNG misses are explicitly inconclusive;
- stable roster-member lineage and exact forced-wait commands are preserved across replay;
- typed reachability results distinguish `WITNESSED`, `EXHAUSTIVELY_DISPROVED`,
  `UNRESOLVED`, and `UNSUPPORTED`;
- sequential Showdown witnesses propagate exact child states;
- deterministic negative authority is allowed only for proven zero-PRNG transitions with
  exhaustive response coverage;
- submitted human commands have been removed from belief/recovery authority after PR #134:
  conditioning and recovery reconstruct compatible opponent actions only from public evidence;
- observation validation through schema `showdown-player-view-v9` is bound to the pinned
  producer contract, including bidirectional consistency between selected opponent execution
  evidence and the retained opponent move ledger;
- the bounded hostile v9 review after PR #138 found no P0/P1/P2 findings in the reviewed
  public-observation validity and reachability-authority surface;
- reachability remains isolated and cannot currently install, supplement, or eliminate live
  belief particles.

Observation-authority gate — closed for the reviewed v9 surface:

The producer-contract findings discovered across reviews of PRs #125-#137 are closed with
expected/returned-evidence regressions. This clears the prerequisite for isolated finite
stochastic-domain work. The certification is scoped to the reviewed public-observation and
reachability-authority boundary at the pinned Showdown revision; it is not a certification of
the broader bot or future Showdown revisions.

Current stochastic work:

- add finite mechanics primitives only through pinned Showdown;
- keep primitive exhaustiveness distinct from complete-transition exhaustiveness;
- do not convert primitive enumeration into live admission/elimination authority yet;
- begin with the 16-bucket `Battle#randomizer` damage-roll domain, then compose additional
  stochastic dimensions only with explicit coverage accounting.

Phase exit criteria:

1. **Complete:** close the observation-producer contract findings with regression coverage for
   both expected and returned evidence.
2. **Complete:** rerun bounded hostile reviews of this surface and clear all P0/P1/P2
   authority findings through the v9 review after PR #138.
3. **In progress:** add isolated finite stochastic-domain enumeration without granting it
   live-admission authority.
4. Build an independent Showdown differential validator that does not reuse production
   acceptance logic as its oracle.
5. Demonstrate that the true hidden world remains reachable, mechanically impossible worlds
   are rejected only with adequate authority, and private information cannot influence
   pre-seal decisions.
6. Only then allow mechanics-authoritative recovery to affect live particle admission or
   elimination.

Planned stochastic mechanics work after the observation-authority gate:

- enumerate bounded discrete damage rolls where practical;
- use exact AI-side HP deltas to constrain opponent offensive parameters;
- map public opponent HP percentages to exact-HP intervals or sets;
- handle sequential bounded damage and small categorical RNG domains explicitly;
- merge observationally equivalent histories;
- retain sampled fallback only for compound or unsupported mechanics;
- add likelihood weighting only after reachability correctness is independently validated.

This phase is the main correctness dependency for later teacher/data-generation work.

## Phase 11 — Selective deeper reasoning

Add only what benchmark failures justify: selective two-ply search, adaptive world/RNG
budgets, transposition caching, better public priors and probability updates, stronger
response modeling, or parallel branching.

## Phase 12 — Practice interface and review tools — started

The first playable vertical slice is a localhost-only browser client built directly on
`SealedBattleFacade`. It uses a fixed current-roster mirror fixture so complete games can
begin before arbitrary-team import and polished controls exist.

Initial demo scope:

- human team-preview selection from live legal choices;
- sanitized public battle-state display;
- server-side AI sealing before human submission;
- legal human command selection and multi-turn resolution;
- forced-switch/terminal compatibility inherited from the sealed coordinator;
- post-commit decision and conditioning history;
- no current AI command or lock token serialized to the browser.

Next interface work should be driven by actual play. Likely additions are arbitrary team
import with a legitimate public-prior source, structured move/target/switch/Mega controls,
battle-log presentation, replay/postgame review, and better team-preview intelligence.

Current sequence:

**Simulator → public beliefs → bounded exact search → persistent beliefs → strategy
→ sealed playable demo → complete games → observation/reachability authority
→ finite stochastic enumeration → validated mechanics-authoritative recovery
→ targeted tuning/selective depth → review tools**
