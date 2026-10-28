[CmdletBinding()]
param([switch]$Publish)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
if ($Publish) {
    & .\.venv\Scripts\python.exe -m agent.journal.github_publisher --publish
} else {
    & .\.venv\Scripts\python.exe -m agent.journal.github_publisher
}
exit $LASTEXITCODE
