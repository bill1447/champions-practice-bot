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

This is intentionally a known gap. The representation can express Sneasler as a cleanup
piece held in back, and exact evidence can evaluate such a plan, but current automatic plan
generation does not infer that offensive role from matchup state.

## How to use the corpus

When a strategy change is proposed, score its observations against the labeled cases before
granting it more live authority. Add a new case whenever a real battle, code review, or
regression reveals a distinct strategic failure mode.

Do not "fix" a benchmark by adding a species-specific rule unless the underlying strategic
principle really is species-specific. The preferred result is a general capability that
makes the labeled case pass for the right reason.
