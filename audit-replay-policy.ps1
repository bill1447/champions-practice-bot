param(
    [string]$DataRoot = $(if ($env:CHAMPIONS_REPLAY_DATA_ROOT) {
        $env:CHAMPIONS_REPLAY_DATA_ROOT
    }
    else {
        "F:\Showdown replay data"
    }),
    [string]$Format = "gen9championsvgc2026regmc",
    [int]$MaxReplays = 0,
    [int]$ShardRows = 50000,
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

$AuditArgs = @(
    "-m",
    "champions_practice.replay_semantic_audit",
    "--data-root",
    $DataRoot,
    "--format",
    $Format,
    "--max-replays",
    "$MaxReplays",
    "--shard-rows",
    "$ShardRows"
)

if ($Refresh) {
    $AuditArgs += "--refresh"
}
if ($Strict) {
    $AuditArgs += "--strict"
}
if ($Status) {
    $AuditArgs += "--status"
}

Write-Host "Replay data root: $DataRoot"
Write-Host "Replay format:    $Format"
& $Python @AuditArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
