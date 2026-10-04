# Semantic replay policy v1

The first learned policy is a replay-derived semantic action prior, not an exact Showdown-command classifier.

That distinction is required by the measured replay corpus. Public logs reveal many moves and switches, but do not prove the player's complete request, submitted target, switch party index, or exact Mega variant. The v1 model learns which semantic joint actions look plausible in a public position and leaves exact command legality and tactical selection to pinned Showdown plus exact search.

## Frozen dataset

Training accepts an explicit semantic-audit run ID. Passing a run ID freezes the replay-disjoint split, source fingerprint, pinned Showdown revision, and compressed policy shards. The trainer independently hashes every shard and records those hashes in its report.

Use `-RunId <audit-run-id>` for benchmark runs rather than training against a moving latest-summary file.

## Inputs

The state tower receives only actor-relative features derived from the decision-time replay public state: turn/phase, weather and field conditions, both public team previews, active species/forms, public HP buckets, status, boosts, side conditions, and moves/items/abilities already publicly revealed.

Player names, replay result, replay ID, rating, future events, resolved future information, and hidden particle identities are not state features. Rating is used only as a training weight.

The action tower receives a semantic two-slot joint action: move ID plus public gimmick identity, switch species, or pass. Selected target is intentionally absent. Mega X/Y are normalized to generic Mega because the public replay evidence used here does not reliably distinguish those submitted variants.

## Model

`semantic-two-tower-adagrad-v1` is a small NumPy model. State and action tokens are deterministically SHA-256 hashed into separate embedding tables. Mean state and action embeddings are scored by dot product.

Training uses sampled contrastive alternatives: the observed human semantic action is positive; negatives come from other training-vocabulary actions of the same action family when possible, with global-vocabulary fallback. Rating-aware weighted cross entropy updates the embeddings with sparse AdaGrad.

Default rating weights are: unrated 0.10, below 1200 0.15, 1200-1399 0.35, 1400-1599 1.00, 1600-1799 2.00, and 1800+ 3.00.

## Metrics

Validation and test report sampled recall at 1, 4, 8, and 16, split by rating band, action family, turn phase, and whether the exact semantic joint action was seen in the training vocabulary. The default evaluation pool contains the positive plus 63 sampled semantic alternatives.

The same sampled candidate pool is also scored by a state-blind baseline: training-row frequency of each semantic joint action within the sampled action-family pool. That baseline answers how much apparent recall can be explained by action-frequency structure without looking at battle state.

These are sampled semantic retrieval metrics. They are not exact legal-menu recall and are not gameplay-strength measurements because the historical public replay cannot prove the exact menu.

Team-archetype metrics are deferred until an authority-safe replay/team-linking or preview-clustering definition exists. The trainer does not infer a hidden published team from replay evidence.

## Artifacts

Outputs stay outside Git under `models/semantic-policy/<dataset-run-id>/<training-id>/` and include `model.npz`, `action-vocabulary.json.gz`, and `report.json`. The report binds the model to the dataset run, source fingerprint, Showdown revision, shard hashes, model/feature schemas, hyperparameters, rating weights, action-vocabulary hash, and random seed.

Human-readable aliases live separately in `models/semantic-policy/aliases.json`. Aliases never replace immutable dataset/training IDs in provenance, and an existing alias cannot be rebound to a different run.

Post-hoc evaluation writes `diagnostics.json` beside the saved model. It reloads the frozen model, vocabulary, and dataset split and recomputes the new baseline/generalization metrics without rerunning training epochs or mutating the original training report.

## Running

Train against a frozen audit:

```powershell
.\train-replay-policy.ps1 -RunId <audit-run-id>
```

For a quick end-to-end check:

```powershell
.\train-replay-policy.ps1 -RunId <audit-run-id> -Epochs 1 -MaxTrainRows 10000 -MaxEvalRows 2000
```

Check status:

```powershell
.\train-replay-policy.ps1 -RunId <audit-run-id> -Status
```

Register aliases while training or when reusing an already-complete training identity:

```powershell
.\train-replay-policy.ps1 -RunId 413769c4a1ce3a35d35b -Epochs 6 `
    -DatasetAlias mc71k-semantic-full-v1 -TrainingAlias mc71k-bc-v1-6ep
```

Retroactively alias existing runs:

```powershell
.\replay-policy-tools.ps1 alias-dataset mc50k-semantic-v1 e3e4e78563f34fabd35c
.\replay-policy-tools.ps1 alias-training mc50k-bc-v1-6ep e714047872b7963ddd35 `
    --dataset mc50k-semantic-v1
```

Re-evaluate a saved model without retraining it, then compare runs:

```powershell
.\replay-policy-tools.ps1 evaluate mc50k-bc-v1-6ep
.\replay-policy-tools.ps1 evaluate mc71k-bc-v1-6ep
.\replay-policy-tools.ps1 compare mc50k-bc-v1-6ep mc71k-bc-v1-6ep
```

The model is not connected to the live selector in this phase. Search remains the player. The next gate is honest offline evaluation first, followed later by an authority-safe adapter that projects model scores onto the bot's exact legal menu without removing the protected tactical baseline.
