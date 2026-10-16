# Exact-tie correction and decision-quality checkpoint

The experimental native player now rejects a sampled-dominated action when its
worst-world and weighted-world scores exactly tie another candidate. On the
same 24 paired full-game cases, native wins increased from **15 to 16**, while
frozen V2 remained **10/24**. This is a correction validated in an existing
suite, not an independent replication or evidence of competitive competence.

## Isolated implementation

`consequence_ties.order_exact_ties` sorts stable nondominated frontiers inside
exact robust-score ties. Dominance requires identical world indices, labels,
weights and response coverage, with no worse sampled response mean anywhere
and a strict improvement somewhere. Incomparable choices retain proposal order.
No tolerance changes the definition of a robust-score tie. Missing/nonfinite
response evidence cannot establish dominance. The final root selector calls
this after its existing robust sort and before its existing deadline check.

Utility weights, opponent aggregation, hypotheses, admission, shortlist,
one-turn 8/3 search, continuation/replacement selection and shared eight-second
budget are unchanged. Strategic labels remain diagnostic. Dominance over
sampled response means does not imply dominance over individual RNG outcomes
or unsampled opponent actions.

## Frozen decision audit

The protocol and manifest were written before evaluating the selector. The
four retained development cases and all **75 separate archived checkpoints**
were audited. Twelve inspection cases were selected deterministically by
hashing game/checkpoint identifiers without consulting scores or game outcomes.
These are separate checkpoints from previously studied games, not unseen teams
or a genuinely blind expert-labelled tactical benchmark. All optimal-action
labels remain explicitly unproven. Command flags identify available move,
shielding, switching and speed-control options; they do not establish KOs,
favorable trades or viable finishing routes.

Only the retained repeated-Protect case changes:

- Before: `Follow Me + Protect`.
- After: `Follow Me + Armor Cannon into Rillaboom`.
- Both robust scores remain **-1061.4**. Armor Cannon is no worse against
  every supplied world/response mean and strictly better in four of six bins.
- The other three retained choices and all 75 separate archived choices remain
  unchanged. Every candidate utility and branch evidence entry is preserved.

This demonstrates transfer safety of the tie rule, not improved strategic
choices on the separate checkpoints. No new win-condition evaluator was fitted.

## Complete-game regression

| Measure | Inventory control | Exact-tie correction |
| --- | ---: | ---: |
| Native wins | 15/24 | 16/24 |
| Frozen V2 wins | 10/24 | 10/24 |
| Native-only / V2-only wins | 5 / 0 | 6 / 0 |
| Completed native searches | 79/166 | 81/168 |
| Turn 4+ searches | 12/67 | 14/68 |
| Disagreements with V2 | 55 | 56 |
| Mean / p95 decision latency | 0.379 / 1.181 s | 0.369 / 1.151 s |
| Maximum decision latency | 1.641 s | 1.589 s |
| Decisions exceeding eight seconds | 0 | 0 |

All 48 games completed with no opponent-adapter fallback. All 24 frozen V2
trajectories matched exactly. Exactly one native trajectory changed:
`validation-2-max-base-power-heldout-native`, turn 2, checkpoint 1. It changed
from a loss to a win. At its first divergence, public view, legal menu, every
candidate utility and native branch evidence matched the control exactly.
The later path and RNG consumption then diverge; the final win is not proof
of optimality for all plausible continuations. The other 23 native trajectories
match. Coverage changes are consequences of that different game, not admission
expansion. Small latency differences are descriptive, not a speed claim.

## Opportunity evidence, without another scoring rule

The benchmark also extracts actor-specific execution evidence from the existing
704 coupled continuation samples. These are reused diagnostic samples, not new
games or calibrated win probabilities. The following counts use only the
original covered-response cells (48 or 24 samples per action):

| Position and line | Terminal wins after next turn | Losses | Named next-turn contribution |
| --- | ---: | ---: | --- |
| Low-HP Armarouge: Protect | 4/48 | 0 | Armarouge deals damage in 0/48 |
| Same: Armor Cannon | 48/48 | 0 | Armarouge attacks now; Venusaur damages in 26/48 continuations |
| Same: switch to Venusaur | 48/48 | 0 | Venusaur damages in 32/48 continuations |
| Venusaur: Protect | 32/48 | 0 | Venusaur damages in 48/48 continuations |
| Same: Energy Ball | 30/48 | 4 | Venusaur damages in 44/48 continuations |
| Same: Sludge Bomb | 36/48 | 2 | Venusaur damages in 40/48 continuations |

Terminal roots remain terminal in continuation counts. Execution counts alone
are not a value function: the lone-Venusaur Protect line damages the opponent
in all 24 V2 continuations yet loses all 24. Existing native next-turn probes
instead find a Sleep Powder opportunity after Trick Room expires. That is a
counterexample to treating V2 continuation as an oracle and to assuming every
executed attack advances a winning route.

The Armarouge case therefore remains the next strategic diagnostic: compare
immediate conversion, preserving Armarouge via switching, and alternative
Venusaur finishes using a shared action across indistinguishable hypotheses.
The evidence supports comparing these routes; it does not justify a universal
Protect penalty, a bonus for keeping a designated centerpiece alive, or an
actor-damage count as a replacement objective.

## Validation and reproduction

**42 targeted tests passed**, covering tie semantics, actual tactical-kernel
integration, the position evaluator, experimental-player behavior and plan
measurements. Ruff passed for changed Python files. The matrix audit verifies
unchanged candidate evidence and robust preferences, plus an independent
scalar-vector check that the selected top-tied action is not dominated.

Run with the repository virtualenv and `PYTHONPATH=src;scripts`:

```text
python scripts/decision_quality_benchmark.py evaluate
python scripts/full_game_native_evaluation.py --output runs/v2-full-game-native/NEW-RUN
python scripts/decision_quality_game_comparison.py --control runs/v2-full-game-native/inventory-v1/games.json.gz --candidate runs/v2-full-game-native/NEW-RUN/games.json.gz --output reviews/NEW-COMPARISON.json
```

The benchmark validates its frozen manifest and does not overwrite it. The
game comparison validates case identities, teams, frozen policy, opponent
identity, source hashes and first-divergence branch parity. Raw game archives
remain local and ignored; concise manifests and reports are tracked. Historical
preservation-diagnostic reproduction belongs at its original `85145ba` source
checkpoint because this change intentionally corrects its old root decision.

The next competence gate remains a genuinely separate, consequence-labelled
tactical set and fresh full games with validated stronger opposition including
Mega behavior. This checkpoint repairs a demonstrated decision defect; it does
not yet connect strategic route selection to action scores or promote the
experimental player to production.
