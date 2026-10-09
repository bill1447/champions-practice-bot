param(
    [string]$Games = "2,8",
    [int]$MaxDecisions = 18,
    [string]$HistoricalReport = "",
    [string]$Output = "runs\rebase-challenge\latest.json",
    [switch]$HistoricalOnly,
    [switch]$RequireRecovery
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment missing. Run setup.ps1 first."
}

$Arguments = @(
    "-m", "champions_practice.rebase_challenge",
    "--output", $Output
)
if (-not $HistoricalOnly) {
    $Arguments += @("--run-games", $Games, "--max-decisions", "$MaxDecisions")
}
if ($HistoricalReport) {
    $Arguments += @("--historical-report", $HistoricalReport)
}
if ($RequireRecovery) {
    $Arguments += "--require-recovery"
}

Write-Host "PR #187: frozen-league collapse reconstruction challenge"
Write-Host "Target cases:          original games 1 (Struggle/Protect), 2 and 8 (Protect/Wood Hammer)"
Write-Host "Fresh games:           $(if ($HistoricalOnly) { 'none (metadata only)' } else { $Games })"
Write-Host "Current-state budget:  8 seconds per reconstruction step"
Write-Host "Oracle:                offline only; never passed to the public constructor"
Write-Host "Live recovery changes: none"
Write-Host "Result:                $Output"

& $Python @Arguments
exit $LASTEXITCODE
