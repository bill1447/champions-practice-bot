$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}

& $Python -m champions_practice.team_corpus_smoke
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
