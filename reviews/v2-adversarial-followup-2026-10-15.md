# Adversarial review follow-up — 2026-10-15

Scope: the user's pasted review of GitHub `main` at `663acfe`, checked against the local experimental checkpoint `9129541` and its pinned Showdown source. This follow-up does not claim to have inspected every difference in that GitHub merge or its live CI status. The experimental player remains unpromoted.

## Correct the ordering finding

Finding 2's premise and recommended turn-start-order fix do not apply to Champions. The pinned Showdown revision is `a5df8274e85b0889bf2a9b3422a08b39732374fc`. Its Champions scripts declare generation 9. `sim/battle.ts` explicitly updates Speed, refreshes queued action speeds and sorts the remaining queue for generation 8 onward after actions. The approximate evaluator's dynamic reordering is therefore not itself the reported defect. This does not establish that every detail of that approximate evaluator is correct.

`tests/test_native_dynamic_order.py` preserves a format-validated native control. From one identical root and RNG sample, Pelipper uses either Tailwind or Protect while Gardevoir and Rotom queue attacks:

| Control | Native order of queued attacks |
| --- | --- |
| Protect | Rotom, then Gardevoir |
| Tailwind | Gardevoir, then Rotom |

The test uses legal native moves, no serialized stat/field edits, no Mega transformation, no Speed tie and the same parent state. Freezing all remaining actions at turn-start order would contradict this control. No ordering algorithm, tactical weight or gameplay decision was changed.

## Pin the evaluation dependency

`poke-env` is now pinned to **0.16.1**, the version already installed and recorded in the frozen full-game evidence. The adapter constructs private battle fields, so an unconstrained dependency upgrade is inappropriate for reproducing those results. Existing opponent source/dex hashes remain relevant; pinning the package is not a complete transitive lockfile. No package upgrade or reinstall was needed and no historical results were regenerated or pooled.

## Explain the 29 inventory fallbacks

`scripts/opponent_inventory_audit.py` walks the original experimental games' public views in order, including forced waits and same-turn replacement checkpoints. It reconstructs the public constraint ledger and resolves item-event identities at their historical active slots. It examines only observations available at each rejected checkpoint; future observations, actual hidden sets and battle results do not enter the classification. The raw archive is read locally and is not added to Git.

All **29** first-reported `opponent-inventory` fallbacks are accounted for, across **9 games**, by **12 distinct public consumption events**:

| Public event | Distinct events | Rejected decisions containing this item history |
| --- | ---: | ---: |
| Sitrus Berry ended | 4 | 19 |
| Shuca Berry ended | 4 | 3 |
| Focus Sash ended | 2 | 4 |
| Colbur Berry ended | 2 | 3 |

These are repeated downstream rejections from a small number of consumption events, rather than 29 independent inventory mechanisms. By current turn, the rejected decisions are: turn 2: 3; turn 3: 4; turn 4: 8; turn 5: 9; turn 6: 4; turn 7: 1.

The explicit gate is in `persistent_support.public_support_contract`: any observed opposing `-item` or `-enditem` lifecycle remains unresolved. Inventory is the only unresolved family in that public contract at these 29 checkpoints. **This is not an estimate of 29 recoverable admissions.** Static prior compatibility, field reconstruction, current capabilities, native state restoration and positive admission checks can still reject them. Other positions may also contain inventory problems masked by an earlier reported gate; this audit is deliberately limited to these 29 recorded first reasons.

In particular, **17/29 decisions** include consumption of Sitrus Berry by Excadrill; the approved species priors represent Life Orb Excadrill, not Sitrus Excadrill. This is three distinct consumption events in shifted-family games. The other **12/29 decisions** have every observed consumed item represented in the corresponding species priors. The fourth Sitrus consumption belongs to Rillaboom, whose prior already includes that item. Item-source representation is only a necessary check for a bounded no-transfer consumption proposal, not certification of full set compatibility or proof about the actual initial set. The audit retains this distinction and the approved item catalog.

## Next bounded admission experiment

Start with the 12 prior-item-covered checkpoints and ordinary public consumption for these four item IDs. Establish an actor/member lifecycle plan from public events, retaining source item and consumption mode through switches and fainting. Distinguish consumption from removal or transfer; do not infer a held item from an empty observation. Keep the 17 other checkpoints as prior-coverage controls; do not silently add held-out Sitrus Excadrill to recover them.

Restoration must reproduce native inventory state, including applicable `lastItem`, `ateBerry`, `usedItemThisTurn`, item effect state and ability interactions. The pinned native `eatItem` and `useItem` paths update more than the current item string. Merely clearing `item` or dropping the gate would be insufficient. Keep unsupported transfer, recycling, ability activation and ambiguous histories closed. Approved initial priors must remain compatible with the observed source item.

Require native positive controls for each item, current-turn versus post-residual boundaries, switches/fainting, and negative controls for wrong item, wrong identity, missing event, duplicated consumption and incompatible abilities. Replay the retained 29 checkpoints to measure recovery and newly exposed rejection reasons before any new paired gameplay. The historical 15/24 versus 10/24 result must remain frozen.

No admission gate was relaxed in this follow-up. The benchmark-strength and late-coverage findings remain valid. Immutable GitHub Actions pins remain separate, lower-priority hardening work.

Evidence: `reviews/v2-opponent-inventory-audit-2026-10-15.json` contains archive provenance, counts, all 29 checkpoint records, their public inventory events and unresolved contract entries. Reproduce with `PYTHONPATH=src python scripts/opponent_inventory_audit.py --archive runs/v2-full-game-native/frozen-v2/games.json.gz --output reviews/v2-opponent-inventory-audit-2026-10-15.json`.

Validation: **1,732 tests passed**, including the new native same-turn ordering control and existing opponent-boundary tests. Targeted Ruff passed; `pip check` reported no broken requirements. The installed `poke-env` version is 0.16.1, matching the new exact pin and the existing frozen gameplay evidence.
