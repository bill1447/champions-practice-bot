$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment missing. Run setup.ps1 first."
}

& $Python -m champions_practice.public_switch_action_smoke
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
