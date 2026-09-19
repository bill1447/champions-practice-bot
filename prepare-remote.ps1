param(
    [switch]$ApplyPowerSettings
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot

Write-Host "Remote-work readiness"
Write-Host "====================="

$CrDServices = @(Get-Service | Where-Object {
    $_.Name -match "chromoting|remoting" -or
    $_.DisplayName -match "Chrome Remote Desktop"
})

if ($CrDServices.Count -gt 0) {
    foreach ($Service in $CrDServices) {
        Write-Host "Chrome Remote Desktop: $($Service.Status) ($($Service.Name))"
    }
}
else {
    Write-Warning "Chrome Remote Desktop service was not detected. Verify remote access manually before leaving."
}

if ($ApplyPowerSettings) {
    Write-Host ""
    Write-Host "Disabling AC sleep and AC hibernation timeouts..."
    & powercfg.exe /change standby-timeout-ac 0
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to change AC sleep timeout."
    }

    & powercfg.exe /change hibernate-timeout-ac 0
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to change AC hibernation timeout."
    }

    Write-Host "AC sleep and hibernation timeouts are disabled."
}
else {
    Write-Host ""
    Write-Host "Power settings were not changed."
    Write-Host "Run .\prepare-remote.ps1 -ApplyPowerSettings before leaving to disable sleep/hibernate while plugged in."
}

Write-Host ""
Write-Host "Current relevant power settings:"
& powercfg.exe /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE
& powercfg.exe /query SCHEME_CURRENT SUB_SLEEP HIBERNATEIDLE

Write-Host ""
Write-Host "Project status:"
& (Join-Path $Root "status.ps1")

Write-Host ""
Write-Host "Before leaving, test Chrome Remote Desktop from the laptop over a different network if possible."
Write-Host "For outage recovery, configure BIOS/UEFI Restore on AC Power Loss to Power On or Last State."
