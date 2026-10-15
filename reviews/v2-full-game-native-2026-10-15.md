# Full-game experimental native player — 2026-10-15

The experimental player won **15/24** frozen paired cases, versus unchanged V2's **10/24**. Five pairs improved and none regressed. All 48 games completed, and neither independent opponent needed adapter fallbacks. This is promising evidence for the wrapper, not proof of competitive strength or of each changed action's quality.

## Decision contract

`ExperimentalNativePlayer` accepts an owned team, approved public priors, a public observation and its authoritative menu. It has no live session handle, actual opponent team, actual RNG seed or future opponent command. V2 at `e0ae723` is computed first and remains the legal incumbent.

Every actionable checkpoint attempts public-only native admission. Opening conditioning uses the existing two explicit public team-family hypotheses. Later checkpoints use fresh present-state reconstruction with the public ledger and source-bound `PublicOriginWorker`. No old belief-controller conditioning cycle runs. Unsupported mechanics and unsupported phase boundaries retain V2.

Worker startup, admission, one-turn **8/3** consequence search, route diagnostics and process cleanup share one absolute **eight-second deadline**. The existing abortable native-worker lifecycle reserves 0.25 seconds for cleanup; there is no second preparation budget. Incomplete comparisons, exceptions and late results retain V2. Forced waits update public history and diagnostics without launching a search.

Search uses the corrected effective-Speed contract and unchanged position utilities, aggregation, candidate limits and strategic weights. The strategic planner and competing-route comparisons are telemetry only. Native leaf positions and all sampled response utilities are retained, alongside the V2 incumbent, selected action, admission reasons, public assessments, actual subsequent observations and final outcomes. Recorded actual replies and outcomes are offline forensics and never enter the player.

## Frozen experiment

Six existing own/opponent composition pairings × two independently implemented upstream algorithms (`poke-env` SimpleHeuristics and MaxBasePower) × two hidden families = **24 pairs / 48 games**. Full games use either V2 everywhere or the experimental wrapper everywhere; the latter continues attempting admission after an earlier failure.

Both arms receive identical live team selections, battle seeds and opponent policy seeds within a pair. The own preview is fixed at 1234. The shifted family replaces opposing Protect with Substitute, replaces Life Orb with Sitrus Berry, and selects 1256; those actual choices are confined to the live driver. The opening hypotheses and approved midgame catalog are frozen separately and are not expanded after hidden moves are revealed.

These are familiar species and previously examined composition templates, with new battle seeds, rather than unseen-team competitive validation. Hidden family also covaries with side and selected bench. Branching paths change subsequent RNG consumption. The two upstream algorithms share the same public adapter and have no Mega augmentation. Outcomes across these related cases are not a rating or an independent estimate for each tactical change.

| Sample | Pairs | V2 wins | Native wins |
| --- | ---: | ---: | ---: |
| All; also opponent-fallback-free | 24 | 10 | 15 |
| SimpleHeuristics | 12 | 4 | 6 |
| MaxBasePower | 12 | 6 | 9 |
| Prior family | 12 | 5 | 8 |
| Shifted hidden family | 12 | 5 | 7 |
| Existing development compositions | 12 | 5 | 7 |
| Existing validation compositions | 12 | 5 | 8 |

## Can it search through a battle?

There were **163 actionable decisions** and 27 forced-wait checkpoints in the experimental games. Admission and search both completed at **73/163 (44.8%)** actionable checkpoints: 60/126 move decisions and 13/37 replacement decisions. All 90 other actionable decisions retained V2. Search changed V2's choice **51 times**: 31.3% of actionable decisions, or 69.9% of completed searches.

| Turn | Actionable checkpoints | Completed searches | Disagreements |
| --- | ---: | ---: | ---: |
| 1 | 29 | 24 | 20 |
| 2 | 41 | 29 | 16 |
| 3 | 29 | 14 | 10 |
| 4 | 31 | 4 | 3 |
| 5 | 21 | 1 | 1 |
| 6 | 9 | 1 | 1 |
| 7 | 3 | 0 | 0 |

The denominator includes replacement checkpoints, so a turn can appear more than once per game. Midgame coverage is **49/134 (36.6%)** for turn two onward, falling to **6/64 (9.4%)** from turn four onward. This is a full-game experimental player with increasingly frequent fallback, not a consistently available full-game native search player.

Fallback reasons: unsupported opponent inventory 29; active Electro Shot 15; opponent capabilities 11; confusion 11; active Stomping Tantrum 9; Flash Fire volatile 5; turn-one replacement phase 5; active Phantom Force 3; sleep 2. No deadline fallback or native exception occurred in the corrected matrix. These gates were not loosened to inflate coverage. The next admission investigation should explain the inventory/capability rejections before considering support changes.

## Practicality

Measured total actionable latency includes canonical public-view preparation, V2, public history, worker startup, admission, search, diagnostics and cleanup. Mean **0.360 s**, p95 **1.192 s**, maximum **1.607 s**. **Zero** measured decisions exceeded eight seconds. The hard-budget regression also forces blocked preparation and verifies abort, V2 fallback and worker-thread exit; ordinary gameplay did not stress the deadline.

## Decision forensics

The compact JSON report retains all **51** changed-decision cases with both candidate utilities, the realized opposing reply, next public events/owned HP and final result. The raw archive additionally retains complete candidate rankings, response branches, leaf positions and route assessments.

- **Armarouge pivot vs grass/water, SimpleHeuristics, prior family:** V2 loses; the experimental player wins. Search opens with Trick Room + Protect. The next public position has Trick Room active, Armarouge at full HP and Indeedee at 55.9%. Turn two changes Psychic + Armor Cannon to Follow Me + Armor Cannon: Rillaboom faints and Hydro Pump is redirected into Indeedee. Turn three's Expanding Force and Psychic remove Rotom and the incoming Pelipper. This provides a concrete setup payoff, without adding a Trick Room bonus or using the diagnostic planner to choose.
- **Same composition, MaxBasePower, shifted family:** both arms lose. Search again sets Trick Room, then selects Follow Me + a second consecutive Protect. Protect fails; Wood Hammer removes Indeedee and Hydro Pump removes Armarouge. The selected and another candidate tie at roughly -1061.4 sampled worst utility. The trace exposes an unresolved risk/response-evaluation problem despite exact native mechanics. A living finisher or an established Trick Room is not a certificate of a usable attack opportunity.
- The same opening appears in both winning and losing cases. The outcomes justify retaining the counterexamples and testing additional seeds/responses; they do not justify crediting an opening label, a particular changed move, or the strategic planner with the aggregate improvement.

## Validation and provenance

**1,731 tests passed**; targeted Ruff and Node syntax checks passed. Deadline regressions cover shared absolute time, rejection before search, late-result discard, blocked preparation abort, forced waits and public-ledger rejection. All 190 experimental incumbents were recomputed from their original side's public view and exactly matched frozen V2, checking canonical relabeling parity.

The first frozen matrix exposed a public-menu mechanics bug: two fainted actives with one reserve incorrectly offered `pass, pass`. The shared public structural validator now requires exactly the available number of ordinary replacements, derived only from the owned request. A deterministic native battle regression verifies both legal one-switch alternatives and successful submission. This changes no move scoring. It applies equally to both arms of the corrected rerun.

- Authoritative corrected archive: `runs/v2-full-game-native/frozen-v2/games.json.gz`; frozen protocol/cases/source hashes: adjacent `manifest.json`.
- Failed first trial retained at `runs/v2-full-game-native/frozen-v1`; 47 complete / 1 failed. Its outcomes are not pooled with the corrected trial. Smoke trials are also excluded.
- Condensed statistics, archive hash, source hashes and changed-decision evidence: `reviews/v2-full-game-native-2026-10-15.json`.
- Reproduce play: `PYTHONPATH=src python scripts/full_game_native_evaluation.py --output runs/v2-full-game-native/new-run --pairs 24`.
- Audit/condense: `python scripts/full_game_native_report.py --archive runs/v2-full-game-native/frozen-v2/games.json.gz --output reviews/v2-full-game-native-2026-10-15.json`.

Keep this experimental. The clearest demonstrated advances are useful early-midgame interventions and a measurable whole-game improvement in this sample. The strongest remaining limitations are collapsing later admission, narrow hidden-world/response coverage, and risk-sensitive evaluation. None is resolved by these results, and no strategic-score changes are warranted by this experiment alone.
