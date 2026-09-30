$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}

Write-Host "Testing worker lifecycle hardening..."
& $Python -m champions_practice.worker_lifecycle_hardening_smoke

if ($LASTEXITCODE -ne 0) {
    throw "Worker lifecycle hardening smoke test failed."
}
