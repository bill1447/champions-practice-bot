$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}

Write-Host "Testing persistent Python -> Showdown search bridge..."
& $Python -m champions_practice.search_bridge_smoke

if ($LASTEXITCODE -ne 0) {
    throw "Python / Showdown search bridge smoke test failed."
}
