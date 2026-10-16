# Stomping admission repair: same-position probe and full-game regression

The repaired player wins **21/24**, versus frozen V2's unchanged **16/24**, on the existing Mega-capable suite. The previous native run won 16/24. Six old native losses became wins and one old native win became a loss. This is a promising regression result on inspected cases, **not fresh playing-strength evidence**.

No strategic weight, production prior, search width, response count, opponent policy, team selection or seed changed. The experimental Earthquake-prior expansion was not used. The mechanical repair is preserved separately in `71f530e`.

## Exact old positions: what became usable?

The separate same-position probe reconsidered exactly the 67 originally Stomping-blocked decisions, using their original public histories and legal menus. Shadow decisions were not executed and could not change later probe positions.

| Original blocked context | Probed | Search completed | Different from V2 |
| --- | ---: | ---: | ---: |
| All Stomping fallbacks | 67 | 46 | 34 |
| Last own Pokémon | 4 | 4 | 0 |
| Low-HP active | 17 | 13 | 10 |
| Replacement pause | 16 | 0 | 0 |

Tags overlap. These are the Stomping-blocked subsets, not all 11 last-Pokémon or all 23 low-HP decisions in the old suite. Of the 21 remaining probe fallbacks, 16 are replacement pauses intentionally outside the new result contract, four expose the existing Phantom Force gate and one exposes an opening-weather-source gate. A completed result certificate does not bypass those gates.

The maximum same-position decision latency was **1.402 seconds**, with no eight-second overrun. All four rescued last-Pokémon decisions agreed with V2. Availability alone did not demonstrate a correction in those four positions.

## Full-game replay

All 48 games completed. The 24 frozen V2 trajectories matched the original control exactly, including public views, commands and opponent traces. A separate audit replayed all 48 new complete trajectories exactly. Opponents visibly Mega Evolved in every game.

| Measure | Before repair | Repaired |
| --- | ---: | ---: |
| Native wins / 24 | 16 | 21 |
| Frozen V2 wins / 24 | 16 | 16 |
| Native search / actionable decisions | 34/148 (23.0%) | 93/154 (60.4%) |
| Native search after turn one | 10/124 (8.1%) | 69/130 (53.1%) |
| Native search, turn four or later | 2/47 (4.3%) | 35/64 (54.7%) |
| Last own Pokémon search | 0/11 | 2/4 |
| Low-HP active search | 1/23 | 19/28 |
| Replacement-context search | 5/33 | 5/27 |
| Action disagreements | 23 | 77 |
| Maximum full-game decision latency | 1.057 s | 1.106 s |
| Eight-second overruns | 0 | 0 |

Full-game denominators differ because decisions change battle paths. Use the fixed-position probe to measure direct admission recovery. Do not describe the new last-Pokémon 2/4 as recovering two of the original eleven positions.

| Turn | Repaired completed search / actionable |
| --- | ---: |
| 1 | 24/24 |
| 2 | 21/29 |
| 3 | 13/37 |
| 4 | 14/27 |
| 5 | 9/18 |
| 6 | 5/11 |
| 7 | 4/5 |
| 8 | 3/3 |

On the 23 pairs without any opponent adapter fallback, native wins 20 versus V2's 15. This subset differs from the old fallback-free subset because paths differ; it is not a separate replication. The six composition results are native/V2 4/2, 4/3, 2/3, 4/4, 3/0 and 4/4, each out of four. The formerly 0/4 composition improves to 3/4, while one rain composition loses a previously won game.

Remaining full-game fallbacks: public effect durations 17; Phantom Force 13; Stomping replacement pauses 12; confusion 11; protection residual effects three; own-speed projection mismatches three; opening weather source two. These are preserved rejections, not permission to guess hidden state.

## Consequences: what improved, and what remains unproven?

Every changed-outcome native game first diverged at the same public position against the same recorded opponent reply, where the old player fell back for Stomping and the repaired player completed search. All seven first divergences are retained in the JSON report. This connects the trajectory changes to restored admission; it does not prove each new action is optimal.

The exact-position consequence probe retained **all 46 newly completed decisions**, including the 12 that agreed with V2. It compared incumbent and native actions against the recorded reply using the recorded RNG stream plus four coupled labels: 230 paired cells, of which 170 compare different commands. It found **zero immediate terminal-win or terminal-loss differences**. The probe resolves one native step, not a continuation or all opponent replies. It does not grade nonterminal positions as better merely because material or generic utility increased.

Two useful nonterminal witnesses:

- In `fresh-mega-1-prior-0-native`, turn two changed Steel Roller + Thunderbolt to Steel Roller + Protect. Rotom survives in all five checked outcomes; with Thunderbolt it faints in all five. Both lines remove the same opposing Pokémon in those checks. The repaired full game wins, whereas the old native path loses. This is conditional preservation evidence, not proof that Protect caused the complete-game win.
- In the regressed `fresh-mega-2-prior-0-native`, turn two changed Tailwind + Mystical Fire to Tailwind + switching Gardevoir for Basculegion. Switching preserves Gardevoir in all five checks; attacking loses it in four. Nevertheless, the repaired complete path loses while the old attacking path wins. This is a concrete candidate for a continuation experiment: preserving material is not sufficient evidence of a better route to victory. Neither branch ends the game immediately, so the present probe cannot attribute the defeat to that root choice.

These outcomes justify retaining the mechanical repair and investigating consequential late-game decisions. They do not justify a Protect penalty, a sacrifice bonus, new strategic weights or promotion to a competent full-game player.

## Public contract and validation

See `stomping-contract-2026-10-16.md`: the native doubling predicate is exactly false, distinct from success, Protect's null result and switch-reset absence. Ambiguous/missing history remains rejected. Current-turn result reconstruction at replacement pauses remains outside scope.

The original public-history audit verified **833 native fields**, and the new-path audit verified **883**, both with zero certificate mismatches. Counts include both game arms and all four ordinary result values; unresolved histories are not counted as verified. No native truth enters the classifier, admission or player; posthoc drivers read it only after sealing public decisions.

**111 targeted tests passed**, including native damage, public menu/projection equivalence, latent-field corruption, flinch, Mega, missing/ambiguous histories, Charcoal/weather/speed controls and all three retained continuation regressions. Changed Python lint, worker syntax and whitespace checks passed.

## Artifacts and next experiment

- Frozen control identity, source hashes, cases, teams and protocol: `reviews/stomping-replay-manifest-2026-10-16.json`.
- Audited summaries, all 67 probe decisions, first divergences and 46 consequence witnesses: `reviews/stomping-replay-results-2026-10-16.json`.
- Ignored local archives: `runs/stomping-admission/replay-v1/results.json.gz`, `public-result-audit.json` and `rescue-forensics.json`.
- Reproduce from this experiment's source checkpoint with `PYTHONPATH=src python scripts/stomping_replay_evaluation.py evaluate --output runs/stomping-admission/NEW`; run `stomping_rescue_forensics.py` and `stomping_replay_report.py` for the sealed default archive.

The gameplay/source checkpoint is `796ec52`. A subsequent diagnostic-only follow-up passes the public ledger to the older admission-audit and human-Mega smoke prechecks, aligning them with the controller's new certificate requirement. It does not change player decisions or the frozen experiment. The human-Mega smoke passed: eight decisions, intact public ledger, one search, one forced wait and six correctly predicted safety fallbacks. Reproduce frozen source-hash checks at the gameplay checkpoint; do not rewrite the manifest to match later diagnostic edits.

Next, freeze a separate late-game diagnostic with response-diverse immediate-win/loss checks and controlled continuations for the retained switch-versus-attack regression. Then add a second independently implemented tactical opponent before a fresh full-game strength evaluation. Team-preview selection remains a separate roadmap item. None of these tests should infer a general strength gain from the reused 24 pairs.
