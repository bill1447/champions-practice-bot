param(
    [switch]$IncludeReferenceRepo
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$External = Join-Path $Root "external"
$Showdown = Join-Path $External "pokemon-showdown"
$Reference = Join-Path $External "pokemon-vgc-ai-ref"
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

function Require-Command {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [string]$Help
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command '$Name'. $Help"
    }
}

function Invoke-GitCloneOrPull {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Path
    )

    if (Test-Path (Join-Path $Path ".git")) {
        Write-Host "Updating $Path"
        git -C $Path pull --ff-only
    }
    elseif (Test-Path $Path) {
        throw "$Path exists but is not a git checkout. Move or delete it and rerun setup."
    }
    else {
        Write-Host "Cloning $Url"
        git clone $Url $Path
    }
}

Require-Command git "Install Git for Windows and reopen PowerShell."
Require-Command node "Install Node.js 22.18 or newer and reopen PowerShell."
Require-Command npm "npm should be installed with Node.js."

$NodeVersionText = (& node --version).Trim().TrimStart("v")
$NodeVersion = [version]$NodeVersionText
if ($NodeVersion -lt [version]"22.18.0") {
    throw "Pokemon Showdown currently requires Node.js >= 22.18.0. Found $NodeVersionText."
}

New-Item -ItemType Directory -Force -Path $External | Out-Null

$PyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($PyLauncher) {
    if (-not (Test-Path $Venv)) {
        Write-Host "Creating Python 3.12 virtual environment"
        & py -3.12 -m venv $Venv
    }
}
else {
    Require-Command python "Install Python 3.12 and reopen PowerShell."
    $PythonVersionText = (& python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    if ($PythonVersionText -ne "3.12") {
        throw "This project currently targets Python 3.12. Found Python $PythonVersionText."
    }
    if (-not (Test-Path $Venv)) {
        Write-Host "Creating Python virtual environment"
        & python -m venv $Venv
    }
}

if (-not (Test-Path $Python)) {
    throw "Virtual environment creation failed: $Python was not found."
}

Write-Host "Installing Python package and development dependencies"
& $Python -m pip install --upgrade pip
& $Python -m pip install -e "$Root[dev]"

. (Join-Path $Root "scripts\showdown-utils.ps1")
Sync-ChampionsShowdownCheckout -CloneIfMissing

Write-Host "Installing Pokemon Showdown dependencies"
Push-Location $Showdown
try {
    & npm ci
    & npm run build
}
finally {
    Pop-Location
}

Set-ChampionsShowdownLocalConfig
& $Python -m champions_practice.showdown_build_stamp
if ($LASTEXITCODE -ne 0) {
    throw "Showdown build provenance stamping failed."
}

if ($IncludeReferenceRepo) {
    Invoke-GitCloneOrPull -Url "https://github.com/Nolelle/pokemon-vgc-ai.git" -Path $Reference
}

Write-Host "Running smoke tests"
& $Python -m pytest

Write-Host ""
Write-Host "Setup complete."
Write-Host "Showdown is configured for localhost only."
Write-Host "Use .\start-showdown.ps1, .\status.ps1, .\test-local.ps1, and .\stop-showdown.ps1."
