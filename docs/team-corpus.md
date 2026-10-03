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

| Key | Sheet | Historical regulation | Validation path in current pin |
| --- | --- | --- | --- |
| `mc` | Champions M-C | `gen9championsvgc2026regmc` | exact M-C validator |
| `mb` | Champions M-B | `gen9championsvgc2026regmb` | exact M-B validator |
| `ma` | Champions M-A | `gen9championsvgc2026regma` | Champions Doubles Custom Game |

The pinned Showdown revision still contains the exact M-C and M-B formats, but no longer
contains an M-A format entry. M-A pastes are therefore parsed and structurally normalized
through `gen9championsdoublescustomgame`; this does **not** claim historical M-A regulation
legality.

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
2. validates it through the configured validator path;
3. returns the structured sets and packed team;
4. emits a canonical Showdown export using Champions Stat Points.

The manifest records the exact pinned Showdown revision and validator format used.

Two readiness fields are deliberately separate:

- `exact_team_ready` means the published paste is a complete six-Pokemon build suitable for
  use as hidden simulator truth: Showdown accepts the configured parse/validation path, the
  source explicitly marks `EVs = Yes`, Showdown parsed six sets, and the index lists six
  species.
- `regulation_validated` means the same pinned Showdown runtime actually contains and
  validates the exact historical regulation. This is available for M-C and M-B in the
  current pin. It is intentionally false for M-A.

A future battle or benchmark must still validate a selected team against the format it is
about to instantiate. `exact_team_ready` is not permission to treat an M-A team as legal in
M-C.

Teams without EV information, invalid teams, and validation errors are retained rather than
silently repaired or discarded. They can still be useful for composition or partial-set
statistics.

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

If the pinned Showdown revision or configured validator path changes, archived raw bytes are
revalidated locally without hitting Pokepaste again. If a team's Pokepaste URL changes, the
new raw paste is archived alongside the previous source file and becomes the current manifest
record.

## Deliberate boundary

This importer does not expose complete opponent sets to the live bot. It only builds the
offline truth corpus. Self-play and evaluation may instantiate an exact team from this corpus;
the existing public-view/closed-sheet boundary is responsible for deciding what the acting
agent can observe.
