$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}

& (Join-Path $Root "start-showdown.ps1")

Write-Host ""
& $Python -m champions_practice.smoke
if ($LASTEXITCODE -ne 0) {
    throw "Showdown connectivity test failed."
}

Write-Host ""
Write-Host "Showdown will remain running for remote work."
Write-Host "Use .\status.ps1 -Logs to inspect it or .\stop-showdown.ps1 to stop it."
