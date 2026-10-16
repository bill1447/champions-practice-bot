# Fresh full-game evaluation with Mega-capable opposition

Native and frozen V2 each won **16/24** paired games. Native gained one win and lost one. This fresh suite does not replicate the earlier playing-strength advantage. All 48 games completed and exactly replayed from their recorded commands, seeds and public views.

| Measure | Result |
| --- | --- |
| Completed native search | 34/148 actionable decisions (23.0%) |
| Different from V2 | 23/148 decisions |
| Search after turn one | 10/124 decisions (8.1%) |
| Search at turn four or later | 2/47 decisions (4.3%) |
| Last remaining own Pokémon | 0/11 searches |
| Low-HP active context | 1/23 searches |
| Maximum decision latency | 1.057 seconds |
| Eight-second overruns | 0 |
| Opponent Mega commands / publicly observed Mega forms | 48 / 48 games |
| Pairs without opponent adapter fallback | 22; native 14 wins, V2 14 wins |

## Frozen protocol

Six new six-Pokémon lineup pairs, two seeds/sides and two hidden families produced 24 paired comparisons. Both arms used the same battle seed and opponent seed per pair. V2 is frozen at `e0ae723`. The native arm used the existing public-only player, shared eight-second preparation/search budget, one-turn 8/3 search, unchanged production prior catalogue and unchanged strategic weights. **No experimental Earthquake-prior expansion** entered these games.

The independent opponent is upstream poke-env SimpleHeuristics with an evaluation-only legal Mega completion. Its move/target proposal is preserved; the adapter adds a Mega modifier only if that exact completion exists in its own authoritative legal menu. This implements Mega behavior, but does not establish that the opponent is stronger than its predecessor. Three upstream adapter ValueErrors triggered explicit legal fallbacks across two pairs; both all-pair and fallback-free results are reported.

The hidden family changes Protect to Substitute and Life Orb to Sitrus Berry, and selects 1256 instead of 1234. Replicate balances side independently of family. Own selection remains 1234. Species, individual base sets and opening hypothesis families remain familiar. This is synthetic evaluation against one opponent algorithm, with fixed team selection; it establishes no ladder rating or broad competence.

## Where search disappears

| Turn | Search completed / actionable |
| --- | --- |
| 1 | 24/24 |
| 2 | 4/40 |
| 3 | 4/37 |
| 4 | 2/26 |
| 5 | 0/15 |
| 6 | 0/6 |

Stomping Tantrum certification caused 67 fallbacks. Other reasons were public effect durations (19), confusion (10), Phantom Force (8), opponent inventory (8), opponent capabilities (1), and one public own-speed mismatch. These are admission outcomes, not demonstrations that any rejected decision would benefit from search. Context tags overlap and describe public situations, not certified tactical importance. In particular, no last-Pokémon decision received native search.

One composition was 0/4 for both players, while two were 4/4 for both. The prior-family stratum was native 6/12 versus V2 7/12; the heldout-family stratum was native 10/12 versus V2 9/12. No aggregate gain should be claimed.

## Changed-outcome forensics

After sealing all games, the report reconstructed both discordant pairs and compared every changed native action with its incumbent at the *same actual position*, against the recorded opponent reply. Each comparison used the recorded RNG stream plus four coupled diagnostic labels. No driver truth entered player decisions. These checks resolve one simulator step, including any resulting replacement request; they do not establish a winning continuation or cover other counterplay.

- **Gained game, `fresh-mega-0-heldout-0`:** native changed three actions. At turn three, Hyper Voice + Wood Hammer removed Excadrill in all four additional coupled samples, while Expanding Force + Wood Hammer removed it in none. Both removed it under the recorded stream. This is a useful conditional conversion witness, not an isolated explanation of the full-game win. At turn four, Protect + Wood Hammer and Hydro Pump + Wood Hammer both won immediately in all five checks. Do not attribute the gained game to that final Protect.
- **Lost game, `fresh-mega-1-prior-0`:** the sole native disagreement was opening Hydro Pump instead of Thunderbolt, alongside the same Mega Steel Roller. Both actions removed Gardevoir and remained nonterminal in all five checks. The generic utility ordering varies with RNG. The complete paths later diverge, but these one-step facts do not identify an incorrect strategic weight or establish that Hydro Pump was the cause of defeat.

The next decision-quality investigation should retain the lost opening and its later fallback positions. The new suite supplies no reason to penalize Protect or redesign strategic weights. A follow-up opposition suite should add an independently validated second algorithm, and any admission repair should be judged on the decisions it rescues rather than its coverage count.

## Mechanical checkpoints and regressions

Charcoal remains independently reviewable at `aff7b8a`; opening-weather reconstruction remains at `0f05f8a`, with source-flag controls at `cb4f4bb`. No production source changed for this experiment. The Earthquake prior overlay remains confined to its explicit experimental profile.

`tests/fixtures/native_continuation_regressions.json` preserves one strictly matched witness for each retained capability, with team texts, public-history reconstruction seeds, root actions, RNG labels and opposing schedules. `tests/test_native_continuation_regressions.py` reconstructs each case and actually invokes the public-only native player. It requires completed search, disagreement and the retained terminal outcome, while separately reproducing V2's terminal result. The three cases cover avoiding a sampled terminal loss, converting the defensive root to a terminal win, and converting an alternative attacking route. They depend on neither ignored raw archives nor serialized hidden-state patches, and retain their explicit experimental prior profile. They are regression witnesses, not independent strength evidence or universal action labels.

## Reproduction and artifacts

- Frozen inputs and source hashes: `reviews/mega-opposition-manifest-2026-10-16.json`.
- Audited summary, per-pair disagreements and conditional branches: `reviews/mega-opposition-results-2026-10-16.json`.
- Raw local archive: `runs/mega-opposition/v1/games.json.gz` (ignored).
- Evaluation: `PYTHONPATH=src python scripts/mega_opposition_evaluation.py evaluate --output runs/mega-opposition/NEW`.
- Audit: `PYTHONPATH=src python scripts/mega_opposition_report.py`.

Do not overwrite the frozen manifest or count reruns as additional evidence.

Validation: 40 targeted tests passed across Charcoal, public weather, native speed, the experimental prior boundary, opponent adaptation and the three continuation regressions. The audit reproduced all 48 complete games exactly. Ruff passed for the new tests and report script; the already-frozen evaluation script passes with its single E731 lambda-style exception excluded. No production source or scoring weight changed.
