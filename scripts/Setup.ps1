$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -3.11 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 indisponivel' }
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Falha nas dependencias Python' }
& .\.venv\Scripts\python.exe -c 'from agent.config import load_config; load_config()'
if ($LASTEXITCODE -ne 0) { throw 'Configuracao local invalida' }
& .\mod\gradlew.bat -p mod build --console=plain
if ($LASTEXITCODE -ne 0) { throw 'Falha na compilacao' }
& .\mod\gradlew.bat -p mod --stop
