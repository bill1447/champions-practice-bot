param(
    [switch]$UpdateShowdown
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Showdown = Join-Path $Root "external\pokemon-showdown"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is not available."
}

$LocalChanges = @(& git -C $Root status --porcelain)
if ($LocalChanges.Count -gt 0) {
    throw "The project has local changes. Commit/stash them before running update-local.ps1."
}

Write-Host "Updating project..."
& git -C $Root pull --ff-only
if ($LASTEXITCODE -ne 0) {
    throw "git pull failed."
}

if (-not (Test-Path $Python)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}

Write-Host "Synchronizing Python dependencies..."
& $Python -m pip install -e "$Root[dev]"
if ($LASTEXITCODE -ne 0) {
    throw "Python dependency synchronization failed."
}

if ($UpdateShowdown) {
    if (-not (Test-Path (Join-Path $Showdown ".git"))) {
        throw "Pokemon Showdown checkout is missing. Run .\setup.ps1 first."
    }

    Write-Host "Updating Pokemon Showdown..."
    & git -C $Showdown pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        throw "Showdown git pull failed."
    }

    Push-Location $Showdown
    try {
        & npm install
        if ($LASTEXITCODE -ne 0) {
            throw "Showdown npm install failed."
        }

        & npm run build
        if ($LASTEXITCODE -ne 0) {
            throw "Showdown build failed."
        }
    }
    finally {
        Pop-Location
    }

    . (Join-Path $Root "scripts\showdown-utils.ps1")
    Set-ChampionsShowdownLocalConfig
}

Write-Host "Running unit tests..."
& $Python -m pytest
if ($LASTEXITCODE -ne 0) {
    throw "Unit tests failed."
}

Write-Host ""
Write-Host "Local checkout is current."
