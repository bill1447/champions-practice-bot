param(
    [string]$DataRoot = $(if ($env:CHAMPIONS_REPLAY_DATA_ROOT) {
        $env:CHAMPIONS_REPLAY_DATA_ROOT
    }
    else {
        "F:\Showdown replay data"
    }),
    [string[]]$Regulations = @("mc", "mb", "ma"),
    [int]$MaxTeams = 500,
    [double]$DelaySeconds = 0.25,
    [switch]$Status
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment missing. Run setup.ps1 first."
}

$TeamArgs = @(
    "-m",
    "champions_practice.team_corpus",
    "--data-root",
    $DataRoot,
    "--max-teams",
    "$MaxTeams",
    "--delay",
    "$DelaySeconds"
)

if (-not $Status) {
    $TeamArgs += "--regulations"
    $TeamArgs += $Regulations
}
else {
    $TeamArgs += "--status"
}

Write-Host "Team data root: $DataRoot"
if (-not $Status) {
    Write-Host "Regulations:    $($Regulations -join ', ')"
}
& $Python @TeamArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
