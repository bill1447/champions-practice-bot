$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}

Write-Host "Testing absolute deadline worker cleanup..."
& $Python -m champions_practice.timeout_lifecycle_smoke

if ($LASTEXITCODE -ne 0) {
    throw "Timeout lifecycle smoke test failed."
}
