# Competing plans and native consequences — 2026-10-15

The comparison found a concrete interface defect: the Champions native summary reports Trick Room-adjusted action speeds, while the evaluator treats them as unreversed effective speeds and reverses their comparison again. This changes the preferred opening in one retained position when normalized offline. It is not a demonstrated gameplay improvement, and the scorer remains unchanged.

## Experiment boundary

Use two already examined psychic/sand counterexamples: `development-0-0-p1` and `validation-1-1-p1`. For each, retain all eight original commands, the same three opponent replies per world, and the original two public-conditioned set/bench hypotheses. Four root RNG samples are coupled across own commands; the first is the original control seed. No live sessions, actual hidden sets, truth RNG, recorded enemy commands, or winners enter this experiment.

This yields **384 opening scenarios**, not full games. At each resulting next-turn position, probe at most eight legal joint commands against the same three reply proposals for every command, with one coupled continuation RNG sample per pair. Native mechanics, legal menus, unchanged scorer, and the existing public-only shortlist are used throughout. Frozen V2 on each side's view completes intervening replacement/pivot phases, capped at six. The experiment completed **16,448 native branches**, including those phases. No new gameplay policy or search depth/coverage setting is deployed.

The continuation probe is a separate diagnostic sweep, not the previous two-candidate continuation backup or an optimized full-game player. Root responses/worlds are identical across competing lines; later legal menus and reply proposals can change with the resulting board. No hypothetical-world-specific continuation is selected for play. A witness or common action inside one world is not a certified information-set policy across worlds.

## Competing routes

The public diagnostic now keeps Gardevoir, Metagross and Armarouge routes where present, plus a remaining-material-exchange hypothesis. It removes unconditional preservation of the reference centerpiece. Each route requires entry/position, relevant damage and an actionable speed/survival window; living alone verifies none of them. Fainted or unselected resources are marked unavailable. The reference anchor remains for continuity/display, not a winning-plan selection. No mechanism yet proves a living route globally infeasible or chooses the best competing plan.

Armarouge is not selected in either retained opening, so it cannot be credited with an attacking opportunity here. This is a useful explicit rejection rather than an invented alternative. Metagross is selected and can become the attacking route.

The eight commands cover overlapping plan hypotheses:

| Plan hypothesis | Retained lines |
| --- | --- |
| Immediate offense | Psychic + Mystical Fire |
| Weaken/remove Excadrill | Mystical Fire + Follow Me; attacks coordinated into the blocker where legal |
| Speed control | Trick Room + Protect; Trick Room + Mystical Fire |
| Defensive repositioning | Protect + Psychic/Follow Me; switch to Metagross + Psychic; switch support + Mystical Fire |

These labels do not add scores or bonuses. Setup is not credited merely for activating Trick Room, and a support loss is not automatically treated as a useful sacrifice.

## What was measured

Retain surviving roster/active identities and HP, actual knockouts, Tyranitar/Excadrill remaining HP, native ordering-speed values, field state, and resolved move order. Direct damage is attributed to the native move event; recoil/residual provenance is excluded and split log duplicates are removed. A productive surviving attack means the named attacker directly damages an opponent and remains alive at completed-turn end. KO/trade outcomes are separately available, so this measurement does not prescribe preservation.

For the next turn, report both a witness and whether **one same joint command** produces that attack against all three sampled replies. This is only a bounded scenario result. It is neither a win probability nor a guarantee against unsampled responses/RNG. Count all legal damaging commands separately from those probed, so shortlist omission is not mistaken for impossibility. That coverage instrumentation was added after inspecting the first pass, then the unchanged paired branches were rerun; it was not a preselected strategic success criterion.

Selected results, each line containing 24 correlated opening scenarios:

| Position / line | Mean first-turn utility | Mean Excadrill HP remaining | Next-turn common productive Gardevoir action | Same for Metagross |
| --- | ---: | ---: | ---: | ---: |
| Development: Psychic + switch Gardevoir → Metagross (control) | -19.3 | 79% | 0/24 | 6/24 |
| Development: Trick Room + Protect | -28.4 | 100% | 7/24 | 0/24 |
| Development: Psychic + Protect | -8.1 | 83% | 7/24 | 0/24 |
| Development: Follow Me + Mystical Fire | 91.0 | 42% | 11/24 | 0/24 |
| Validation: Protect + Trick Room (control) | -27.3 | 100% | 3/24 | 0/24 |
| Validation: Mystical Fire + Follow Me | 44.0 | 44% | 9/24 | 0/24 |
| Validation: switch Gardevoir → Metagross + Psychic | -30.3 | 79% | 0/24 | 0/24 |

These means are descriptive scenario averages, not opponent probabilities or the control's worst-case selection rule. Follow Me + Mystical Fire knocks out an opponent in 7/24 development and 6/24 validation scenarios, while losing an own resource in 5/24 in each. That tradeoff must remain visible rather than being hidden inside a strategic label.

Switching Gardevoir out leaves it alive in all 24 scenarios but with **zero legal damaging commands for the immediately following turn**. That disproves a Gardevoir-attacks-next-turn requirement in that state; it does not disprove a later Gardevoir endgame. The development Metagross witnesses show why discarding the line solely for failing the original finisher's immediate requirement would be wrong. In validation, failure to find a common productive Metagross attack likewise does not establish that its route is impossible.

Trick Room is not a universal Gardevoir speed advantage. A retained native next-turn trace resolves Indeedee's Psychic, Tyranitar's Crunch, then Gardevoir's Mystical Fire. Tyranitar can act before Gardevoir under Room even though sand-boosted Excadrill's relative order improves for Gardevoir. The measured native ordering speeds in that frame are Indeedee -96, Tyranitar -113, Mega Gardevoir -150, Excadrill -280. These are encoded ordering values, not negative raw stats.

## Concrete evaluator defect

Pinned source `external/pokemon-showdown/data/mods/champions/scripts.ts` implements `getActionSpeed()` by negating effective speed in Trick Room. `tools/showdown-search-worker.js:summarize` exports `mon.speed`. `exact_search.py:_speed_position_value` then negates the difference again whenever Room is active.

In the retained Protect + Trick Room frame, the average native ordering difference gives the existing scaled term **+14.7**, but the evaluator reports **-14.7**. The audit verifies signed native values and this reversal against the first control RNG sample across both positions. This is a semantic contract mismatch, not a new strategic weight proposal or a simulator turn-resolution error.

Offline, correcting only that double inversion changes development's preferred first-sample worst-case line from Psychic + switch (utility -39.97) to Trick Room + Protect (-14.82 after normalization). Validation retains Protect + Trick Room. The production scorer is untouched. Replacement phases use this experiment's frozen-V2 completion, which can differ from the older search's continuation backup; same-seed frames with no such phase reproduce the saved scalar utilities exactly. This comparison does not establish that the new preference wins more games.

Average side ordering is still a coarse objective after correcting its contract. It cannot prove that Gardevoir acts before the particular threat that matters. That remaining limitation is separate from the double inversion.

The report also retains 56 development and 13 validation matched comparisons where the control has higher immediate utility yet an alternative supplies a sampled common Gardevoir opportunity absent in the control. These overlap across actions/scenarios and are not independent errors. Some control lines enable Metagross instead; those are not automatically strategic failures. We therefore have one reproducible contract defect and several plan-specific counterexamples, not proof that a finisher-opportunity metric is the right replacement objective.

## Validation and next milestone

32 targeted tests pass, covering public-only planning, Mega continuity, competing routes, direct-damage attribution, native split logs, legal-menu coverage and common-command checks. Ruff and retained-archive/source-hash audits pass. Tests and native execution establish measurement correctness; they do not establish decision quality.

Next isolate the speed interface contract in a focused fix: explicitly define raw effective speed versus native action-order speed, verify native ordering with and without Room on different compositions, and run a paired held-out decision/gameplay comparison with all other controls fixed. Do not use these two positions as proof of general improvement. Strategic feasibility and trade valuation remain separate unresolved work. Keep strategic labels disconnected from action scoring.

Reproduction with `PYTHONPATH=src`:

```powershell
../champions-practice-bot/.venv/Scripts/python.exe scripts/strategic_consequence_comparison.py
../champions-practice-bot/.venv/Scripts/python.exe scripts/strategic_consequence_report.py
../champions-practice-bot/.venv/Scripts/python.exe -m pytest tests/test_plan_consequences.py tests/test_strategic_diagnostic.py tests/test_strategy.py tests/test_strategy_tactics.py -q
```

Source/archive hashes, complete paired measurements, legal/probed coverage and witness commands are in the companion JSON and local ignored `runs/v2-plan-consequences/v1/` archive. Prior diagnostic reports retain their historical contents. No scorer, default V2, or PR #249 changes are included.
