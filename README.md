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

## Initial setup

```powershell
.\setup.ps1 -IncludeReferenceRepo
```

The setup script creates the Python environment, installs dependencies, clones/builds Pokémon Showdown, configures Showdown to listen on **127.0.0.1 only**, and runs the unit tests.

The localhost-only binding is intentional. Chrome Remote Desktop gives you access to the home PC; there is no reason to expose the Showdown development server to the LAN or Internet.

## Continuous integration

Every pull request and push to `main` now runs a Windows GitHub Actions job that installs the Python environment, clones/builds official Pokémon Showdown, lints the project, runs unit tests, validates the Reg M-C team, completes a baseline Champions battle, and completes a heuristic-opponent battle. Runtime logs and battle outputs are uploaded as workflow artifacts for seven days.

This means most code changes can be validated in GitHub without requiring the home PC. The local machine remains useful for interactive testing and later UI work.

## Daily / remote workflow

After merging changes in GitHub:

```powershell
.\update-local.ps1
```

That fast-forwards the project checkout, syncs Python dependencies, and runs unit tests.

Only when we intentionally want to update the upstream Showdown checkout too:

```powershell
.\update-local.ps1 -UpdateShowdown
```

Server controls:

```powershell
.\start-showdown.ps1
.\status.ps1
.\status.ps1 -Logs
.\test-local.ps1
.\stop-showdown.ps1
```

`start-showdown.ps1` launches Showdown as a hidden persistent process and records its PID/logs under `.runtime/`. It is not tied to the PowerShell window used to start it.

`test-local.ps1` runs unit tests plus the live `poke-env` connectivity test. Add `-StopAfter` if it had to start Showdown and you want it shut down afterward.

`validate-team.ps1` asks the official Showdown validator to check the integration team against Reg M-C.

`fork-smoke.ps1` creates a Champions battle directly in the official Showdown simulator, snapshots it after team preview with `Battle.toJSON()`, restores two independent copies with `Battle.fromJSON()`, applies different legal turns, and verifies that the forks diverge without mutating one another. This is the proof-of-concept needed for exact branch search without writing our own battle engine.

`bridge-smoke.ps1` exercises the next layer: Python launches one persistent Node.js search worker, asks it to create an exact Showdown state, then submits multiple branch requests against the same snapshot. This gives the Python AI a low-overhead path to exact Showdown branch evaluation without restarting Node for every candidate.

`session-smoke.ps1` exercises the backend shape intended for the local GUI: start a persistent battle, expose a sanitized human-player view, accept independent team-preview choices, resolve a turn, snapshot the exact internal state for search, and verify the live session produces the same result as an exact fork from that snapshot.

`exact-search-smoke.ps1` exercises the first exact decision layer. It reconstructs the heuristic battle's turn-four position, batches exact Showdown forks for the candidate actions, scores the resulting material and HP, and verifies that switching Indeedee to Armarouge ranks above needlessly sacrificing Indeedee. Candidate actions are ranked by their worst result across the supplied opponent responses, with mean and best results used as tie-breakers.

`battle-smoke.ps1` validates that team, starts Showdown if needed, and runs one complete automated Champions doubles battle between two deterministic baseline players. A successful run proves the full path from team text → team preview → legal doubles actions → Mega Evolution → battle completion.

`ai-smoke.ps1` runs the first real opponent policy against the deterministic baseline. The v0 heuristic now also evaluates all 90 legal bring-4/lead-2 combinations at team preview using only public preview information plus its own known sets. During battle it enumerates every legal joint doubles action exposed by poke-env, scores attacks using base power / accuracy / STAB / type effectiveness / target HP pressure, gives small values to Protect and common support moves, penalizes obvious bad spread choices, and chooses the highest-scoring legal joint action. It is intentionally transparent and shallow; Showdown still resolves the actual turn.

`run.ps1` is a convenience command: it starts Showdown if needed, runs the live connectivity check, and deliberately leaves Showdown running.

## Remote-PC preparation

Before leaving the home PC, run:

```powershell
.\prepare-remote.ps1 -ApplyPowerSettings
```

This checks for the Chrome Remote Desktop service, disables AC sleep/hibernation timeouts, and prints project/server status.

For reliable Chrome Remote Desktop access, the home PC should:

- stay awake while plugged in;
- have Chrome Remote Desktop Host enabled and tested before leaving;
- remain connected by reliable Ethernet/Wi-Fi;
- have Windows configured so an unattended reboot does not require you to physically dismiss firmware prompts.

A power outage is the main failure mode that Windows cannot solve by itself. If the motherboard supports it, set BIOS/UEFI **Restore on AC Power Loss** (sometimes called AC Back, After Power Failure, or Restore Last State) to **Power On** or **Last State**.

## Repository layout

```text
champions-practice-bot/
├── src/champions_practice/
├── scripts/
├── tests/
├── external/                 # gitignored local dependencies
├── .runtime/                 # gitignored PID/log files
├── setup.ps1
├── update-local.ps1
├── prepare-remote.ps1
├── start-showdown.ps1
├── status.ps1
├── test-local.ps1
├── validate-team.ps1
├── battle-smoke.ps1
├── ai-smoke.ps1
├── stop-showdown.ps1
└── run.ps1
```

## Licensing

Our code will use its own license once we choose one.

Pokémon Showdown is MIT-licensed. Its copyright/license notices remain with the upstream checkout under `external/pokemon-showdown`.

The AI reference repository is currently treated as read-only reference material and is not redistributed by this project.
