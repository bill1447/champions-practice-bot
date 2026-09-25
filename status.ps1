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

$GitCommand = Get-Command git -ErrorAction SilentlyContinue
$ShowdownGitDir = Join-Path $ChampionShowdownRoot ".git"

if ($null -ne $GitCommand -and (Test-Path $ShowdownGitDir)) {
    $PinnedShowdown = Get-ChampionsShowdownCommit
    $ActualOutput = & git -C $ChampionShowdownRoot rev-parse HEAD
    $ActualShowdown = "$ActualOutput".Trim().ToLowerInvariant()
    if ($ActualShowdown -eq $PinnedShowdown) {
        $PinState = "matches pin"
    }
    else {
        $PinState = "PIN MISMATCH"
    }

    & git -C $ChampionShowdownRoot diff --quiet HEAD --
    $WorkingTreeDirty = $LASTEXITCODE -eq 1
    & git -C $ChampionShowdownRoot diff --cached --quiet HEAD --
    $IndexDirty = $LASTEXITCODE -eq 1
    $TrackedState = if ($WorkingTreeDirty -or $IndexDirty) {
        "TRACKED MODIFICATIONS"
    }
    else {
        "tracked files clean"
    }

    $ShortActual = $ActualShowdown.Substring(0, 8)
    $ShortPinned = $PinnedShowdown.Substring(0, 8)
    Write-Host "Engine:   $ShortActual (pin $ShortPinned; $PinState; $TrackedState)"
}
elseif (Test-Path $ChampionShowdownVersionFile) {
    $PinnedShowdown = Get-ChampionsShowdownCommit
    $ShortPinned = $PinnedShowdown.Substring(0, 8)
    Write-Host "Engine:   checkout missing (pin $ShortPinned)"
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
