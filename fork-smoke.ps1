$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Showdown = Join-Path $Root "external\pokemon-showdown"
$Script = Join-Path $Root "tools\showdown-fork-smoke.js"

if (-not (Test-Path (Join-Path $Showdown "dist\sim\battle.js"))) {
    throw "Built Pokemon Showdown simulator was not found. Run .\setup.ps1 first."
}

Write-Host "Testing exact Showdown state serialization and forked branches..."
& node $Script

if ($LASTEXITCODE -ne 0) {
    throw "Showdown state fork smoke test failed."
}
