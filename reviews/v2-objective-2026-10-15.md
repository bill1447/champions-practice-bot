# Fixed-branch objective investigation — 2026-10-15

The primary risk-sensitive alternative did not improve clean paired results. Removing the position term produced a narrow gain worth investigating, but short continuations disagree with some full-game rankings. No objective or weight change is promoted.

## Controlled comparison

Retain one turn, eight own candidates, three opponent responses and the original hidden hypotheses/RNG. Replaying all 24 control matrices reproduces every original ranking, scalar utility, selected action and branch count. Added telemetry decomposes the actual resolved leaf into existing terminal, material, position and speed terms. Material additionally exposes living, HP and status components. No native mechanics or scorer weights change.

Response sensitivity uses `(1-lambda) * scenario_mean + lambda * scenario_min`, with lambda 0.5 declared primary before collection; 0.75, 0.25 and zero are diagnostic controls. Hidden-world averaging and leaf ablations are separate interventions. Scenario averages are not calibrated opponent probabilities. Re-ranking changes only root selection; subordinate replacement/continuation decisions remain fixed in the cached native branches.

| Root objective | Wins / 24 | Changed openings | Candidate-only / control-only | Fallback-free paired control → candidate |
| --- | ---: | ---: | ---: | --- |
| Original minimum | 10 | 0 | 0 / 0 | 10/24 → 10/24 |
| Risk 0.5 | 12 | 20 | 4 / 2 | 10/20 → 8/20 |
| Risk 0.75, 0.25, scenario mean | 12 each | 20 each | 4 / 2 each | 10/20 → 8/20 each |
| World mean, response minimum | 10 | 0 | 0 / 0 | 10/24 → 10/24 |
| Remove position | 12 | 4 | 2 / 0 | 10/24 → 12/24 |
| Material plus terminal only | 12 | 4 | 2 / 0 | 10/24 → 12/24 |
| Remove speed | 10 | 0 | 0 / 0 | 10/24 → 10/24 |
| Remove HP | 7 | 12 | 1 / 4 | 10/24 → 7/24 |
| Remove living-count term | 10 | 0 | 0 / 0 | 10/24 → 10/24 |

The softened-response variants choose identical actions here. Their apparent aggregate improvement depends on games where the independent opponent used its legal-action fallback. Excluding every pair affected on either side reverses that result. This does not establish excessive pessimism as the main cause. World averaging changing nothing does not validate the hidden priors: only two friendly hypotheses were represented.

Removing position changes four psychic-balance/sand openings from Gardevoir Protect + Indeedee Trick Room to switching Gardevoir into Metagross + Psychic. Two additional wins come from one correlated seed/mirrored matchup. This implicates position valuation in specific decisions; it does not justify deleting the term globally.

## Retained counterexamples and short continuations

After sealing the root recommendations, diagnose three retained positions using actual native states, three or four fixed opponent replies and eight coupled RNG futures per action/reply. Continue through two completed turns, including replacements, using frozen V2 for our continuation and the independent heuristic for the opponent. Actual hidden state is diagnostic-only and never enters root choices. All 288 samples complete; three opponent-fallback samples are excluded from clean means. These are scenario sweeps, not 288 independent battles or estimated win probabilities.

Selected clean means of the unchanged scorer:

| Position / plan | After first turn | After second turn |
| --- | ---: | ---: |
| Development psychic/sand: Psychic + switch | -17 | -1706 |
| Same: Trick Room + Protect | -28 | 363 |
| Validation Armarouge: Follow Me + Armor Cannon | 610 | -448 |
| Same: Trick Room + Protect | 20 | 262 |
| Validation psychic/sand: Protect + Trick Room | -30 | 350 |
| Same: switch + Psychic | -32 | -160 |

The first two comparisons expose enabling value that immediate scores miss. The last is equally important: switch + Psychic wins the retained full-game trials more often, yet Trick Room looks better in this short diagnostic sweep. A short rollout evaluated by the same incomplete scorer is not ground truth. Horizon, response assumptions, and downstream policy still interact; no universal tactical rule follows.

## Provenance and limits

There are 24 paired cases from the already examined suite, not fresh validation. The 264 objective assignments reuse identical case/opening-command games from retained archives; only 12 new full battles were necessary. Later gameplay remains frozen PR #249 V2 (`e0ae723`). The machine-readable companion records source/archive hashes, paired fallback exclusions and all continuation means. Raw matrices, sealed manifests and rollouts live under `runs/v2-objective/` (local, ignored).

Reproduce with `PYTHONPATH=src` and the existing environment Python:

```powershell
../champions-practice-bot/.venv/Scripts/python.exe scripts/tactical_objective_experiment.py
../champions-practice-bot/.venv/Scripts/python.exe scripts/tactical_objective_continuations.py
../champions-practice-bot/.venv/Scripts/python.exe scripts/tactical_objective_report.py
```

The report audits source/archive hashes, original matrix equality, branch counts and all rollout references. Full suite: 1,701 passed after the implementation changes; targeted objective tests and Ruff also pass. Default V2 and PR #249 remain unchanged. Keep 8/3 as control. Next evaluator work should explain the retained position/trade reversals before tuning weights; next admission work should separately address the newly exposed persistent-mechanics blockers.
