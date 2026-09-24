$ChampionProjectRoot = Split-Path -Parent $PSScriptRoot
$ChampionShowdownRoot = Join-Path $ChampionProjectRoot "external\pokemon-showdown"
$ChampionRuntimeRoot = Join-Path $ChampionProjectRoot ".runtime"
$ChampionShowdownPidFile = Join-Path $ChampionRuntimeRoot "showdown.pid"
$ChampionShowdownStdout = Join-Path $ChampionRuntimeRoot "showdown.stdout.log"
$ChampionShowdownStderr = Join-Path $ChampionRuntimeRoot "showdown.stderr.log"

$ChampionShowdownVersionFile = Join-Path $ChampionProjectRoot "showdown-version.txt"

function Get-ChampionsShowdownCommit {
    if (-not (Test-Path $ChampionShowdownVersionFile)) {
        throw "Pokemon Showdown pin file is missing: $ChampionShowdownVersionFile"
    }

    $Commit = (Get-Content -Path $ChampionShowdownVersionFile -Raw).Trim().ToLowerInvariant()
    if ($Commit -notmatch '^[0-9a-f]{40}$') {
        throw "Pokemon Showdown pin must be a full 40-character git SHA. Found '$Commit'."
    }

    return $Commit
}

function Sync-ChampionsShowdownCheckout {
    param(
        [switch]$CloneIfMissing
    )

    $Commit = Get-ChampionsShowdownCommit
    $GitDir = Join-Path $ChampionShowdownRoot ".git"
    $FreshClone = $false

    if (-not (Test-Path $GitDir)) {
        if (Test-Path $ChampionShowdownRoot) {
            throw "$ChampionShowdownRoot exists but is not a git checkout."
        }
        if (-not $CloneIfMissing) {
            throw "Pokemon Showdown checkout is missing. Run .\setup.ps1 first."
        }

        $ShowdownParent = Split-Path -Parent $ChampionShowdownRoot
        New-Item -ItemType Directory -Force -Path $ShowdownParent | Out-Null

        Write-Host "Cloning Pokemon Showdown dependency..."
        & git clone --filter=blob:none --no-checkout "https://github.com/smogon/pokemon-showdown.git" $ChampionShowdownRoot
        if ($LASTEXITCODE -ne 0) {
            throw "Pokemon Showdown clone failed."
        }
        $FreshClone = $true
    }

    if (-not $FreshClone) {
        $Changes = @(& git -C $ChampionShowdownRoot status --porcelain)
        if ($Changes.Count -gt 0) {
            throw "Pokemon Showdown checkout has local changes. Clean or stash them before synchronizing the pinned revision."
        }
    }

    & git -C $ChampionShowdownRoot cat-file -e "$Commit^{commit}" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Fetching Pokemon Showdown history for pinned revision..."
        $IsShallowOutput = & git -C $ChampionShowdownRoot rev-parse --is-shallow-repository
        $IsShallow = "$IsShallowOutput".Trim()
        if ($IsShallow -eq "true") {
            & git -C $ChampionShowdownRoot fetch --unshallow --filter=blob:none origin
        }
        else {
            & git -C $ChampionShowdownRoot fetch --filter=blob:none origin
        }
        if ($LASTEXITCODE -ne 0) {
            throw "Pokemon Showdown fetch failed."
        }
    }

    & git -C $ChampionShowdownRoot cat-file -e "$Commit^{commit}" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Pinned Pokemon Showdown revision $Commit is not available from origin."
    }

    Write-Host "Checking out pinned Pokemon Showdown revision $Commit"
    & git -C $ChampionShowdownRoot checkout --detach $Commit
    if ($LASTEXITCODE -ne 0) {
        throw "Pokemon Showdown checkout of pinned revision failed."
    }

    $ActualOutput = & git -C $ChampionShowdownRoot rev-parse HEAD
    $Actual = "$ActualOutput".Trim().ToLowerInvariant()
    if ($Actual -ne $Commit) {
        throw "Pokemon Showdown revision mismatch: expected $Commit, found $Actual."
    }

    Write-Host "Pokemon Showdown revision verified: $Commit"
}

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
