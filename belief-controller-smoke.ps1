$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    throw "Virtual environment missing. Run setup.ps1 first."
}
& ".\.venv\Scripts\python.exe" -m champions_practice.belief_controller_smoke
