# Playable reliability: replacement recovery — 2026-10-10

This update recovers search for ordinary end-of-turn replacements and repairs an
own fainted-slot mismatch. It does not establish broad competitive strength or
full terrain support.

## What the player gains

After a Pokémon faints, the bot can now compare replacement choices using its
search system when the public protocol proves the turn's residual has finished.
Previously those checkpoints fell back under a misleading protection-history
reason. Every such protection-history fallback in the preceding two eight-game
reports was a replacement checkpoint containing current-turn events, not a
missing public history.

An own Pokémon can remain in an active slot after fainting while its `isActive`
flag becomes false. The constructor previously compared that flag before native
faint processing cleared it. The check now runs after native faint resolution.
A fainted Mega in that slot also bypasses unnecessary benched-Mega staging once
the native active-form pass has established its form.

## Public evidence and native operations

The sanitized event producer retains the channel-visible `upkeep` event. A current
replacement request is admitted only when its current delta ends at that marker
and has no unsupported event. Earlier completed turns still require complete
ordered history. Mid-turn pivot, eject and other unfinished action queues remain
unsupported with `unsupported-public-switch-boundary`; no historical move queue
is fabricated or copied.

The constructor establishes the replacement pause with pinned `turnLoop()` and
native faint processing before restoring current owned HP/status/field. This
produces the native empty queue, mid-turn resume flag and forced-switch request.
The existing native stall lifecycle runs once. Exact owned request/projection,
current field, public opponent constraints, legal menu and serialization checks
remain admission requirements. Unrepresented worlds remain unresolved.

Terrain age now counts public upkeep occurrences after its activation. A Surge
start during a replacement happens after the old turn's residual; subtracting
turn labels overcounted its age by one. The frozen native regression includes
that activation and its later one-turn remainder. Legacy observation controls
without upkeep markers retain the earlier bounded opening/start path.

## Validation

All 1,502 pytest tests passed; Ruff, native worker syntax and diff checks passed.
Native protection, own Mega, terrain, present-mechanics, execution-evidence,
execution-authority and sealed-transition controls passed. The new replacement
control covers both sides replacing, one side waiting, a fainted Mega, a fainted
member retained with no reserve, and a final team with one living member. It
compares exact own state and legal choices, native terrain duration, native
serialization and replacement continuations. Resuming advances one turn without
processing a second residual. Removing the public boundary rejects construction.
Independent production projection admission also passed for the three repaired
checkpoints.

The human Mega regression made eight search decisions in eight decisions with
zero fallbacks (the preceding run had six searches, one fallback and one wait).
That trajectory changed, so counts are evidence of the new behavior rather than
a claim that a wait itself was an error.

Both final source-bound runs completed. Configuration remained eight battles per
frozen fixture, seed 15601 and an eight-second decision budget. Winning record is
secondary to search coverage, fallback causes, legal decisions and response time.

| Fixture | Previous update | This update | PR 236 reference |
| --- | ---: | ---: | ---: |
| Current roster mirror | 7/54 (13.0%) | 0/48 (0.0%) | 5/51 (9.8%) |
| Synthetic spread uncertainty | 10/67 (14.9%) | 6/64 (9.4%) | 13/92 (14.1%) |

Reported fallback rates use all decisions, including forced waits, consistently
with the preceding league reports. Among decisions requiring an action, search
coverage was 34/34 in mirror and 47/53 in synthetic. The native engine required
14 and 11 forced waits respectively; those are normal protocol waits. Search
handled one mirror replacement and four synthetic replacements. One remaining
synthetic replacement fell back because Trick Room was active.

Mirror searched 43,198 branches; synthetic searched 52,078 branches. The 95th
percentile decision time was 7.781 seconds and 7.777 seconds respectively. All
six remaining fallbacks were explicit support gates: three copied terrain-source
cases and three active Trick Room cases. No unsupported protection-history,
exact own ability or own active-flag rejection occurred in these final runs.

Reports are `runs/strength-league/184f0be443f074ef8d1b/report.json` and
`runs/strength-league/0921cc1d6634eece262c/report.json`. They record parent commit
`d3800abb70d0050efea075d5e15e5098da912d4d` and bind the uncommitted runtime sources
with a source fingerprint. No runtime source changed during these measurements.
The bot completed all games (mirror 8–0; synthetic 7–1). Small samples, changed
trajectories and wall-clock budgets limit causal and strength claims; the
recovery and native regression controls are the main acceptance evidence.

## Remaining scope

The next measured blockers are borrowed terrain-source abilities (Trace copying
a Surge ability) and Trick Room duration/cache reconstruction. Uncertain Terrain
Extender inventories remain unsupported. Weather, pseudo-weather, side conditions and ambiguous
protection histories still have explicit gates. A self-authored implementation
review does not replace the independent #240 milestone review. No deployment,
commit or push was performed for this update.
