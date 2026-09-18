# Champions Practice Bot

Offline Pokémon Champions doubles practice environment.

The project is intentionally split into three pieces:

1. **Pokémon Showdown** is the authoritative battle engine. We use its official Champions mod instead of reimplementing battle mechanics.
2. **poke-env** is the Python interface to the local Showdown server.
3. **champions-practice-bot** contains our team-preview logic, opponent AI, hidden-information model, tests, and eventually a local practice UI.

The public `Nolelle/pokemon-vgc-ai` repository is useful as a reference implementation, but it is **not a dependency and no source is copied from it** unless its licensing changes. The setup script can optionally clone it into a gitignored reference directory for inspection.

## Target format

`gen9championsvgc2026regmc`

## Requirements

- Windows PowerShell 7+ recommended
- Git
- Python 3.12
- Node.js 22.18 or newer

## Quick start

Clone this repository and run:

```powershell
.\setup.ps1
```

To also clone the AI reference repository:

```powershell
.\setup.ps1 -IncludeReferenceRepo
```

The setup script:

- creates `.venv`;
- installs this package and development dependencies;
- clones or updates Pokémon Showdown under `external/pokemon-showdown`;
- installs Showdown's Node dependencies;
- builds Showdown;
- runs the Python smoke tests.

After setup:

```powershell
.\run.ps1
```

The first milestone is deliberately narrow: prove that Python can connect to a local Showdown server advertising the Champions M-C format. Battle AI comes after the rules-engine connection is trustworthy.

## Repository layout

```text
champions-practice-bot/
├── src/champions_practice/
├── tests/
├── external/                 # gitignored local dependencies
├── setup.ps1
├── run.ps1
└── pyproject.toml
```

## Licensing

Our code will use its own license once we choose one.

Pokémon Showdown is MIT-licensed. Its copyright/license notices remain with the upstream checkout under `external/pokemon-showdown`.

The AI reference repository is currently treated as read-only reference material and is not redistributed by this project.
