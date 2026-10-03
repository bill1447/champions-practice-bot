param(
    [string]$DataRoot = $(if ($env:CHAMPIONS_REPLAY_DATA_ROOT) {
        $env:CHAMPIONS_REPLAY_DATA_ROOT
    }
    else {
        "F:\Showdown replay data"
    }),
    [string[]]$Regulations = @("mc"),
    [int]$Battles = 64,
    [int]$Turns = 8,
    [int]$MaxDecoys = 7,
    [switch]$RefreshPools,
    [switch]$AllowNonauthoritativeRegulation
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment missing. Run setup.ps1 first."
}

$CorpusArgs = @(
    "-m",
    "champions_practice.recovery_corpus",
    "--data-root",
    $DataRoot,
    "--battles",
    "$Battles",
    "--turns",
    "$Turns",
    "--max-decoys",
    "$MaxDecoys",
    "--regulations"
)
$CorpusArgs += $Regulations

if ($RefreshPools) {
    $CorpusArgs += "--refresh-pools"
}
if ($AllowNonauthoritativeRegulation) {
    $CorpusArgs += "--allow-nonauthoritative-regulation"
}

Write-Host "Recovery data root: $DataRoot"
Write-Host "Regulations:       $($Regulations -join ', ')"
Write-Host "Battles/reg:       $Battles"
Write-Host "Turns/battle:      $Turns"
Write-Host "Max decoys:        $MaxDecoys"

& $Python @CorpusArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
