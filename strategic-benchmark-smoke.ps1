$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment not found. Run .\setup.ps1 first."
}

& $Python -m champions_practice.strategic_benchmark_smoke
if ($LASTEXITCODE -ne 0) {
    throw "Executable strategic benchmark smoke test failed."
}
