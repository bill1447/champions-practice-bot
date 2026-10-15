# Native speed contract fix — 2026-10-15

Native summaries now distinguish current effective Speed from action-order Speed. Both native evaluators use the effective stat and apply Trick Room once. All strategic weights remain unchanged. The paired opening trial improves narrowly; it does not establish a stronger full-game native player.

## Contract and consumer audit

`tools/showdown-search-worker.js:summarize` exports:

- `effectiveSpeed`: native `getStat('spe', false, false)`, including status, boosts, abilities, items and Tailwind; excludes Trick Room ordering.
- `actionOrderSpeed`: native `getActionSpeed()`, computed for the current field. Champions negates this value under Trick Room.
- `cachedActionOrderSpeed`: native `mon.speed`, which can be stale across field transitions.
- Legacy `speed` remains an alias of the cached value for compatibility. It is not an effective stat.

`native_speed.effective_speeds` consumes only the explicit effective field. It never guesses from the sign of a cached or ordering value. Missing/partial legacy summaries yield unknown speed evidence; invalid effective values are rejected.

| Consumer | Audit/change |
| --- | --- |
| `exact_search._average_active_speed` / `_speed_position_value` | Read effective Speed; retain the existing single Trick Room reversal, scaling and cap. Material, position, terminal scores and every other exact-search function are AST-identical to `dbb1027`. |
| `strategy_evidence._favorable_speed_control` | Read effective Speed, compare under Trick Room once, remove duplicate Tailwind multiplication. Plan priorities and weights are unchanged. |
| `belief_search` | Aggregates named score components; does not reinterpret a native Speed field. No change. |
| `tactical_consequences` | Delegates scoring and propagates components. No candidate, response, depth, world or utility-weight changes. |
| `position_report` | Renders the scalar speed contribution. No change. |
| `plan_consequences` and the previous consequence report | Record legacy cached ordering values for historical diagnostics; they do not select actions. Prior reports/archives retain their original meaning and source identity. |
| Public-view `agent_v2`, `strategy`, current-state constraints and admission diagnostics | Consume a separate exact own observed cached-Speed field. Its producer and values are intentionally unchanged; this experiment does not rework V2 heuristics or the third-stage public strategic planner. Cached public Speed must not be treated as a new effective-Speed certificate. |

The two actual native-summary evaluators were the double-inversion consumers. Strategic evidence also duplicated Tailwind. Fixing those contracts does not certify that average team speed or a pairwise majority is a good strategic objective.

## Native controls

A format-validated six-member roster executes legal native moves; no status, boost, field timer or stat is assigned by the control script. Both evaluators' isolated actor comparisons are checked against actual native move/cant order, using equal-priority attacks:

| Condition | Effective Speed | Action-order Speed | Result |
| --- | ---: | ---: | --- |
| Normal Gardevoir | 130 | 130 | Opposing Dragonite acts first |
| Trick Room | 130 | -130 | Gardevoir acts first |
| Tailwind | 260 | 260 | Gardevoir acts first |
| Paralysis | 65 | 65 | Opposing Rotom acts first |
| Dragon Dance on Dragonite | 198 | 198 | Boosted Dragonite acts first |
| Mega Gardevoir | 150 | 150 | Mega Gardevoir acts first |
| Tailwind plus Trick Room | 260 | -260 | Opposing Dragonite acts first |

All seven controls pass. Unit tests additionally verify unknown legacy fields, invalid values, stale-cache independence and no second Tailwind multiplier. Full suite: **1,719 passed**; Node syntax and Ruff pass.

## Paired gameplay with weights held fixed

Primary control is the unchanged pre-fix **native one-turn 8/3 baseline**, with its exact scorer loaded from `dbb1027`. It reads the preserved cached summary field. The candidate uses the corrected speed contract on the same native worker. All later choices use frozen public V2 `e0ae723`; this remains an opening-only intervention. Public observations, live seeds, opponent seeds, own teams and hidden truth are identical within each pair.

The original 24 control openings reproduce **all saved rankings, utilities, actions and branch counts** under the new worker, confirming that adding explicit fields did not alter the baseline. Identical case/opening games are reused for retained pairs; new compositions are played in both arms.

| Suite | Paired cases | Baseline wins | Fixed wins | Fixed-only / baseline-only |
| --- | ---: | ---: | ---: | ---: |
| Retained compositions | 24 | 10 | 11 | 1 / 0 |
| Six fresh matchup combinations and fresh seeds | 24 | 11 | 13 | 2 / 0 |
| Fresh, excluding either-arm opponent fallback | 22 | 9 | 11 | 2 / 0 |

Four retained and eight fresh openings change. The fresh-only wins are a mirrored pair from one matchup/seed; they are correlated. Retained gains also come from a previously examined example. These results support correcting a proven contract defect, not a broad strength or competitive-rating claim. Hidden hypotheses remain the same friendly two-world family; no strategic labels were wired into the scorer.

There are 52 newly simulated game records (48 fresh-arm records and four changed retained openings), representing 36 distinct new case/opening trajectories. The remaining retained games reuse the original archive. Repeated deterministic runs for source cleanup/provenance are not additional evidence. Both original and fresh summaries report paired opponent-fallback exclusions.

## Reproduction and sequencing

With `PYTHONPATH=src`:

```powershell
../champions-practice-bot/.venv/Scripts/python.exe scripts/native_speed_controls.py
../champions-practice-bot/.venv/Scripts/python.exe scripts/speed_contract_gameplay.py
../champions-practice-bot/.venv/Scripts/python.exe scripts/speed_contract_report.py
```

The machine-readable report audits code/archive hashes, unchanged weight functions, paired public observations/seeds, legal commands and native controls. Raw outputs are under local ignored `runs/v2-speed-contract/`. This speed-only evidence is frozen before the separate midgame admission work. No push or PR #249 update is included.
