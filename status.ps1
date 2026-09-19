param(
    [switch]$Logs
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "scripts\showdown-utils.ps1")

$Python = Join-Path $ChampionProjectRoot ".venv\Scripts\python.exe"

Write-Host "Champions Practice Bot status"
Write-Host "============================"
Write-Host "Project:  $ChampionProjectRoot"

if (Get-Command git -ErrorAction SilentlyContinue) {
    $Branch = (& git -C $ChampionProjectRoot branch --show-current).Trim()
    $Commit = (& git -C $ChampionProjectRoot rev-parse --short HEAD).Trim()
    $Changes = @(& git -C $ChampionProjectRoot status --porcelain)
    Write-Host "Git:      $Branch @ $Commit ($($Changes.Count) local change(s))"
}

if (Test-Path $Python) {
    $PythonVersion = (& $Python --version).Trim()
    Write-Host "Python:   $PythonVersion"
}
else {
    Write-Host "Python:   missing .venv"
}

if (Get-Command node -ErrorAction SilentlyContinue) {
    Write-Host "Node:     $((& node --version).Trim())"
}

$TrackedPid = Get-ChampionsTrackedShowdownPid
$PortOpen = Test-ChampionsTcpPort

if ($null -ne $TrackedPid -and $PortOpen) {
    Write-Host "Showdown: running, tracked PID $TrackedPid"
}
elseif ($null -ne $TrackedPid) {
    Write-Host "Showdown: tracked PID $TrackedPid, but port 8000 is not listening"
}
elseif ($PortOpen) {
    Write-Host "Showdown: port 8000 is open, but process is untracked"
}
else {
    Write-Host "Showdown: stopped"
}

$ConfigPath = Join-Path $ChampionShowdownRoot "config\config.js"
if (Test-Path $ConfigPath) {
    $Binding = Select-String -Path $ConfigPath -Pattern "^\s*exports\.bindaddress\s*=" | Select-Object -Last 1
    if ($null -ne $Binding) {
        Write-Host "Binding:  $($Binding.Line.Trim())"
    }
}

if ($Logs) {
    Write-Host ""
    Show-ChampionsShowdownLogTail -Lines 30
}
