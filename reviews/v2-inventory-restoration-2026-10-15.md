# Bounded native item-consumption restoration — 2026-10-15

The retained inventory probe now completes one-turn native search at **4/12 prior-item-covered checkpoints**, previously all inventory fallbacks. The other eight expose existing capability gates. All **17 out-of-item-prior checkpoints remain rejected**. This is a position-level correctness/coverage result; the historical full-game **15/24 versus 10/24** result is unchanged.

## What changed

`public_inventory.public_inventory_plan` derives a bounded opposing consumption plan from the complete source-bound public lifecycle. It admits only Sitrus Berry `[eat]`, Focus Sash's ordinary end-item event, and complete Shuca/Colbur Berry `[eat]` + `[weaken]` pairs. Identity is taken from the public actor mapping at the event, not the current occupant of the slot. Unknown identities, transfers/removals, unsupported items, missing pair members and repeated consumption by the same member remain unresolved.

The native present-state builder checks the hypothetical original item against the consumed source item and restricts the holder to an explicit set of supported abilities. It uses pinned `eatItem()`/`useItem()` methods to establish current item, `lastItem`, `ateBerry`, `usedItemThisTurn` and native item effect-state cleanup. It does not edit those serialized fields to force a match. Temporary native staging/HP changes are followed by the existing tenure, PP, protection, field, HP, request, legal-menu and serializer checks.

Old consumptions are established before native active-tenure reconstruction; native `endTurn` or switch-out clears their current-turn flag. A current-turn consumption at a post-residual replacement pause is established after tenure/protection reconstruction but **before native faint handling**. This ordering matters: consuming after fainting would be refused by native mechanics. A focused native regression caught and validated this boundary. Previously fainted consumers can also be reconstructed after their replacement, with the flag cleared by switching.

Positive admission independently checks the consumed item's original set source, empty current slot, exact `lastItem`, strict Boolean berry/current-turn flags, cleared item effect state and correct serialized member target. It rejects an unobserved inventory mutation even when the public plan is empty. Approved-prior set validation remains in place; observations never grant permission to invent a Sitrus Excadrill prior.

No strategic weights, position utilities, candidate/response caps, horizon, public prior catalog or experimental decision budget changed. This extends bounded mechanical admission; it does not promote the experimental player.

## Retained replay

The original 29 inventory-fallback checkpoints were replayed from their recorded public views and legal menus. Each experimental decision retained V2 as the incumbent and shared its existing eight-second budget across preparation and one-turn 8/3 search. Earlier actions and paths remain the recorded ones; new choices were not played forward as new games.

| Group | Positions | Completed searches | Still rejected |
| --- | ---: | ---: | ---: |
| Prior source items represented | 12 | 4 | 8 |
| Source item outside species priors | 17 | 0 | 17 |
| All retained inventory fallbacks | 29 | 4 | 25 |

Recovered checkpoints:

- Armarouge support / grass balance, shifted family, SimpleHeuristics: turn 4 replacement, turn 5 move, turn 6 move. Pelipper's consumed Focus Sash is retained correctly through the replacement boundary.
- Armarouge pivot / grass water, shifted family, SimpleHeuristics: turn 5 move. Rillaboom's consumed Sitrus Berry is reconstructed.

Two of the four searches choose differently from V2. Maximum total decision time across the probe is **0.860 s**; no eight-second overrun occurred. This does not establish better decisions or a new win count.

The eight prior-covered failures now report: opponent capabilities 2; owned Unburden 1; active Electro Shot 3; active Stomping Tantrum 2. All 17 source-item-outside-prior cases report opponent capabilities, retaining the earlier catalog boundary. Inventory-only in the public contract did not imply full native admission, as the previous audit cautioned.

## Native controls and adversarial validation

The probe separately reconstructs nine original live fixtures from their driver-owned sets/seeds and replays their recorded commands. It verifies exact public observation parity before every target checkpoint and checks native inventory against the public plan at all **29** checkpoints. It rejects **116** mutated item/last-item/berry/current-turn flag controls. These oracle fixtures never enter the admission player; its inputs remain owned team, public view/history/menu and approved priors.

Format-validated six-member native test teams exercise all four item types using legal attacks. The tests require successful fresh reconstruction, compare the inventory fields against the real native states, test serialization and a native continuation, and cover consumption followed by fainting, replacement and a second fresh reconstruction. Incompatible source priors remain rejected. Further unit controls reject missing events, wrong identity/source item, duplicate consumption, incomplete resistance-berry pairs, removal/transfer tags, stale effect-state keys and wrong effect-state member references.

Clarification of the earlier audit: its **12 distinct public end-item messages represent nine consumption events**. Three resistance-berry consumptions each emit two messages. The old JSON's message counts remain historically accurate; this implementation treats each validated pair as one consumption.

The supported native APIs restore inventory consequences, not a complete historical replay or calibrated hidden-world distribution. Damaged living opposing reserves and unsupported abilities/moves remain subject to their existing gates. Transfer, recycling and repeated-consumption histories remain closed.

## Provenance and reproduction

- Frozen source hashes, unchanged-prior hash, baseline identity and source-archive hash: `runs/v2-inventory-admission/frozen-v2/manifest.json`.
- Complete decision traces, rankings and public route diagnostics: `runs/v2-inventory-admission/frozen-v2/positions.json.gz` (local raw archive, not tracked).
- Tracked compact report: `reviews/v2-inventory-restoration-2026-10-15.json`.
- Replay in PowerShell: `$env:PYTHONPATH='src;scripts'; python scripts/inventory_admission_probe.py --output runs/v2-inventory-admission/new-run`.
- Audit/condense: `python scripts/inventory_admission_report.py --archive runs/v2-inventory-admission/frozen-v2/positions.json.gz --output reviews/v2-inventory-restoration-2026-10-15.json`.

The earlier inventory audit should be reproduced at `caccbc1`, where ordinary consumption was still intentionally unsupported. Its historical assertions are not a test of the new contract.

Validation: **1,746 tests passed**; targeted Ruff, Node syntax and Git whitespace checks passed. Raw archives and model files are not included in the change.
