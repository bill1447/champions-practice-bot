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
    $BranchOutput = & git -C $ChampionProjectRoot branch --show-current
    $Branch = if ($null -eq $BranchOutput) { "" } else { "$BranchOutput".Trim() }
    $Commit = "$(& git -C $ChampionProjectRoot rev-parse --short HEAD)".Trim()
    if ([string]::IsNullOrWhiteSpace($Branch)) {
        $Branch = "(detached)"
    }
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

if (
    (Get-Command git -ErrorAction SilentlyContinue)
    -and (Test-Path (Join-Path $ChampionShowdownRoot ".git"))
) {
    $PinnedShowdown = Get-ChampionsShowdownCommit
    $ActualShowdown = "$(& git -C $ChampionShowdownRoot rev-parse HEAD)".Trim().ToLowerInvariant()
    $PinState = if ($ActualShowdown -eq $PinnedShowdown) { "matches pin" } else { "PIN MISMATCH" }
    Write-Host (
        "Engine:   "
        + $ActualShowdown.Substring(0, 8)
        + " (pin "
        + $PinnedShowdown.Substring(0, 8)
        + "; "
        + $PinState
        + ")"
    )
}
elseif (Test-Path $ChampionShowdownVersionFile) {
    $PinnedShowdown = Get-ChampionsShowdownCommit
    Write-Host "Engine:   checkout missing (pin $($PinnedShowdown.Substring(0, 8)))"
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
