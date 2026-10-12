# Frozen V2 versus full production

This is an evaluation-only capability. Neither V2 nor production policy, search,
admission, inference or reconstruction is modified. Current main `680a005` is the
reference. Both players receive eight seconds per decision by default. V2 retains
its legal incumbent and production retains its current tactical search and public
fallback. Setup and production conditioning time are recorded separately.

```powershell
.\.venv\Scripts\python.exe -m champions_practice.competitive_evaluation --seeds 5 --budget 8 --output runs/competitive-evaluation
.\.venv\Scripts\python.exe scripts/competitive_evaluation_report.py runs/competitive-evaluation/report.json --output runs/competitive-evaluation/analysis.json
```

The full configuration is 100 games: 30 held-out direct games, 10 reference direct
games and 60 games against a common public-pressure challenger. Each direct pair
uses the same teams, selections and seed, reversing which policy occupies p1/p2.
Common-opponent pairs replace V2 with production on the same team/side/seed. They
also cover both sides. Policy actions diverge, so identical initial seeds cannot
promise identical future random draws. Fixed selection `1234` isolates move play.
Five independent seeds per matchup are used; side outcomes are correlated.

Held-out teams recombine catalog species and include unfamiliar Earthquake/Surf
and bulk-oriented stat distributions. This is held-out composition/set testing,
not unseen-species generalization or a representative ladder sample. The public
prior catalog is frozen independently before selecting these variants. The
production bot is not given the actual opponent set, selected four or battle RNG.
Its decision configuration uses current defaults and independent particle seed
53101, eight worlds/particles, four candidates/responses and existing strategic
screening. Reference matchups retain the original mirror/balance sets.

The pressure challenger uses static public utility plus a fixed double-target
focus bonus. It shares the frozen V2 utility function; it is a related benchmark
challenger, not independent learning or a proven competitive opponent. Its
strength is measured in this suite rather than assumed. Neither main policy is
tuned against it during this PR.

## Capability and side mapping

The unchanged `BeliefDecisionEngine` is initialized from its player's sanitized
post-preview observation. Decisions and observation updates follow the production
coordinator path, including forced wait. The engine has only its restricted
hypothetical worker; it is not handed the live worker or an oracle snapshot. The
driver owns native sessions and seeds. Both players use request-derived public
menus (`session_public_choices`), avoiding hidden-state legality probes.

The production engine assumes p2. An evaluation-only adapter relabels public p1
protocol side/slot identifiers into that convention, leaving numeric facts,
relative command targets and selected actions unchanged. Unit controls verify
involution, detached copies and exact slot/request remapping. Complete native
side-swapped smoke games verify production search operates on both sides. This
adapter is not installed in production or certified for arbitrary user nicknames.

## Metrics and limits

Every decision retains sanitized own/public observations, its public menu, chosen
action, policy details, wall latency and cooperative budget overrun. Production
traces retain search/fallback modes, reasons, native admission and conditioning.
Fallback percentage excludes forced waits. V2 fallback means an unranked deadline
incumbent, not use of an absent native search engine. Timeout failures, budget
overruns, conditioning overruns and deadline fallback reasons are distinct.
Failed or capped games are retained and never silently scored as losses.

After both actions are fixed, an isolated validator may inspect the actual native
state. It evaluates the chosen action and up to three public-policy alternatives
against the same submitted opponent response using two independent coupled future
seeds. A diagnostic flags alternatives that strictly improve own survivors or
opponent KOs without worsening the other count on both sampled continuations.
This is bounded, conditional one-turn material dominance. It is hindsight and
does not prove strategic error, optimality, exhaustive regret or the probability
of a mistake. No state, hidden set, seed or diagnostic result feeds a decision.

The analysis validates cases, budgets, seeds, teams and legal actions against the
manifest. It separates held-out head-to-head, reference head-to-head and common
opponent results. Descriptive resampling bands cluster by matchup and seed rather
than treating side swaps as independent. They are not population confidence
intervals; constant observed results yield degenerate bands. CI verifies the
contract with a two-game side-swapped smoke, never a win-rate promotion threshold.

Keep V2 isolated. A favorable result establishes behavior on these tested cases,
not competitive strength or the superiority of V2 over correctly admitted search
at every position. Search-only diagnostic comparisons help locate that distinction.
Detailed frozen evidence and loss analysis are linked from the review report.
