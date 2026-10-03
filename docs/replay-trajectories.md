# Public replay trajectory extraction

The replay trajectory extractor converts archived public Pokémon Showdown replay logs into
deterministic per-game trajectory files for later behavior-cloning work.

It is deliberately narrower than a simulator replay or an exact command log.

## Trust boundary

The extractor consumes only the replay JSON already archived under the external replay data
root. It reads the public `log` field and deliberately ignores `inputlog`, even when a replay
happens to contain one.

The output therefore does not claim information that a normal public replay does not prove:

- a top-level public `|move|` event can establish the selected move identity;
- called moves carrying `[from]` provenance are not treated as a second selected action;
- a public `|cant|` event leaves that slot incomplete rather than inventing the selected
  command;
- a pre-action public switch can provide a conservative switch identity, while obvious public
  forced-switch markers are excluded;
- the move event target is stored only as the resolved public target. It is not promoted to
  the originally selected target because redirection can change it;
- exact Showdown command strings and private move-slot indices are not claimed.

This distinction is important for later policy training. The trajectory layer is an
authority-preserving source dataset, not yet the final legal-menu training tensor.

## Decision-time state

Each `|turn|N` marker defines a normal turn decision boundary. The extractor snapshots only
information already present in the replay prefix at that point:

- team-preview species;
- active species/form, public HP/status and boosts;
- publicly revealed moves, items and abilities;
- weather, field effects and side conditions;
- player names and the turn number.

Each state also carries a SHA-256 hash and line count of the exact public replay prefix used to
produce it. The raw replay remains the audit source if the structured reducer is expanded in a
later schema.

Team preview and mid-turn forced-switch requests are not emitted as policy decision rows in
this first schema.

## Joint-action labels

A decision stores one joint-action record for each side. `identity_complete=true` means every
occupied active slot had a conservatively reconstructible move/switch identity (or a publicly
inferable pass for an empty slot).

It does **not** mean an exact Showdown command is available. In particular, resolved move
targets are retained separately from selected targets, and
`exact_showdown_command_available` remains false.

Incomplete sides stay in the trajectory with explicit missing reasons. They are not silently
turned into training labels.

## Storage and split safety

Generated data remains outside Git:

```text
<external root>/
  raw/<format>/<replay>.json
  trajectories/<format>/<replay>.json
  manifests/replays.sqlite3
```

There is exactly one trajectory document per replay and every document carries
`game_group=<replay_id>`. Downstream train/evaluation splits can therefore group by replay
instead of accidentally placing turns from the same game on both sides of a split.

The manifest stores the source raw hash, trajectory hash, schema, byte count and label counts.
A trajectory is reused only when the source hash and schema still match.

## Running

On Windows:

```powershell
.\extract-trajectories.ps1
```

The launcher defaults to the same external data root and current M-C replay format as the
downloader and processes at most 5,000 newly extracted replays per invocation.

Useful options:

```powershell
.\extract-trajectories.ps1 -MaxReplays 0
.\extract-trajectories.ps1 -Status
.\extract-trajectories.ps1 -Refresh
.\extract-trajectories.ps1 -Strict
```

`-MaxReplays 0` removes the per-run extraction limit. `-Refresh` re-extracts current rows;
it does not modify the archived raw replay.

The next policy-data step should map authority-safe semantic action identities to a legal menu
without converting resolved targets or unavailable commands into fabricated selected actions.
