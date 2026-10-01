$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}

Write-Host "Testing ordered both-side execution authority..."
& $Python -m champions_practice.execution_authority_smoke

if ($LASTEXITCODE -ne 0) {
    throw "Ordered both-side execution authority smoke test failed."
}
