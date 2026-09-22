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

## Phase 7 — Midgame belief-state reconstruction — next major objective

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

## Phase 8 — Live autonomous practice opponent

Connect reconstruction and search to the persistent session loop. Add a decision deadline,
safe heuristic fallback, forced-switch handling, and complete-game regression tests.

## Phase 9 — Benchmark and playing-strength development

Build labeled positions and complete games. Compare bounded belief search with exhaustive
search where tractable and with perfect-information search only as a diagnostic oracle.
Track missed KOs, sacrifices, targets, switches, Protects, speed control, field control,
setup recognition, conservatism, and latency.

## Phase 10 — Selective deeper reasoning

Add only what benchmark failures justify: selective two-ply search, adaptive world/RNG
budgets, transposition caching, better public priors and probability updates, stronger
response modeling, or parallel branching.

## Phase 11 — Practice interface and review tools

Build the local browser client: team import, preview, battlefield, move/target/switch/Mega
controls, thinking state, battle log, replay, postgame review, belief inspection, decision
traces, and optional perfect-information postgame analysis.

Current sequence:

**Simulator → public beliefs → bounded exact search → autonomous pruning → position evidence
→ selective continuation → midgame reconstruction → live opponent → benchmarks/tuning
→ selective depth → GUI**
