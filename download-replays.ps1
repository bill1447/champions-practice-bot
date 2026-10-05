param(
    [string]$DataRoot = $(if ($env:CHAMPIONS_REPLAY_DATA_ROOT) {
        $env:CHAMPIONS_REPLAY_DATA_ROOT
    }
    else {
        "F:\Showdown replay data"
    }),
    [string]$Format = "gen9championsvgc2026regmc",
    [int]$MaxReplays = 5000,
    [double]$DelaySeconds = 0.25,
    [switch]$RestartSearch,
    [switch]$Strict,
    [switch]$Status,
    [switch]$Survey
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment missing. Run setup.ps1 first."
}

$ReplayArgs = @(
    "-m",
    "champions_practice.replay_corpus",
    "--data-root",
    $DataRoot,
    "--format",
    $Format,
    "--max-replays",
    "$MaxReplays",
    "--delay",
    "$DelaySeconds"
)

if ($RestartSearch) {
    $ReplayArgs += "--restart-search"
}
if ($Strict) {
    $ReplayArgs += "--strict"
}
if ($Status) {
    $ReplayArgs += "--status"
}
if ($Survey) {
    $ReplayArgs += "--survey"
}

if (-not $Survey) {
    Write-Host "Replay data root: $DataRoot"
}
Write-Host "Replay format:    $Format"
if ($Survey) {
    Write-Host "Replay mode:      search-index survey (no replay downloads)"
}
& $Python @ReplayArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
