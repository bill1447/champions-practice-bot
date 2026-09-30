$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}

Write-Host "Testing hidden-state pre-seal choice isolation..."
& $Python -m champions_practice.legality_oracle_smoke

if ($LASTEXITCODE -ne 0) {
    throw "Legality oracle smoke test failed."
}
