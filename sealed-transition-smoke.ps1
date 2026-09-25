$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}

Write-Host "Testing sealed forced-switch and terminal transitions..."
& $Python -m champions_practice.sealed_transition_smoke

if ($LASTEXITCODE -ne 0) {
    throw "Sealed transition smoke test failed."
}
