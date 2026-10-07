# Offline recovery soundness

The recovery soundness harness measures one property before experimental recovery is allowed
to influence live belief admission:

> Given an exact hidden world that we know generated a public transition, can our conditioning
> or reachability machinery incorrectly remove that true world?

This is an offline validation surface. It has no live particle-install or live-session
authority.

## Two failure channels

The harness measures two different ways the true world could be lost.

### 1. Reachability authority

A known-real exact pre-state, action pair, and public observation are evaluated through the
current isolated reachability boundary.

For true-world survival:

- `WITNESSED` survives;
- `UNRESOLVED` survives;
- `UNSUPPORTED` survives;
- only `EXHAUSTIVELY_DISPROVED` excludes the world.

This intentionally treats ambiguity as survival. A finite RNG miss is not negative evidence.

### 2. Production-shaped sampled conditioning

The harness can also start from an explicit particle set containing a tagged true
`world_id` and run the same `condition_particles` path used by production. Each case
supplies deterministic RNG batches; the harness accumulates misses and stops at the first
nonempty batch, mirroring the production adaptive-conditioning shape.

It then emulates the live controller's current one-transition update semantics:

- sampled positive matches are witnesses for the worlds that produced them;
- a finite sampled miss is never negative authority;
- a sampled posterior is installable only when every still-authoritative starting world
  is represented by at least one matching child;
- otherwise the last-good particles are retained and the controller enters degraded recovery.

This closes the measured conditioning false-exclusion channel in which a wrong world could
receive a lucky sampled match while the true world received none.

### 3. Finite stochastic transition reachability

When ordinary sampled conditioning cannot install a posterior and every opponent action slot
is freshly recoverable from the public Showdown channel, production may escalate to
public-command witness recovery and then the finite-transition enumerator. Recoverable
actions include direct selected moves, publicly prevented attempted moves, and plain selected
switches from Showdown's pre-resolution switch prefix. The enumerator replays the exact
hypothetical state and the publicly reconstructible joint command while branching Showdown's
finite random-call domains.

The authority rule remains fail-closed:

- one exact finite-transition witness may advance that hidden world;
- a world is excluded only if every retained particle and every public command candidate is
  exhaustively disproved by a completed finite random-call tree;
- branch-budget exhaustion, unsupported/unbounded random calls, timeout, or incomplete public
  command evidence remain unresolved and retain the last-good belief;
- switch species are resolved independently against each hypothetical particle's party indexes;
  a public species label is never treated as a universal private switch number;
- source-driven switches, `drag`, `replace`, and ambiguous/disguised switch projections are
  not promoted to exhaustive command authority;
- move modifiers such as Mega Evolution and Ultra Burst are constrained only when the
  recognized public mechanics ledger is aligned to the selected-action turn; an aligned
  ledger with no transformation event excludes invented transformation modifiers, while a
  missing or misaligned ledger fails open;
- the sealed opponent command is never supplied as live belief authority.

This layer is broader than the isolated 16-bucket damage randomizer: it follows the complete
transition's finite random calls, including categorical outcomes such as secondary effects,
while remaining bounded. The isolated damage-roll domain still carries no transition authority
by itself.

## Primary metric

For either channel:

`true-world survival rate = surviving known-real boundaries / evaluated known-real boundaries`

The target for authoritative recovery is effectively zero false exclusions. Witness/coverage
rates are secondary; unresolved or unsupported cases are acceptable until mechanics support
is expanded.

Reports expose:

- total boundaries;
- surviving boundaries;
- false exclusions;
- reachability witness / unresolved / unsupported counts;
- conditioning degraded-retention count;
- true-world survival rate.

## Deterministic hard cases

Every detected false exclusion can be serialized as a self-contained JSON regression.

Reachability regressions preserve:

- exact pre-state;
- state fingerprint;
- exact action pair;
- actual public observation;
- actual and probe RNG seeds;
- actual RNG draw count;
- preview context;
- reachability status and coverage.

Conditioning regressions additionally preserve:

- all starting particles;
- tagged true `world_id`;
- fixed adaptive conditioning RNG batches;
- resample limit/seed;
- branch/mismatch counters;
- resulting posterior world IDs.

CI writes any smoke-test false exclusion to:

`.runtime/recovery-hard-cases/`

which is included in the existing CI artifact upload. Larger local/corpus runs should write
hard cases under the external data root, for example:

`F:\Showdown replay data\recovery-hard-cases\`

and should not commit those generated cases to Git unless one is deliberately minimized into
a curated test fixture.

## Current pinned-Showdown smoke

```powershell
.\recovery-soundness-smoke.ps1
```

The smoke:

1. creates a known exact Champions hidden world in pinned Showdown;
2. generates a real stochastic public transition from that world;
3. verifies the exact RNG continuation is a positive reachability witness;
4. finds a different RNG seed that produces a distinct public outcome;
5. verifies that sampled miss remains `UNRESOLVED`, not impossible;
6. chains additional exact true-world boundaries;
7. runs production-shaped conditioning with both a matching RNG sample and a known sampled
   miss;
8. requires the true world to survive every tested boundary.

This fixed smoke is only the baseline. The exact-team corpus runner below scales the same
measurement across deterministic arbitrary-team battles.

## Exact-team corpus runner

PR #145 scales the fixed harness into a deterministic local corpus measurement without giving
recovery any new live authority.

```powershell
.\recovery-corpus.ps1
```

The default run uses current Regulation M-C truth teams. The runner:

1. reads only `exact_team_ready` teams from the external team manifest and verifies each
   canonical file against its recorded SHA-256;
2. creates a fixed external train/evaluation split with deterministic species and species-pair
   diversity, keeps identical canonical team bytes from crossing the split under different
   provenance rows, then reuses that exact pool until `-RefreshPools` is requested;
3. revalidates every selected team through pinned Showdown against the concrete battle format
   before instantiating it;
4. deterministically seeds battle initialization and legal action selection, then lets the
   real battle continue through native serialized Showdown RNG; probe RNG, the production
   adaptive conditioning batches `(2, 4)`, and resampling remain independently deterministic;
5. runs the measurement from the production bot's `p2` perspective and supplies the complete
   six-species public preview while retaining exact sets only as offline hidden truth;
6. when available, adds other published teams from the frozen pool with the same six species
   as opening-boundary hidden-world decoys and translates team-preview selections by species.
   Newly downloaded teams cannot silently alter an existing pool/run. Later turn cases do not
   advance decoys with the known human command, because that hidden command is not public
   conditioning authority;
7. measures reachability-authority survival and production-shaped sampled-conditioning
   survival separately.

M-C and M-B use their exact pinned regulation validators. Historical M-A has no exact format
entry in the current pin, so corpus battles refuse M-A by default. The explicit
`-AllowNonauthoritativeRegulation` diagnostic mode uses Champions Doubles Custom Game and
marks those rows non-authoritative; it is not evidence of historical M-A legality.

Generated bulk data stays outside Git under:

```text
<external root>\recovery-soundness\
├── team-pools-v1.json
├── latest-summary.json
└── runs\<deterministic-run-id>\
    ├── summary.json
    ├── cases.jsonl
    ├── team-pool.json
    └── hard-cases\
        ├── reachability\
        └── conditioning\
```

Each run snapshots the exact pool IDs and canonical hashes it used. The deterministic run ID
also binds the full frozen pool and pinned Showdown revision, so newly downloaded teams, a
pool refresh, or a mechanics-pin change cannot silently overwrite an older run's provenance.

The summary includes survival and false-exclusion counts plus breakdowns by regulation, turn,
complete-action family, and whether the real transition consumed simulator RNG. A large local
run is a measuring instrument: discovered false exclusions are serialized rather than hidden
or converted into mechanic-specific patches. Classify the missing stochastic/evidence domain
first, then add structural support and a minimized regression.

CI runs only a tiny deterministic external fixture. The bulk corpus and generated reports are
never required in GitHub Actions.

## Scope

This harness is not the independent Showdown differential validator from the roadmap. The
current fixtures can be generated and evaluated by the same pinned Showdown runtime. It is
therefore a soundness monitor for our exclusion/conditioning logic, not an independent proof
that Showdown itself or our public-observation producer is correct.
