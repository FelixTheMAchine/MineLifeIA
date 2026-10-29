[CmdletBinding()]
param([switch]$Setup, [switch]$InstallMod, [string]$MinecraftDir = (Join-Path $env:APPDATA '.minecraft'), [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
if ($Setup) { & "$PSScriptRoot\Setup.ps1"; if ($LASTEXITCODE -ne 0) { throw 'Preparacao falhou' } }
if ($InstallMod) { & "$PSScriptRoot\Install-Mod.ps1" -MinecraftDir $MinecraftDir -World 'ia' }
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Execute novamente com -Setup' }
$health = $null
try { $health = Invoke-RestMethod 'http://127.0.0.1:8765/health' -TimeoutSec 2 } catch { }
if ($health -and ($health.service -ne 'MineLife AI' -or $health.version -ne '0.2.0')) { throw 'Porta 8765 ocupada por outro backend/versao. Encerre-o antes de atualizar.' }
if (-not $health) {
    New-Item -ItemType Directory -Force -Path 'data\logs' | Out-Null
    $process = Start-Process -FilePath $pythonPath -ArgumentList @('-m','agent.main') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot 'data\logs\backend.out.log') -RedirectStandardError (Join-Path $projectRoot 'data\logs\backend.err.log')
    $process.Id | Set-Content -LiteralPath 'data\backend.pid'
    for ($attempt=0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 250
        try { $health = Invoke-RestMethod 'http://127.0.0.1:8765/health' -TimeoutSec 1; break } catch { }
    }
    if (-not $health -or $health.version -ne '0.2.0') { throw 'Backend nao iniciou; consulte data\logs\backend.err.log' }
}
if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:8765' }
Write-Host 'MineLife AI 0.2.0 iniciado. Abra Minecraft, entre em ia e pressione F8.'
Write-Host 'Painel: http://127.0.0.1:8765. Token em config/local.json (nao publicar).'
