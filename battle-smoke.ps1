$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}

& (Join-Path $Root "validate-team.ps1")
& (Join-Path $Root "start-showdown.ps1")

Write-Host ""
& $Python -m champions_practice.battle_smoke
if ($LASTEXITCODE -ne 0) {
    throw "Automated Champions battle smoke test failed."
}
