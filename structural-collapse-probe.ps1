param(
    [int]$GameIndex = 0,
    [int]$MaxDecisions = 16,
    [double]$DecisionBudgetSeconds = 8.0,
    [double]$ConditioningBudgetSeconds = 8.0,
    [double]$WorkerStartupTimeoutSeconds = 30.0,
    [int]$Seed = 15601
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment missing. Run setup.ps1 first."
}

$ArgsList = @(
    "-m",
    "champions_practice.structural_collapse_probe",
    "--game-index", "$GameIndex",
    "--max-decisions", "$MaxDecisions",
    "--decision-budget-seconds", "$DecisionBudgetSeconds",
    "--conditioning-budget-seconds", "$ConditioningBudgetSeconds",
    "--worker-startup-timeout-seconds", "$WorkerStartupTimeoutSeconds",
    "--seed", "$Seed"
)

Write-Host "Structural belief-collapse probe"
Write-Host "Fixture:             current-roster-mirror-v1"
Write-Host "Game index:          $GameIndex"
Write-Host "Seed:                $Seed"
Write-Host "Decision budget:     $DecisionBudgetSeconds s"
Write-Host "Conditioning budget: $ConditioningBudgetSeconds s"

& $Python @ArgsList
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
