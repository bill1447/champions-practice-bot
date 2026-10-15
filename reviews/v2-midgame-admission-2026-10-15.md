# Midgame admission and competing-route requirements — 2026-10-15

The retained turn-two probe improves from **0/12 to 8/12 completed native one-turn 8/3 comparisons**, with four familiar and four unfamiliar-set checkpoints. The remaining four remain explicitly unsupported. This establishes early-midgame availability in a bounded sample, not full-game playing strength or universal admission.

The speed-only fix and gameplay experiment were frozen first in `6e9014a`. This subsequent work changes admission and public-view plumbing, not strategic weights. Historical speed reports and archives retain that commit's provenance; replay their source-hash audit at that commit.

## Bounded capability support

- Earthquake is admitted as a current-fact move. Native mechanics still resolve terrain, immunities, spread/ally damage and boosts. Unsupported Dig and related persistent capabilities remain closed.
- Stomping Tantrum is allowed on an inactive holder only. Native switch-out `clearVolatile` resets the previous-move result before a reserve can act again. Active holders and observed Stomping history are still unsupported. Admission independently rejects a carried inactive last-move result.
- Owned Unburden is allowed on an inactive holder only, with the native volatile absent. Active owned Unburden and opponent Unburden remain closed; a cached Speed is not treated as activation-history proof.
- Inactive Electro Shot/Phantom Force capabilities use the same native switch-reset boundary for charge volatiles. Active charging capabilities and observed charge history remain unsupported. Fainted public members are unavailable to act; revival capabilities remain outside the supported contract.

These are not blanket move/ability allowlists. Every compatible opponent prior is still checked before bounded sampling. Native request equality, current mechanical facts, PP, active tenure, protection history, field age/source, legal-menu equality and serializer round-trip checks remain required.

Format-validated native controls produce a real Stomping failure against Levitate, consume Psychic Seed to activate Unburden, then switch both holders out and back. The failure does not carry across switching; Unburden clears and does not reactivate without an item (effective Speed 344 → 172). Adversarial retained-state controls reject **18** corrupted dormant move results and **4** corrupted dormant Unburden flags. No production mechanics flags are fabricated by these controls; corruptions are offline negative tests only.

## Public origin: constructor logs are not observations

Physical admission exposed a second interface problem. A reconstructed Battle has helper logs from staging switches, inert Splash entries used to establish native tenure, and old HP notifications. Its physical state can match the public checkpoint while its log-derived view reports stale HP or unobserved helper moves. Two otherwise admitted roots also differed in synthetic `public_event_delta` values, causing the consequence kernel's information-set guard to reject them.

`PublicOriginWorker` supplies an explicit, source-bound public annotation for already admitted canonical-p2 roots:

1. Require the current view to match the public constraint ledger and rerun the native positive admission checks.
2. Seed the focal side's opponent knowledge from its authoritative public observation. Seed the modeled opponent's knowledge from actual public lifecycle events rather than our private move list.
3. Keep the root's original native log offset. Project future knowledge from only the native fork events after that offset, with the correct source-turn boundary.
4. Carry the same origin through child forks. Preserve native states, requests, legal menus, RNG, summaries and mechanics; projection uses a separate read-only log view.

Every admitted root now matches the **entire consequence observation key**, including opponent HP/reveals and the public event channel, rather than merely matching another reconstructed world. Future controls verify the correct native turn, unchanged parent state, absence of constructor Splash revelations, and rejection of a modified source observation. The information-set guard remains intact. Unknown roots, invalid source offsets, unsupported mechanics and ledger mismatches are not licensed by this annotation.

The optional origin belongs to the explicit native-consequence consumer. It is not a new gameplay policy, hidden-history reconstruction, or a claim that arbitrary raw constructor logs are trustworthy. Existing callers without an origin retain their previous projection behavior.

## Remaining blockers

| Cases | Current blocker |
| ---: | --- |
| 2 | Active Electro Shot capability has no certified charge-state domain in this constructor. This does not assert that it is currently charging. |
| 1 | Observed confusion needs a mechanically possible counter domain; it cannot be reset to a convenient timer. |
| 1 | No compatible approved public prior after Pelipper reveals Hydro Pump. The public prior catalog does not cover that revealed set. |

No private actual team, enemy command, battle seed or live snapshot is supplied to admission or decision helpers. Hypotheses remain partial public-compatible possibilities, with no claim of an exact historical RNG witness or exhaustive hidden-set coverage. Do not expand priors using sealed truth merely to improve this count.

## Strategic plan comparison without move bonuses

The eight completed checkpoints also compare the existing competing finisher/material hypotheses against the **same native completed-turn leaves**. An opt-in telemetry flag records those leaves through the already selected replacement/pivot continuations. Tests verify identical action, ranking, utility and branch count when this telemetry is enabled.

For each command and route, report remaining material, terminal outcomes, whether the required resource survives and is active, grounded Psychic Terrain readiness, and native Mega availability for Gardevoir's Fairy Hyper Voice mode. No numeric plan utility, move bonus, automatic plan selection or future attacking-window certificate is introduced.

A concrete consequence appears in development psychic/sand: the selected Metagross Mega + Steel Roller line keeps Gardevoir alive in all six world/response leaf samples, but Gardevoir's Mega Fairy mode is unavailable in all six after Metagross spends the shared Mega resource. Grounded Psychic Terrain readiness remains in only two of six samples. Metagross itself survives and is active in all six. That can be a valid alternative route; a planner that equates “Gardevoir alive” with “Gardevoir sweep available” would miss both the opportunity cost and the alternative.

This comparison does not prove Metagross is the winning route, or that terrain preservation is always preferable. It distinguishes requirements and consequences so a later plan selector can compare realistic routes. A living but benched resource is not credited with an immediate attacking window; absent terrain or Mega availability invalidates that specific mode, not every remaining way the resource might help win. The emergency material hypothesis remains available without requiring the original centerpiece.

## Validation and reproduction

Full suite: **1,723 passed**. Existing native persistent-admission equivalence/negative controls pass, including Fake Out, pivot/replacement boundaries, terrain uncertainty and rejection of sleep, confusion and other unrestored latent mechanics. Native dormant-state controls, all eight authoritative public roots, future-event controls, source/archive audits, Ruff and Node syntax checks pass.

The probe keeps the original 12 checkpoints and known own actions, two-world/two-particle preparation limits, and one-turn 8/3 consequence control. Its eight-second preparation and separate eight-second consequence budgets do not establish production latency. There is no new midgame gameplay intervention or win-rate claim. Default public V2 and PR #249 are unchanged.

With `PYTHONPATH=src`:

```powershell
../champions-practice-bot/.venv/Scripts/python.exe scripts/inactive_capability_controls.py
../champions-practice-bot/.venv/Scripts/python.exe scripts/midgame_admission_probe.py
../champions-practice-bot/.venv/Scripts/python.exe scripts/midgame_admission_report.py
```

Raw final checkpoints, rankings, leaf positions and per-sample route requirements are under ignored `runs/v2-midgame-admission/v9/`; the tracked companion JSON keeps audited counts and compact comparisons. Earlier v1–v8 iterations are exploratory instrumentation runs, not additional gameplay samples. Next admission work is the explicit charge/confusion domains and public-prior coverage; plan selection should be tested on these outcome requirements before any promotion into action selection.
