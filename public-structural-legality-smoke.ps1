$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}

Write-Host "Testing public structural target legality..."
& $Python -m champions_practice.public_structural_legality_smoke

if ($LASTEXITCODE -ne 0) {
    throw "Public structural target legality smoke test failed."
}
