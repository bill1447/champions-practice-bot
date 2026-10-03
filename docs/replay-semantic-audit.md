# Replay semantic-policy corpus audit

This stage measures how much of the public replay archive can support supervised policy
learning without inventing private commands.

It consumes the deterministic replay trajectories produced by PR #146 and writes a
replay-disjoint semantic-action dataset plus an audit summary. It still does **not** train a
model.

## Why semantic labels

A normal public Showdown replay can often reveal that a player used, for example:

- Protect + Close Combat;
- switch to Rillaboom + Dire Claw;
- a generic Mega action plus another move.

It does not prove the complete player-side request required to reconstruct every legal
Showdown command. PR #147 therefore maps to an exact legal-menu index only when an
authoritative menu is supplied.

The broad corpus instead uses a semantic label:

```json
{
  "actions": [
    {"slot": 1, "kind": "switch", "switch_species_id": "rillaboom"},
    {"slot": 2, "kind": "move", "move": "direclaw", "gimmicks": []}
  ],
  "action_family": "switch+move"
}
```

Only trajectory rows with `identity_complete=true` become semantic training examples.
Incomplete rows remain audit evidence and are counted by missing reason.

## Pinned move metadata

The audit asks the pinned Showdown runtime for static move target metadata. This is used only
to determine whether the public move identity would have required a selected target at the
decision boundary.

The target analysis deliberately ignores the replay's resolved target. Instead it combines:

- the pinned move target type;
- the choosing slot;
- the public occupied active slots at the decision boundary;
- the same doubles slot geometry used by Showdown.

A row is tagged `selected_target_ambiguous=true` when more than one public target location
was selectable from that semantic move identity. That measures a real reason an exact command
cannot be recovered from the public replay label alone.

Switch rows are separately tagged as requiring player-side party-slot-order context because
`switch N` is an exact menu command while public replay action identity is species based.

Generic public Mega evidence is also counted separately because it may not distinguish exact
Mega variants.

## Leakage-safe splits

Every replay is assigned to exactly one split by a stable SHA-256 hash of `replay_id`:

- 90% train;
- 5% validation;
- 5% test.

All turns and both player sides from the same replay therefore remain in the same split.

The split algorithm is versioned as `replay-group-sha256-90-5-5-v1`.

## Output

Generated files stay outside Git under:

```text
<external root>/
  processed/
    replay-policy/
      <format>/
        latest-summary.json
        runs/
          <run-id>/
            summary.json
            train/part-00000.jsonl.gz
            validation/part-00000.jsonl.gz
            test/part-00000.jsonl.gz
```

The run ID binds:

- semantic-policy schema;
- split schema;
- format;
- the sorted trajectory source fingerprint;
- pinned Showdown revision.

Compressed JSONL shards default to 50,000 rows each.

## Audit metrics

The summary reports:

- raw replay count and trajectory coverage;
- total side-turn rows;
- complete semantic labels and coverage rate;
- incomplete-label reasons;
- move/move, move/switch, switch/move, switch/switch and other action-family counts;
- rating-band coverage;
- exact turn and turn-band distributions;
- replay-disjoint train/validation/test counts;
- selected-target ambiguity exposure;
- rows requiring switch party-order context;
- generic Mega context;
- unknown pinned move metadata;
- usable semantic rows per replay.

These measurements are intended to decide whether the broad semantic-action corpus is large
and clean enough for the first behavior-cloned prior or whether additional authoritative
player-side request enrichment is worth the cost.

## Running

First ensure the raw archive has been converted into trajectories:

```powershell
.\extract-trajectories.ps1 -MaxReplays 0
```

Then build and audit the semantic corpus:

```powershell
.\audit-replay-policy.ps1
```

Status without rebuilding:

```powershell
.\audit-replay-policy.ps1 -Status
```

For a bounded test:

```powershell
.\audit-replay-policy.ps1 -MaxReplays 5000
```

The downloader may continue growing the raw archive. A later trajectory extraction and audit
will produce a new source fingerprint and therefore a new semantic dataset run.
