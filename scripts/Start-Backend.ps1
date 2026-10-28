[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -3.11 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar ambiente Python 3.11' }
    & .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar dependencias' }
}
Write-Host 'Life Observer: http://127.0.0.1:8765 - Ctrl+C encerra o backend.'
& .\.venv\Scripts\python.exe -m agent.main
exit $LASTEXITCODE
