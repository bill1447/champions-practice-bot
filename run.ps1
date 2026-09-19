$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Showdown = Join-Path $Root "external\pokemon-showdown"
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}

if (-not (Test-Path (Join-Path $Showdown "pokemon-showdown"))) {
    throw "Pokemon Showdown checkout is missing. Run .\setup.ps1 first."
}

Write-Host "Starting local Pokemon Showdown server..."
$Process = Start-Process -FilePath "node" -ArgumentList @("pokemon-showdown", "start", "--no-security") -WorkingDirectory $Showdown -PassThru

try {
    Start-Sleep -Seconds 3

    if ($Process.HasExited) {
        throw "Pokemon Showdown exited during startup with code $($Process.ExitCode)."
    }

    Write-Host "Showdown PID: $($Process.Id)"
    Write-Host ""
    & $Python -m champions_practice.smoke
}
finally {
    if (-not $Process.HasExited) {
        Write-Host ""
        Write-Host "Stopping local Showdown server..."
        Stop-Process -Id $Process.Id
    }
}
