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

The next benchmark expansion should be measurement-driven rather than another hand-built
strategy pass. In particular:

- add complete-game hard cases such as repeated Protect, poor switching, and bad target
  allocation as reproducible search/evaluation regressions;
- add an offline true-world-survival metric for belief/recovery soundness;
- later add joint-action policy top-k recall and teacher-vs-live-bot win-rate gates;
- preserve the current strategic corpus as a regression floor, not as evidence that strategy
  is complete or that the current evaluator is a strong teacher.

Playing-strength work now proceeds in parallel with the human-data pipeline below. Further
hand-authored strategy expansion remains frozen unless gameplay exposes a concrete failure.

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

Current stochastic and recovery work:

- PR #139 established the first isolated finite stochastic primitive: the exact 16-bucket
  pinned-Showdown `Battle#randomizer` damage-roll domain;
- primitive exhaustiveness remains distinct from complete-transition exhaustiveness;
- no stochastic primitive may install, supplement, or eliminate live belief particles yet;
- the offline true-world-survival harness now measures both isolated reachability authority
  and production-shaped sampled conditioning against known exact hidden worlds;
- only an authoritative `EXHAUSTIVELY_DISPROVED` reachability result counts as a
  reachability exclusion; `WITNESSED`, `UNRESOLVED`, and `UNSUPPORTED` all preserve the
  true world;
- sampled conditioning is measured separately because a nonempty posterior can still be
  unsound if only wrong worlds happened to sample matching RNG outcomes;
- both false-exclusion channels can serialize exact pre-state, commands, observations, RNG,
  particle lineage, and coverage into deterministic hard-case JSON;
- the deterministic exact-team corpus runner now freezes external train/evaluation pools,
  revalidates arbitrary selected teams against the concrete battle format, preserves the
  closed-sheet public boundary, and emits external per-run survival reports and hard cases;
- ambiguous evidence should widen or retain support rather than forcing false precision;
- stop expanding stochastic mechanics speculatively. Scale the soundness harness over diverse
  exact teams and add accuracy, crit, multihit, secondary-effect, speed-tie, HP-interval, or
  other stochastic machinery only when measured failures show that the missing dimension
  matters.

Primary recovery metric:

`true-world survival rate = fraction of decision boundaries where the actual generated hidden
world remains represented after public conditioning/recovery`

The first target is effectively zero false exclusions on the covered offline corpus. Coverage
and precision are secondary: an inconclusive/wider belief is acceptable where exclusion is
not authoritative.

Phase exit criteria:

1. **Complete:** close the observation-producer contract findings with regression coverage for
   both expected and returned evidence.
2. **Complete:** rerun bounded hostile reviews of this surface and clear all P0/P1/P2
   authority findings through the v9 review after PR #138.
3. **Complete baseline:** add isolated finite stochastic-domain enumeration without granting it
   live-admission authority; PR #139 provides the first exact damage-roll primitive.
4. **Complete baseline:** build the offline true-world-survival harness, cover both
   reachability authority and production-shaped sampled conditioning, and serialize detected
   false exclusions as deterministic regressions.
5. **Infrastructure complete; measurement campaign pending:** use the deterministic exact-team
   corpus runner across a diverse game corpus and drive new stochastic support from measured
   false exclusions and inconclusive-coverage hotspots.
6. Build an independent Showdown differential validator that does not reuse production
   acceptance logic as its oracle.
7. Demonstrate sound recovery on that diverse corpus, with private information unable to
   influence pre-seal decisions.
8. Only then allow mechanics-authoritative recovery to affect live particle admission or
   elimination.

This phase is no longer a blocker on beginning human-data collection and policy learning.
Those tracks should proceed in parallel.

## Phase 10.6 — Human data, learned priors, and equilibrium search — next

The next intelligence phase begins before recovery is mechanically complete. The goal is not
to replace exact search with a neural policy. The learned model should provide fast VGC
judgment that allocates search toward plausible and strategically meaningful joint actions.

### Human replay corpus

The resumable public Showdown replay archive is now implemented. Raw replay JSON is kept
outside Git with hashes, provenance, retry/checkpoint state, measured throughput, and
per-format separation. Collection currently prioritizes Regulation M-C; older regulations can
be added as separate corpora rather than silently mixed.

The deterministic trajectory-extraction baseline is now implemented:

- reconstruct common public decision-time state from the replay prefix only;
- retain only observable/reconstructible two-slot action identity;
- ignore replay inputlog commands even when present;
- exclude called moves as selected actions and leave prevented/unobservable slots incomplete;
- retain a move's resolved public target without claiming that it was the originally selected
  target;
- preserve one trajectory document and one stable group key per replay for leakage-safe
  training/evaluation splits;
- bind every generated trajectory to the archived raw replay hash and an explicit schema.

The legal-menu matching baseline is now implemented:

- parse the exact pinned-Showdown joint-action strings already consumed by live search;
- map replay move/switch/pass identity only when exactly one legal menu entry is supported;
- resolve switch commands only with an explicit choosing-side party-slot species mapping;
- never use a resolved replay target to manufacture the originally selected target;
- abstain on incomplete labels, target ambiguity, switch-slot ambiguity, Mega-form ambiguity,
  or any replay action absent from the supplied exact menu;
- preserve exact legal-menu membership, menu index, Showdown revision, replay group, and
  abstention reason in the policy-example schema.

This exposed an important data-source boundary: a normal public replay does not contain the
choosing player's complete Showdown request, so it cannot by itself prove the complete legal
menu. The adapter therefore accepts only an externally supplied menu tagged as
`pinned-showdown-legal-choices` and does not infer missing moves, party-slot ordering, trapping,
or transformation options from later replay evidence.

A semantic-policy corpus audit/sharding baseline now measures that gap directly:

- complete public action identities become replay-disjoint semantic joint-action rows;
- incomplete labels remain explicit audit evidence rather than training rows;
- pinned Showdown static move metadata identifies move target types;
- public doubles slot geometry measures when move identity leaves multiple selected targets
  possible, without using the replay's resolved target as selected intent;
- switch rows are tagged as requiring player-side party-slot-order context;
- generic Mega evidence, missing-label reasons, rating bands, turn distribution, action
  families, split coverage, and usable rows per replay are reported;
- generated semantic rows are grouped by replay into deterministic 90/5/5
  train/validation/test splits and compressed external shards.

The first 50,000-replay M-C audit processed all 50,000 trajectories with zero source or
processing failures and produced 455,802 complete semantic labels from 678,286 side-turns
(67.2% coverage). The measured command-context gap is large: 353,487 semantic rows leave
selected target ambiguous, 86,258 require switch party-slot context, and 65,177 contain
generic Mega context. That measurement selects the broad semantic-action prior as the first
learned model rather than discarding most data or manufacturing exact commands.

The first offline semantic-policy trainer is now implemented. It:

- freezes an explicit audit run and records SHA-256 for every consumed shard;
- uses actor-relative replay-public state only, excluding names, results, rating, future events,
  and hidden particle identities from model features;
- scores complete two-slot semantic actions with separate hashed state/action embedding towers;
- uses same-action-family sampled negatives without claiming those alternatives are exact legal
  menu entries;
- applies explicit rating-aware loss weights so the large low-rated corpus does not define the
  objective solely by row count;
- reports sampled recall at 1/4/8/16 by rating band, action family, and turn phase;
- stores model, action vocabulary, configuration, dataset fingerprint, and evaluation report
  outside Git;
- remains offline only: exact Showdown legality and the protected exact-search baseline retain
  all live decision authority.

The next gate is to train the frozen 50k corpus, inspect validation/test behavior, and only then
build the authority-safe live feature/menu projection. Opponent private truth remains outside
the replay label authority.

### Team corpus and generalization

Complete published teams are simulator-side ground truth. Closed-sheet secrecy belongs at the
observation boundary, not inside the offline corpus.

The first curated source is the public VGCPastes Repository across Champions M-C, M-B, and
M-A. The importer:

- preserves content-addressed source-sheet snapshots and untouched Pokepaste raw text outside
  Git;
- retains regulation, team ID, owner/player, event, placement, source links, EV completeness,
  six displayed species, and other provenance;
- parses and normalizes every paste through the exact pinned Showdown runtime;
- uses exact M-C/M-B regulation validators where those formats still exist in the pin, while
  historical M-A is normalized through Champions Doubles Custom Game without claiming exact
  M-A legality;
- stores structured sets, packed teams, canonical Showdown exports, validator format, and
  validator revision as derived evidence;
- keeps `exact_team_ready` separate from `regulation_validated`: complete published M-A
  builds can be valid hidden simulator truth even though the current pin cannot certify their
  historical M-A legality;
- retains incomplete or invalid teams with diagnostics instead of inventing missing fields;
- revalidates archived raw teams automatically when the pinned Showdown revision changes.

M-C remains the primary current-meta pool. M-B and M-A provide additional complete-team
diversity for priors, self-play, and general VGC structure while remaining separately tagged
by regulation and validation authority. Any team used in a concrete battle must still pass
that battle format's validator before instantiation.

Fixed external training/evaluation pools and arbitrary-team battle instantiation now exist for
the recovery corpus runner. The next team-data use is replay-policy training/self-play while
preserving the same closed-sheet observation boundary.

### First learned model: semantic joint-action prior — implementation complete

Before a large teacher/value network, train a small policy model from human replay decisions.

The measured public-replay authority gap means v1 is a semantic two-slot action scorer rather
than an exact-command classifier. The action itself supplies move/switch identity while the
state tower consumes only actor-relative public decision state. Exact target, switch index, and
other command distinctions remain outside v1 unless they are later supplied by an authoritative
player-side request.

The implemented baseline uses deterministic hashed features, separate state/action embedding
towers, sampled same-family contrastive alternatives, sparse AdaGrad, and explicit rating-aware
loss weights. Validation/test report sampled semantic recall at 1, 4, 8, and 16 by rating band,
turn phase, action family, and whether the exact semantic joint action was seen in training.

Before live integration, evaluation also compares the learned scorer against a state-blind
training-frequency baseline on the identical sampled candidate pool. Saved models can be
re-evaluated post hoc without rerunning training, and immutable dataset/training hashes can be
given non-authoritative human-readable aliases for comparison reporting.

Those sampled metrics are representation/training diagnostics, not legal-menu recall. Exact-menu
evaluation requires simulator-generated or player-authoritative positions where the complete
menu is genuinely known. Team-archetype breakdown is likewise deferred until an authority-safe
definition exists rather than inferring hidden published teams from replay evidence.

The raw policy is not expected to be a strong standalone player. Its first job is to become a
measured prior that can later improve candidate shortlisting and search-budget allocation without
starving the protected tactical baseline.

### Equilibrium-search prototype

VGC turns are simultaneous decisions, so pure worst-case response ranking is not the long-term
target. Prototype a bounded CFR/Bayesian matrix-game layer after a usable joint-action prior
exists.

Requirements:

- operate on public belief worlds;
- solve over complete joint actions, not independent per-slot move rankings;
- reserve explicit coverage so learned priors cannot starve protected tactical baseline actions;
- preserve exact Showdown branch resolution as mechanics authority;
- run in shadow/diagnostic mode before it can influence the live selector;
- log disagreement against the current exact-search selector and strategic benchmark cases.

### Later learned value / teacher loop

Only after the policy-plus-search loop is measurable should a learned leaf value and expensive
teacher pipeline become the main training system. Teacher labels must carry search budget,
belief/world coverage, opponent-response coverage, stochastic coverage, value margin,
stability, and abstention reason. Unstable or under-covered positions should abstain rather
than manufacture ground truth.

The expected long-term loop is:

`human replay BC -> policy-guided equilibrium search -> self-play/search rows -> retraining
-> stronger search -> targeted hard-example augmentation`

Search remains the player; learned models provide priors and leaf judgment.

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
→ sealed playable demo → observation/reachability authority → first finite stochastic
primitive → [parallel tracks: recovery soundness + human replay/team corpus]
→ joint-action trajectory extraction → legal-menu adapter
→ player-side menu-context strategy → behavior-cloned policy prior
→ bounded equilibrium/CFR prototype → independently validated recovery
→ learned value/teacher loop → targeted selective depth and review tools**

Near-term implementation order:

1. **Complete:** replay downloader/raw corpus archive with throughput measurement;
2. **Complete baseline:** curated M-A/M-B/M-C VGCPastes ground-truth team corpus;
3. **Complete baseline:** offline true-world-survival recovery harness;
4. **Complete infrastructure:** deterministic exact-team soundness runner with fixed external
   pools and arbitrary-team battle instantiation; the first local M-C measurement completed
   64 battles / 469 transitions with zero observed true-world false exclusions;
5. **Complete baseline:** replay-to-public-state/action-identity trajectory extractor with
   replay-disjoint grouping and explicit label authority;
6. **Complete baseline:** exact legal-menu matching adapter with strict abstention when public
   replay evidence cannot identify one submitted command;
7. **Complete infrastructure + measured:** replay-disjoint semantic-policy corpus audit and
   compressed dataset shards; the 50k M-C snapshot yields 455,802 complete semantic labels;
8. **Complete implementation / measuring:** rating-aware semantic two-tower policy trainer
   with frozen-dataset provenance and sampled recall diagnostics;
9. **Evaluation gate:** human-readable immutable-run aliases, state-blind frequency baseline,
   seen-vs-unseen semantic-action metrics, post-hoc saved-model evaluation, and compact run
   comparison reporting; keep the learned policy disconnected from live selection;
10. **Cross-regulation experiment:** keep M-B separately tagged and compare M-C-only,
    M-B+M-C mixed, and M-B pretraining -> M-C fine-tuning on an unchanged M-C test set;
11. **After those measurements:** authoritative exact-menu/shadow policy evaluation with
    semantic projection onto Showdown's true choosing-side legal menu; exact search remains
    protected and authoritative;
12. bounded CFR/Bayesian matrix-game prototype;
13. additional stochastic mechanics only when measured soundness failures require them.
