$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}

Write-Host "Testing public action execution evidence..."
& $Python -m champions_practice.execution_evidence_smoke

if ($LASTEXITCODE -ne 0) {
    throw "Public action execution evidence smoke test failed."
}
