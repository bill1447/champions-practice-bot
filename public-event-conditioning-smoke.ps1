$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}

Write-Host "Testing authoritative public mechanics event conditioning..."
& $Python -m champions_practice.public_event_conditioning_smoke

if ($LASTEXITCODE -ne 0) {
    throw "Public event conditioning smoke test failed."
}
