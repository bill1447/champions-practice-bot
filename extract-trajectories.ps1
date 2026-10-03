param(
    [string]$DataRoot = $(if ($env:CHAMPIONS_REPLAY_DATA_ROOT) {
        $env:CHAMPIONS_REPLAY_DATA_ROOT
    }
    else {
        "F:\Showdown replay data"
    }),
    [string]$Format = "gen9championsvgc2026regmc",
    [int]$MaxReplays = 5000,
    [switch]$Refresh,
    [switch]$Strict,
    [switch]$Status
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment missing. Run setup.ps1 first."
}

$TrajectoryArgs = @(
    "-m",
    "champions_practice.replay_trajectories",
    "--data-root",
    $DataRoot,
    "--format",
    $Format,
    "--max-replays",
    "$MaxReplays"
)

if ($Refresh) {
    $TrajectoryArgs += "--refresh"
}
if ($Strict) {
    $TrajectoryArgs += "--strict"
}
if ($Status) {
    $TrajectoryArgs += "--status"
}

Write-Host "Replay data root: $DataRoot"
Write-Host "Replay format:    $Format"
& $Python @TrajectoryArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
