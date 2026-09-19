$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "scripts\showdown-utils.ps1")

$TrackedPid = Get-ChampionsTrackedShowdownPid
if ($null -eq $TrackedPid) {
    if (Test-ChampionsTcpPort) {
        Write-Warning "Port 8000 is listening, but the process was not started by this project. It was not stopped."
    }
    else {
        Write-Host "Showdown is not running."
    }
    exit 0
}

Write-Host "Stopping Showdown process tree (PID $TrackedPid)..."
& taskkill.exe /PID $TrackedPid /T /F | Out-Null
Start-Sleep -Milliseconds 500
Remove-Item -Force $ChampionShowdownPidFile -ErrorAction SilentlyContinue

if (Test-ChampionsTcpPort) {
    Write-Warning "Port 8000 is still listening after the tracked process tree was stopped."
}
else {
    Write-Host "Showdown stopped."
}
