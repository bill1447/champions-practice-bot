$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "scripts\showdown-utils.ps1")

if (-not (Test-Path (Join-Path $ChampionShowdownRoot "pokemon-showdown"))) {
    throw "Pokemon Showdown checkout is missing. Run .\setup.ps1 first."
}

Initialize-ChampionsRuntime
Set-ChampionsShowdownLocalConfig

$TrackedPid = Get-ChampionsTrackedShowdownPid
if ($null -ne $TrackedPid) {
    if (Test-ChampionsTcpPort) {
        Write-Host "Showdown is already running on 127.0.0.1:8000 (PID $TrackedPid)."
        exit 0
    }
    throw "Tracked Showdown process PID $TrackedPid exists, but port 8000 is not listening."
}

if (Test-ChampionsTcpPort) {
    throw "Port 8000 is already in use by an untracked process. Refusing to start another server."
}

Remove-Item -Force $ChampionShowdownStdout, $ChampionShowdownStderr -ErrorAction SilentlyContinue

$Node = (Get-Command node -ErrorAction Stop).Source
Write-Host "Starting persistent local Pokemon Showdown server..."

$StartArgs = @{
    FilePath = $Node
    ArgumentList = @("pokemon-showdown", "start", "--no-security")
    WorkingDirectory = $ChampionShowdownRoot
    RedirectStandardOutput = $ChampionShowdownStdout
    RedirectStandardError = $ChampionShowdownStderr
    WindowStyle = "Hidden"
    PassThru = $true
}
$Process = Start-Process @StartArgs

Set-Content -Path $ChampionShowdownPidFile -Value $Process.Id -Encoding ASCII

$Ready = $false
for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
    Start-Sleep -Milliseconds 500

    if ($Process.HasExited) {
        Show-ChampionsShowdownLogTail
        Remove-Item -Force $ChampionShowdownPidFile -ErrorAction SilentlyContinue
        throw "Pokemon Showdown exited during startup with code $($Process.ExitCode)."
    }

    if (Test-ChampionsTcpPort) {
        $Ready = $true
        break
    }
}

if (-not $Ready) {
    Show-ChampionsShowdownLogTail
    & taskkill.exe /PID $Process.Id /T /F | Out-Null
    Remove-Item -Force $ChampionShowdownPidFile -ErrorAction SilentlyContinue
    throw "Pokemon Showdown did not begin listening on 127.0.0.1:8000 within 15 seconds."
}

Write-Host "Showdown is running on 127.0.0.1:8000 (PID $($Process.Id))."
Write-Host "Logs: $ChampionRuntimeRoot"
