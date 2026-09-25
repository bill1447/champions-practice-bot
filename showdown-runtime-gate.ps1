$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}

Write-Host "Verifying pinned Pokemon Showdown runtime..."
& $Python -m champions_practice.showdown_runtime_gate

if ($LASTEXITCODE -ne 0) {
    throw "Pokemon Showdown runtime verification failed."
}
