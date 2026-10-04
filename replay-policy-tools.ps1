param(
    [string]$DataRoot = $(if ($env:CHAMPIONS_REPLAY_DATA_ROOT) {
        $env:CHAMPIONS_REPLAY_DATA_ROOT
    }
    else {
        "F:\Showdown replay data"
    }),
    [string]$Format = "gen9championsvgc2026regmc",
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("alias-dataset", "alias-training", "evaluate", "compare", "aliases")]
    [string]$Command,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ToolArgs
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment missing. Run setup.ps1 first."
}

& $Python -m champions_practice.semantic_policy_tools --data-root $DataRoot --format $Format $Command @ToolArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
