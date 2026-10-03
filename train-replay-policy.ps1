param(
    [string]$DataRoot = $(if ($env:CHAMPIONS_REPLAY_DATA_ROOT) {
        $env:CHAMPIONS_REPLAY_DATA_ROOT
    }
    else {
        "F:\Showdown replay data"
    }),
    [string]$Format = "gen9championsvgc2026regmc",
    [string]$RunId = "",
    [int]$Epochs = 3,
    [int]$BatchSize = 256,
    [int]$TrainNegatives = 15,
    [int]$EvalNegatives = 63,
    [int]$EmbeddingDim = 64,
    [double]$LearningRate = 0.08,
    [int]$Seed = 150,
    [int]$MaxTrainRows = 0,
    [int]$MaxEvalRows = 0,
    [switch]$Refresh,
    [switch]$Status
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment missing. Run setup.ps1 first."
}

$TrainArgs = @(
    "-m",
    "champions_practice.semantic_policy_train",
    "--data-root",
    $DataRoot,
    "--format",
    $Format,
    "--epochs",
    "$Epochs",
    "--batch-size",
    "$BatchSize",
    "--train-negatives",
    "$TrainNegatives",
    "--eval-negatives",
    "$EvalNegatives",
    "--embedding-dim",
    "$EmbeddingDim",
    "--learning-rate",
    "$LearningRate",
    "--seed",
    "$Seed",
    "--max-train-rows",
    "$MaxTrainRows",
    "--max-eval-rows",
    "$MaxEvalRows"
)

if ($RunId) {
    $TrainArgs += @("--run-id", $RunId)
}
if ($Refresh) {
    $TrainArgs += "--refresh"
}
if ($Status) {
    $TrainArgs += "--status"
}

Write-Host "Replay data root: $DataRoot"
Write-Host "Replay format:    $Format"
if ($RunId) {
    Write-Host "Dataset run:      $RunId"
}
else {
    Write-Host "Dataset run:      latest audited run"
}
& $Python @TrainArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
