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

## Phase 5 — Position visibility and decision evidence — in progress

Every recommendation must expose:

- the public turn and request phase;
- all active Pokémon, public HP, status, and stat stages;
- terrain, weather, room effects, and side conditions;
- shortlist coverage and an explicit non-optimality warning;
- the top alternatives, aggregate scores, and representative worst replies.

Next evidence additions are per-world outcomes, score-component breakdowns, and pruning
reasons. This phase starts before the live bot because it is how later work is verified.

## Phase 6 — Midgame belief-state reconstruction — next major objective

Belief worlds currently begin from team preview. Reconstruct the current turn in every
world while preserving only public information:

- active and benched identities;
- HP, fainting, status, stat stages, and public transformations;
- consumed or revealed items and abilities;
- terrain, weather, rooms, screens, hazards, and other public effects;
- PP and choice constraints only when legitimately knowable;
- the AI's own exact private state.

Hidden-state mutation tests must prove that unrevealed truth cannot affect the reconstructed
position or recommendation. Nontrivial turn-two and turn-four fixtures will compare the
displayed position, reconstructed worlds, and live session state.

## Phase 7 — Live autonomous practice opponent

Connect reconstruction and search to the persistent session loop. Add a decision deadline,
safe heuristic fallback, forced-switch handling, and complete-game regression tests.

## Phase 8 — Benchmark and playing-strength development

Build labeled positions and complete games. Compare bounded belief search with exhaustive
search where tractable and with perfect-information search only as a diagnostic oracle.
Track missed KOs, sacrifices, targets, switches, Protects, speed control, field control,
setup recognition, conservatism, and latency.

## Phase 9 — Selective deeper reasoning

Add only what benchmark failures justify: selective two-ply search, adaptive world/RNG
budgets, transposition caching, better public priors and probability updates, stronger
response modeling, or parallel branching.

## Phase 10 — Practice interface and review tools

Build the local browser client: team import, preview, battlefield, move/target/switch/Mega
controls, thinking state, battle log, replay, postgame review, belief inspection, decision
traces, and optional perfect-information postgame analysis.

Current sequence:

**Simulator → public beliefs → bounded exact search → autonomous pruning → position evidence
→ midgame reconstruction → live opponent → benchmarks/tuning → selective depth → GUI**
