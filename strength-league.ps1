param(
    [int]$Battles = 8,
    [int]$MaxDecisions = 64,
    [int]$WorldLimit = 8,
    [int]$ParticlesPerWorld = 1,
    [int]$MaxParticles = 8,
    [int]$CandidateLimit = 4,
    [int]$ResponseLimit = 4,
    [int]$StrategicPlanLimit = 2,
    [int]$StrategicCandidateLimit = 3,
    [int]$StrategicResponseLimit = 2,
    [double]$DecisionBudgetSeconds = 8.0,
    [double]$ConditioningBudgetSeconds = 8.0,
    [double]$WorkerStartupTimeoutSeconds = 30.0,
    [int]$Seed = 15601,
    [ValidateSet("current-roster-mirror-v1", "synthetic-spread-uncertainty-v1")]
    [string]$Fixture = "current-roster-mirror-v1",
    [switch]$Refresh
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
    "champions_practice.strength_league",
    "--battles", "$Battles",
    "--fixture", "$Fixture",
    "--max-decisions", "$MaxDecisions",
    "--world-limit", "$WorldLimit",
    "--particles-per-world", "$ParticlesPerWorld",
    "--max-particles", "$MaxParticles",
    "--candidate-limit", "$CandidateLimit",
    "--response-limit", "$ResponseLimit",
    "--strategic-plan-limit", "$StrategicPlanLimit",
    "--strategic-candidate-limit", "$StrategicCandidateLimit",
    "--strategic-response-limit", "$StrategicResponseLimit",
    "--decision-budget-seconds", "$DecisionBudgetSeconds",
    "--conditioning-budget-seconds", "$ConditioningBudgetSeconds",
    "--worker-startup-timeout-seconds", "$WorkerStartupTimeoutSeconds",
    "--seed", "$Seed"
)

if ($Refresh) {
    $ArgsList += "--refresh"
}

Write-Host "Offline strength league"
Write-Host "Fixture:             $Fixture"
Write-Host "Bot:                 belief-strategy-main-v1"
Write-Host "Baseline:            public-fallback-v1"
Write-Host "Battles:             $Battles"
Write-Host "Decision budget:     $DecisionBudgetSeconds s"
Write-Host "Conditioning budget: $ConditioningBudgetSeconds s"
Write-Host "Worker startup:      $WorkerStartupTimeoutSeconds s"
Write-Host "Worlds/particles:    $WorldLimit / $MaxParticles"
Write-Host "Candidate/response:  $CandidateLimit / $ResponseLimit"

& $Python @ArgsList
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
