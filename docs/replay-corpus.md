# Replay corpus

PR #141 introduces a resumable archive for public Pokémon Showdown replay JSON.

## Storage boundary

Bulk corpus data must not be stored in the source repository. The primary Windows development
machine uses:

```text
F:\Showdown replay data
```

The downloader refuses any data root that resolves inside the repository. The repository also
ignores common replay/training locations and generated dataset/model formats as a second safety
layer.

The external layout is:

```text
F:\Showdown replay data\
├── raw\
│   └── gen9championsvgc2026regmc\
├── manifests\
│   └── replays.sqlite3
├── processed\
├── trajectories\
├── teams\
├── models\
└── cache\
```

Only downloader code, schemas, tests, and documentation belong in Git. Raw replays, generated
trajectories, downloaded team corpora, caches, databases, and model checkpoints do not.

## Source API

The archive uses Pokémon Showdown's documented public replay API:

- `/search.json?format=<format>` lists public replays for one format;
- searches return at most 51 rows;
- the 51st row indicates that another page exists;
- `before=<uploadtime>` pages backward in time;
- `/<replay-id>.json` returns the replay JSON, including its battle log.

The implementation is deliberately sequential and rate-limited by default. It does not scrape
the HTML replay pages.

## Running it

After normal project setup:

```powershell
.\download-replays.ps1
```

The launcher defaults to the external F: drive path and current Reg M-C format.

Useful variants:

```powershell
# Historical backfill without the per-run 5,000-new-replay cap
.\download-replays.ps1 -MaxReplays 0

# Recheck from the newest replay after a previous historical pass
.\download-replays.ps1 -RestartSearch

# Show local counts/checkpoint without network access
.\download-replays.ps1 -Status

# Override the corpus root
.\download-replays.ps1 -DataRoot "D:\some-other-corpus"
```

The Python entry point is also available:

```powershell
python -m champions_practice.replay_corpus --data-root "F:\Showdown replay data"
```

or through the installed script:

```powershell
champions-replays --data-root "F:\Showdown replay data"
```

`CHAMPIONS_REPLAY_DATA_ROOT` may supply the root for callers that should not embed a machine
path.

## Resume and integrity behavior

Each format has a pagination checkpoint in SQLite. A completed page advances the timestamp
cursor. If the run reaches `--max-replays` in the middle of a page, the cursor does not
advance; the next run re-reads that page and skips already indexed replay IDs.

Replay detail responses are:

1. parsed only to validate that they are JSON battle records;
2. written byte-for-byte to `raw/<format>/<id>.json`;
3. hashed with SHA-256;
4. indexed in SQLite with the search metadata and compact replay metadata.

If a raw file exists but its SQLite row is missing (for example, interruption between the file
write and metadata commit), the next pass validates and re-indexes that existing file instead
of downloading it again.

Individual replay failures are recorded in a persistent retry queue in the local manifest. The
next invocation retries those IDs before continuing pagination, including after the historical
checkpoint is exhausted. By default a failed ID does not discard the successfully archived
remainder of the page; `--strict` makes the first such failure stop the run for debugging.

`--restart-search` resets only the pagination cursor. It never deletes archived replay files
or replay rows. During a refresh, pagination stops at the first complete page made entirely of
already indexed replay IDs, so checking newer uploads does not re-walk the historical archive.

## Scope

This PR archives source data only. It does not yet infer hidden commands, reconstruct
decision-time player views, create behavior-cloning labels, filter by rating, or download team
pastes. Those are separate later steps so the original replay JSON remains an immutable source
of truth.
