# VGCPastes team corpus

The first complete-team source is the public **VGCPastes Repository** Google Sheet. The
importer reads the Champions M-C, M-B, and M-A tabs, preserves each sheet snapshot, downloads
the linked Pokepaste raw text, and validates/normalizes the team through the project's pinned
Pokemon Showdown runtime.

This dataset is simulator-side ground truth. Closed-team-sheet secrecy is applied later at the
battle observation boundary; the corpus itself should preserve every exact field that the
published paste provides.

## Source mapping

The importer currently tracks:

| Key | Sheet | Showdown format |
| --- | --- | --- |
| `mc` | Champions M-C | `gen9championsvgc2026regmc` |
| `mb` | Champions M-B | `gen9championsvgc2026regmb` |
| `ma` | Champions M-A | `gen9championsvgc2026regma` |

The public Google Sheet is used as an index. Each row contributes provenance such as team ID,
player/owner, event, placement, source links, EV completeness, six displayed species, and its
Pokepaste URL. The linked Pokepaste `/raw` response is the preserved team text.

No bulk team data is committed to Git.

## External layout

With the primary development-machine data root:

```text
F:\Showdown replay data\
└── teams\
    ├── raw\
    │   ├── mc\
    │   ├── mb\
    │   └── ma\
    ├── canonical\
    │   ├── mc\
    │   ├── mb\
    │   └── ma\
    ├── index\
    │   ├── mc\
    │   ├── mb\
    │   └── ma\
    └── manifests\
        └── teams.sqlite3
```

Index snapshots are content-addressed by SHA-256. Raw Pokepastes are stored by regulation,
team ID, and paste slug so a later source change does not silently destroy an older raw file.

## Validation and exact-truth eligibility

For every downloaded paste, the pinned Showdown runtime:

1. imports the text with Showdown's own `Teams.import`;
2. validates it with the target regulation's `TeamValidator`;
3. returns the structured sets and packed team;
4. emits a canonical Showdown export using Champions Stat Points.

The manifest records the exact pinned Showdown revision used for validation.

A row is marked `exact_truth_ready` only when:

- Showdown validation succeeds;
- Showdown parsed exactly six Pokemon;
- the VGCPastes source row lists six species; and
- the source explicitly marks `EVs = Yes`.

Teams without EV information, invalid teams, and validation errors are retained rather than
silently repaired or discarded. They can still be useful for composition or partial-set
statistics, but they are not exact simulator ground truth.

## Running it

After updating the local repository and pinned Showdown build:

```powershell
.\download-teams.ps1
```

The default order is current regulation first: M-C, then M-B, then M-A. A run processes at
most 500 teams so collection is checkpoint-friendly.

Useful variants:

```powershell
# Process all pending teams across all three regulations
.\download-teams.ps1 -MaxTeams 0

# Current regulation only
.\download-teams.ps1 -Regulations mc -MaxTeams 0

# M-B and M-A only
.\download-teams.ps1 -Regulations mb,ma -MaxTeams 0

# Local status, no network
.\download-teams.ps1 -Status
```

The installed Python entry point is also available:

```powershell
champions-teams --data-root "F:\Showdown replay data" --regulations mc mb ma
```

## Refresh behavior

Every invocation refreshes the small public Google Sheet indexes. Already archived teams are
not re-downloaded when the team ID, Pokepaste URL, and pinned Showdown validation revision are
unchanged.

If the pinned Showdown revision changes, archived raw bytes are revalidated locally without
hitting Pokepaste again. If a team's Pokepaste URL changes, the new raw paste is archived
alongside the previous source file and becomes the current manifest record.

## Deliberate boundary

This importer does not expose complete opponent sets to the live bot. It only builds the
offline truth corpus. Self-play and evaluation may instantiate an exact team from this corpus;
the existing public-view/closed-sheet boundary is responsible for deciding what the acting
agent can observe.
