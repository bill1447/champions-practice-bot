# Full-game rerun after inventory restoration — 2026-10-15

The inventory-enabled experimental player still wins **15/24**, versus frozen V2's **10/24**. Every individual win/loss outcome is unchanged from the original native experiment. Search coverage improves, including after turn four, but this run demonstrates **no additional playing-strength gain**.

All **48 games completed**, with no opponent-adapter fallback, deadline fallback, native decision exception or eight-second overrun. The original archive was preserved and its digest verified.

## Matched protocol and evidence

This is the same examined 24-pair matrix: six composition pairings, two independent upstream opponent algorithms, two hidden families, identical previews, sides, battle seeds and opponent seeds. Both arms were played again as complete games. Frozen V2 remains `e0ae723`; the candidate uses the inventory implementation at `93c73e1`. The installed dependency is the same `poke-env` 0.16.1 recorded in the original trial.

The comparator verifies equality of the complete case matrix, baseline identity, team hashes, independent-opponent identity and eight-second / one-turn / 8-own / 3-response protocol. It also verifies the current candidate source against a supplemental provenance snapshot covering every package Python source, the harness and native worker. Every V2 game's winner, public observations, legal menus, own actions, opposing actions and opponent trace exactly matches the original trajectory: **24/24 V2 trajectories identical**.

Position utilities, strategic weights, search breadth, horizon and priors are unchanged. Public strategy and route assessments remain diagnostic only. No experimental player was promoted. This is a same-case regression comparison, not an independent replication or unfamiliar-team strength test.

## Full-game comparison

| Metric | Original native run | Inventory-enabled run |
| --- | ---: | ---: |
| Native wins | 15/24 | 15/24 |
| Frozen V2 wins | 10/24 | 10/24 |
| Native-only / V2-only winning pairs | 5 / 0 | 5 / 0 |
| Completed native searches | 73/163 (44.8%) | 79/166 (47.6%) |
| V2 action disagreements | 51 | 55 |
| Searches from turn 4 onward | 6/64 (9.4%) | 12/67 (17.9%) |
| Fallback decisions | 90 | 87 |
| Mean total decision latency | 0.360 s | 0.379 s |
| p95 total decision latency | 1.192 s | 1.181 s |
| Maximum total decision latency | 1.607 s | 1.641 s |
| Eight-second overruns | 0 | 0 |

Coverage denominators change because two native games take different paths and run longer. The six additional completed searches are not six independent recovered positions on an unchanged trajectory. The earlier fixed-position replay remains the direct evidence for four recovered retained checkpoints.

| Turn | Original searches / actionable | New searches / actionable |
| --- | ---: | ---: |
| 1 | 24/29 | 24/29 |
| 2 | 29/41 | 29/41 |
| 3 | 14/29 | 14/29 |
| 4 | 4/31 | 5/31 |
| 5 | 1/21 | 3/21 |
| 6 | 1/9 | 3/10 |
| 7 | 0/3 | 1/5 |

Move-phase search completes at 65/129 checkpoints; replacement search at 14/37. The same limits still prevent most later-game decisions from using native search.

Opponent/family outcome totals also remain unchanged: SimpleHeuristics 6/12 versus V2 4/12; MaxBasePower 9/12 versus 6/12; prior family 8/12 versus 5/12; shifted family 7/12 versus 5/12. The two opponent algorithms share the same adapter and lack Mega augmentation, as documented in the original experiment.

## Where the player changed

Only **two of the 24 native trajectories diverge**. Both first divergences occur at identical public positions with identical realized opposing replies, where the old player fell back on the inventory gate and the new one completed search. Both games were wins before and remain wins.

- **Development Armarouge support / grass balance, shifted family, SimpleHeuristics, turn 5:** the old action is Expanding Force + Energy Ball; the new action is Expanding Force + Protect. Sampled worst utility favors the new action 77.54 versus 11.86. Venusaur remains at full HP after the turn. The new game later uses Sleep Powder, then falls back when sleep becomes unsupported. The trajectory grows from 9 to 10 checkpoints and finishes on turn 7 instead of turn 6.
- **Validation Armarouge pivot / grass water, shifted family, SimpleHeuristics, turn 5:** the old action is Flare Blitz + Armor Cannon; the new action is Flare Blitz + Protect, preserving Armarouge at 2.1% HP against Darkest Lariat. The following search switches Armarouge out for Venusaur. The trajectory grows from 7 to 9 checkpoints and finishes on turn 7 instead of turn 5.

These are retained preservation-versus-finishing counterexamples, not evidence that the new defensive choices are objectively better or worse. Both still win, and changed paths consume RNG differently. They make useful targets for evaluating whether leaf utility rewards saving material more than converting an available finish. No weights were adjusted in response.

## Remaining fallbacks

The ordinary inventory reason disappears on these trajectories; other strict gates now report first. New totals are opponent capabilities 30; active Electro Shot 18; active Stomping Tantrum 11; confusion 11; Flash Fire 5; turn-one replacement phase 5; sleep 3; active Phantom Force 3; owned Unburden 1. Those sum to **87 fallbacks**.

These are first-reported reasons, not independent defects. Inventory previously masked some capability failures, and changed trajectories introduce different observations. The increase in other labels is not evidence of a mechanical regression. The 17 incompatible-source-item checkpoints in the separate fixed-position audit remained closed; the priors were not expanded for this rerun.

## Artifacts and validation

- Original raw archive: `runs/v2-full-game-native/frozen-v2/games.json.gz`.
- New raw archive and frozen protocol: `runs/v2-full-game-native/inventory-v1/games.json.gz` and `manifest.json`.
- Expanded source/commit/control-archive provenance: adjacent `inventory-provenance.json`.
- Tracked candidate audit and all changed-decision forensics: `reviews/v2-full-game-inventory-2026-10-15.json`.
- Tracked matched comparison, all native outcome transitions, first divergences and source hashes: `reviews/v2-full-game-inventory-comparison-2026-10-15.json`.
- Comparator: `scripts/full_game_inventory_comparison.py`; Ruff passes. The data audit confirms legal selected actions, V2 retention on every fallback, admitted roots and route telemetry for every completed search, matched source hashes and all completed games. The underlying implementation already passed 1,746 tests at this code state; no player implementation changed during this rerun.

Raw archives and model files remain untracked. No new game outcomes are pooled into the original result. The useful result here is a bounded coverage improvement with preserved outcomes, while late admission and decision quality remain open work.
