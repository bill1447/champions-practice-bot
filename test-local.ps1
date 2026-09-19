param(
    [switch]$StopAfter
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}

. (Join-Path $Root "scripts\showdown-utils.ps1")

$WasRunning = Test-ChampionsTcpPort
if (-not $WasRunning) {
    & (Join-Path $Root "start-showdown.ps1")
}

try {
    Write-Host ""
    Write-Host "Running unit tests..."
    & $Python -m pytest
    if ($LASTEXITCODE -ne 0) {
        throw "Unit tests failed."
    }

    Write-Host ""
    Write-Host "Running live Showdown connectivity test..."
    & $Python -m champions_practice.smoke
    if ($LASTEXITCODE -ne 0) {
        throw "Showdown connectivity test failed."
    }
}
finally {
    if ($StopAfter -and -not $WasRunning) {
        & (Join-Path $Root "stop-showdown.ps1")
    }
}
