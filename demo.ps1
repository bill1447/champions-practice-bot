$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}

& (Join-Path $Root "showdown-runtime-gate.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "Showdown runtime verification failed."
}

& $Python -m champions_practice.demo_server @args
if ($LASTEXITCODE -ne 0) {
    throw "Playable demo exited with an error."
}
