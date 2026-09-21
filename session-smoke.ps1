$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}

Write-Host "Testing persistent battle-session API..."
& $Python -m champions_practice.session_smoke

if ($LASTEXITCODE -ne 0) {
    throw "Battle-session API smoke test failed."
}
