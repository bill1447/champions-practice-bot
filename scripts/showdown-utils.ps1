$ChampionProjectRoot = Split-Path -Parent $PSScriptRoot
$ChampionShowdownRoot = Join-Path $ChampionProjectRoot "external\pokemon-showdown"
$ChampionRuntimeRoot = Join-Path $ChampionProjectRoot ".runtime"
$ChampionShowdownPidFile = Join-Path $ChampionRuntimeRoot "showdown.pid"
$ChampionShowdownStdout = Join-Path $ChampionRuntimeRoot "showdown.stdout.log"
$ChampionShowdownStderr = Join-Path $ChampionRuntimeRoot "showdown.stderr.log"

function Initialize-ChampionsRuntime {
    New-Item -ItemType Directory -Force -Path $ChampionRuntimeRoot | Out-Null
}

function Test-ChampionsTcpPort {
    param(
        [string]$HostName = "127.0.0.1",
        [int]$Port = 8000,
        [int]$TimeoutMs = 500
    )

    $Client = [System.Net.Sockets.TcpClient]::new()
    try {
        $AsyncResult = $Client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $AsyncResult.AsyncWaitHandle.WaitOne($TimeoutMs)) {
            return $false
        }
        $Client.EndConnect($AsyncResult)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $Client.Dispose()
    }
}

function Set-ChampionsShowdownLocalConfig {
    $ConfigPath = Join-Path $ChampionShowdownRoot "config\config.js"
    if (-not (Test-Path $ConfigPath)) {
        throw "Showdown config was not found at $ConfigPath. Run .\setup.ps1 first."
    }

    $Contents = Get-Content -Path $ConfigPath -Raw

    $BindPattern = '(?m)^\s*exports\.bindaddress\s*=\s*[''"][^''"]+[''"];\s*$'
    $BindReplacement = "exports.bindaddress = '127.0.0.1';"
    if ($Contents -match $BindPattern) {
        $Contents = [regex]::Replace($Contents, $BindPattern, $BindReplacement)
    }
    else {
        $Contents += [Environment]::NewLine + $BindReplacement + [Environment]::NewLine
    }

    $PortPattern = '(?m)^\s*exports\.port\s*=\s*\d+;\s*$'
    $PortReplacement = "exports.port = 8000;"
    if ($Contents -match $PortPattern) {
        $Contents = [regex]::Replace($Contents, $PortPattern, $PortReplacement)
    }
    else {
        $Contents += [Environment]::NewLine + $PortReplacement + [Environment]::NewLine
    }

    Set-Content -Path $ConfigPath -Value $Contents -Encoding UTF8
}

function Get-ChampionsTrackedShowdownPid {
    if (-not (Test-Path $ChampionShowdownPidFile)) {
        return $null
    }

    $RawPid = (Get-Content -Path $ChampionShowdownPidFile -Raw).Trim()
    $TrackedPid = 0
    if (-not [int]::TryParse($RawPid, [ref]$TrackedPid)) {
        Remove-Item -Force $ChampionShowdownPidFile
        return $null
    }

    $Process = Get-Process -Id $TrackedPid -ErrorAction SilentlyContinue
    if ($null -eq $Process -or $Process.ProcessName -ne "node") {
        Remove-Item -Force $ChampionShowdownPidFile
        return $null
    }

    return $TrackedPid
}

function Show-ChampionsShowdownLogTail {
    param([int]$Lines = 20)

    if (Test-Path $ChampionShowdownStdout) {
        Write-Host "--- Showdown stdout (last $Lines lines) ---"
        Get-Content -Path $ChampionShowdownStdout -Tail $Lines
    }
    if (Test-Path $ChampionShowdownStderr) {
        Write-Host "--- Showdown stderr (last $Lines lines) ---"
        Get-Content -Path $ChampionShowdownStderr -Tail $Lines
    }
}
