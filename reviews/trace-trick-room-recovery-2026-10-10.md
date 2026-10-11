# Playable reliability: Trace and Trick Room recovery — 2026-10-10

This update targets all six fallback decisions in the preceding synthetic
eight-game report: three copied terrain-source failures and three active Trick
Room duration failures. It also repairs public identity and native evolution
for opponent Megas returning from the bench.

## What the player gains

The bot can reconstruct a publicly disclosed Trace copy of a Surge ability and
keep the resulting terrain's original source after that Pokémon evolves or
switches out. A returning Mega retains its preview roster identity. Trick Room
can remain available to tactical search through ordinary activation, toggling,
reactivation, source switching and end-of-turn replacements.

## Evidence and construction

Plans use only ordered sanitized public lifecycle events and the public ledger.
Trace requires an identified opposing donor and the canonical native disclosure.
Current copies cover the four Surge abilities, inactive Unburden and Pixilate;
switches and Mega evolution end current copies. Historical terrain activation
keeps its separately proven Trace origin. Native `setAbility` establishes current
copies; native field start receives the historically disclosed Surge effect.

Trick Room requires a canonical start, complete upkeep boundaries, no later end
and zero through four elapsed residuals. Unknown activation, missing boundaries
and extension annotations reject admission. Native Persistent sources remain
unsupported. Native `addPseudoWeather` and field residual operations establish
the current duration without counter assignments. Terrain and Trick Room share
a residual timeline, with younger effects activated later. Empty field residual
targets exclude Pokémon HP, status and volatile callbacks.

After expiry, replacements can leave a positive owned speed cache next to a
negative cache. Native speed updates under temporary Trick Room now apply only
to owned members whose exact observed cache is negative. Public Mega events
restore permanent opponent evolution and its disclosed stone through native
switch/evolution operations, including when that member is benched.

Exact owned state/request, current field, public opponent constraints, legal
menu and native serialization checks remain required. No sealed live battle,
opponent private set, historical move queue or native timer oracle enters the
production plans. Native counters and exact opponent abilities are offline
regression oracles only. Unsupported construction leaves a world unresolved.

## Validation

All 1,520 pytest tests pass, including 18 new public evidence controls. Ruff and
native worker syntax pass. Native controls cover both sides' Trace copies,
Mega evolution, bench/return, terrain expiry, retained Terrain Extender,
Trick Room toggling/restart, source switching, joint field age and expiry.
The frozen command sequence from the previous synthetic report's game seven
now reconstructs the active Trick Room replacement checkpoint and later move
states. Terminal states are excluded from decision reconstruction.

Protection, terrain, replacement, own Mega, present-mechanics, Unburden,
fainted-active, public execution evidence/authority and sealed transition
regressions pass. The protection fixture uses a static ability to isolate stall
behavior from an unsupported Trace/Flash Fire activation domain. The separate
Trace controls cover the newly supported copy domains. Human Mega regression:
eight searches, zero fallbacks in eight decisions.

Both final source-bound runs completed with unchanged configuration: eight games
per fixture, seed 15601, eight-second decision budget and the same baseline.

| Fixture | Previous update | This update | PR 236 reference |
| --- | ---: | ---: | ---: |
| Current roster mirror | 0/48 (0.0%) | 0/48 (0.0%) | 5/51 (9.8%) |
| Synthetic spread uncertainty | 6/64 (9.4%) | 0/63 (0.0%) | 13/92 (14.1%) |

Fallback rates use all decisions, including forced waits, consistently with prior
reports. Search covered every decision requiring an action: 34/34 in mirror and
52/52 in synthetic. The native protocol required 14 and 11 waits respectively.
Mirror searched 43,198 branches; synthetic searched 55,866. Decision p95 was
7.776 seconds in each run, within the configured budget. No copied terrain-source,
Trick Room, own-ability or own-active-flag fallback occurred. All games completed;
records remained 8–0 and 7–1. Records are secondary to recovery and legal search
coverage. Small samples, changed trajectories and wall-clock budgets limit causal
and broader competitive-strength claims.

Reports are `runs/strength-league/994b4fea1a9fe1d50fe5/report.json` and
`runs/strength-league/ad00076b5cdc9a623926/report.json`. Both bind parent commit
`668d8ec600fa8ec3bce8e3f1049c471d3e3f9bf3` and dirty runtime source fingerprint
`05102cc10b8f9d3cdade53cbdaac1ead60e0958ded4b2509a4bd1a75fd0ee1ff`.
Runtime sources remained unchanged during measurement.

With the measured six blockers recovered, the next acceptance work is broader
team and mechanic coverage with true-world survival, privacy and projection
checks; zero fallback on these two fixtures does not establish universal support.

## Remaining scope

Other copied abilities and lost-item copied Unburden activation remain
unsupported, as do uncertain Terrain Extender histories, weather, other
pseudo-weather, side conditions and unfinished-turn replacement queues.
This implementation review does not replace the independent #240 milestone
review. No deployment, commit or push was performed for this update.
