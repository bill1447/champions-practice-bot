# Strategic benchmarks

The benchmark corpus is a labeled specification of strategic behavior we care about.
It is deliberately separate from the live controller and from ordinary unit-test
implementation details.

Each case records:

- the strategic category and stage being tested;
- a short scenario and the principle it is meant to exercise;
- accepted or forbidden plan names when relevant;
- accepted tactical choices when the position is sufficiently labeled;
- richer DesiredBoard requirements such as active pairings, safe entry, or cleanup roles;
- preserved resources and acceptable sacrifices when those are part of the plan;
- whether the capability is already expected to work or is an explicit known gap.

## Result states

A benchmark result has one of three states.

**PASS** means the observation satisfies the labeled expectation.

**FAIL** means a capability that is already expected to work regressed or produced the
wrong strategic result. These are true benchmark regressions.

**KNOWN-GAP** means the case describes a capability we intentionally have not implemented
yet. It remains visible in reports without making the suite look healthy by omission or
turning unfinished work into red CI.

## Initial corpus

### sneasler-neutral-trick-room

Category: speed control.

The labeled position rejects Trick Room merely because it is feasible. With fast Sneasler
beside slower Indeedee-F, Trick Room must provide a favorable resulting speed relationship
before it receives strategic credit. The accepted line is Psychic + Protect rather than
Trick Room + Protect.

### critical-resource-over-material

Category: resource preservation.

A material-winning line is wrong if it spends the Pokemon explicitly required by the
declared endgame. The benchmark preserves the required Keeper even when that means making
less immediate material progress.

### gard-rilla-safe-entry-cleanup

Category: positioning.

The desired result is not just that Gardevoir, Rillaboom, and Sneasler remain alive.
Gardevoir must enter safely beside Rillaboom while Sneasler remains in back as the cleanup
piece.

### support-sacrifice-for-trick-room-endgame

Category: sacrifice.

Indeedee-F and Porygon2 may be acceptable losses when those resources are converted into
the declared Torkoal Trick Room endgame. This case encodes that sacrifice value depends on
the resulting win condition rather than raw Pokemon count.

### auto-generate-cleanup-purpose

Category: plan generation.

Cleanup is now inferred from position rather than species identity. When the visible opposing
active board is already chipped, the generator considers healthy benched resources with at
least two damaging moves. Outside Trick Room it prefers the fastest qualifying reserve;
under Trick Room it prefers the slowest. Exact evidence then verifies that the selected
cleanup resource can remain preserved in back for the current turn.

## Executable benchmarks

The corpus is no longer only a schema/scorer test.

`run_generated_strategy_benchmark()` executes the same strategic sequence used by the live
controller:

1. build `StrategicAssessment` from the public view and posterior;
2. generate the full strategic plan set;
3. filter plans unsupported by the one-turn evidence model;
4. probe each retained plan with exact branch resolution;
5. select the strongest fully supported sampled-robust plan;
6. score that observed result against the labeled benchmark.

Pytest includes deterministic production-shaped cases for the neutral-Trick-Room regression
and critical-resource preservation. CI additionally runs a dedicated real-Showdown smoke
that creates an actual Champions battle state and sends the generated plans through the
Showdown-backed exact probe path.

The real-Showdown label intentionally protects the strategic conclusion rather than one
exact tactical command. The deterministic benchmark still protects the original
`Psychic + Protect` action. This keeps simulator integration coverage from becoming brittle
when several tactically equivalent legal lines exist.

## How to use the corpus

When a strategy change is proposed, score its observations against the labeled cases before
granting it more live authority. Add a new case whenever a real battle, code review, or
regression reveals a distinct strategic failure mode.

Do not "fix" a benchmark by adding a species-specific rule unless the underlying strategic
principle really is species-specific. The preferred result is a general capability that
makes the labeled case pass for the right reason.


## Sampled robustness

Strategic probes do not prove a plan robust against every possible random outcome. They
resolve a bounded set of exact Showdown branches across selected belief worlds, adversarial
replies, and deterministic RNG futures.

The live controller now uses two deterministic strategic RNG futures. A plan receives
`sampled_robust` authority only if its chosen candidate remains robust across every sampled
branch and has no unsupported desired conditions or unresolved failure conditions.

The older `proven_robust` attribute remains temporarily as a read-only compatibility
alias, but diagnostics and new code use `sampled_robust`. Increasing the RNG sample count
later is a search-budget decision, not a change in what the term means.


## Expanded behavior coverage

The corpus now distinguishes strategic behaviors that the current production-shaped stack
can already execute from capabilities that are only represented or partially implemented.

### Protect a unique resource — resolved

The assessment identifies Anchor as the only living redirection provider. The generator
creates `preserve-anchor`, and exact plan evidence must prefer a Protect line when an
aggressive line loses that resource.

### Switch a unique resource — resolved

The same preservation objective is tested in a position where Protect still loses Anchor
under the sampled reply. Exact plan evidence must therefore prefer switching Anchor to the
bench. This verifies that preservation guidance is not synonymous with always clicking
Protect.

### Boosted-threat targeting — resolved

The assessment and generator identify a boosted immediate threat and create a
`neutralize-boosted-*` plan with target guidance. One-turn evidence now supports
`threat-snowballs:*` by comparing the threat's public positive boost mass with the exact
resulting Showdown state.

The benchmark requires the generated plan to focus the boosted opposing slot, KO that
threat, and receive sampled-robust authority. A competing line that attacks the other slot
lets the threat increase its public boost state and is recorded as a snowball failure.

### Active pairing and safe entry — resolved for unique-role resources

`DesiredBoard` can represent an active pair and a newly safe-entered Pokemon, and exact
evidence evaluates those requirements directly.

Generation now proposes a positioning plan when exactly one high-priority strategic
resource is active and another high-priority resource is on the bench. The generated board
pairs the benched resource with the active anchor and requires the benched resource to be
newly active. This is role-derived rather than species-derived; exact evidence still decides
whether any legal switch actually reaches the board safely.

### Sacrifice into a specific endgame — resolved for spent supports

Generation now identifies a bounded sacrifice pattern when both active resources are
support-oriented and already at 40% HP or lower while a healthy benched high-priority
resource remains available.

The generated plan explicitly preserves the benched endgame resource, marks the two active
supports as acceptable losses, and labels the endgame resource with an `endgame` purpose
while it remains in reserve. Exact evidence then decides whether a sacrificial line actually
improves the resulting board enough to justify those losses.

Healthy support resources do not trigger this plan.


### Offensive cleanup role — resolved

The AI-visible own-team view now includes exact own speed and damaging-move count derived
directly from Showdown. These are legal private facts about the AI's own team, not opponent
hidden information.

Cleanup generation requires:

- every visible opposing active Pokemon to be at 55% HP or lower;
- a benched resource at 70% HP or higher;
- at least two damaging moves on that reserve;
- a known own speed.

The preferred reserve follows the current speed mode: fastest outside Trick Room, slowest
inside Trick Room. The resulting DesiredBoard assigns a `cleanup` purpose with
`position="bench"`, so exact evidence rejects lines that spend the resource too early.

With this case resolved, the initial 11-case strategic benchmark corpus has no known gaps.
Future KNOWN-GAP cases may still be added when gameplay exposes new missing capabilities.
