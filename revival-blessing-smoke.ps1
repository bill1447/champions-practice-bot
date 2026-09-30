$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}

Write-Host "Testing Revival Blessing request support..."
& $Python -m champions_practice.revival_blessing_smoke

if ($LASTEXITCODE -ne 0) {
    throw "Revival Blessing smoke test failed."
}
