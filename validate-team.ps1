$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Showdown = Join-Path $Root "external\pokemon-showdown"
$Format = "gen9championsvgc2026regmc"

if (-not (Test-Path $Python)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}
if (-not (Test-Path (Join-Path $Showdown "pokemon-showdown"))) {
    throw "Pokemon Showdown checkout is missing. Run .\setup.ps1 first."
}

Write-Host "Validating integration team against $Format..."

Push-Location $Showdown
try {
    & $Python -m champions_practice.team_text |
        & node pokemon-showdown validate-team $Format

    if ($LASTEXITCODE -ne 0) {
        throw "Showdown rejected the integration team."
    }
}
finally {
    Pop-Location
}

Write-Host "Team validation passed."
