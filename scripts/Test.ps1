$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path $PSScriptRoot -Parent)
Push-Location mod
try { & .\gradlew.bat build --console=plain; if ($LASTEXITCODE -ne 0) { throw 'Build Fabric falhou' } }
finally { Pop-Location }
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Testes Python falharam' }
