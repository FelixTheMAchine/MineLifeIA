[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$MinecraftDir, [string]$World = 'ia')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$gameRoot = (Resolve-Path -LiteralPath $MinecraftDir).Path
if ($World -match '[\\/]' -or $World -in @('.', '..')) { throw 'Nome de mundo invalido' }
$savePath = (Resolve-Path -LiteralPath (Join-Path $gameRoot "saves\$World")).Path
if (-not $savePath.StartsWith($gameRoot.TrimEnd('\') + '\saves\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Save fora do diretorio esperado' }
if (-not (Test-Path -LiteralPath (Join-Path $savePath 'level.dat'))) { throw 'Save Minecraft nao confirmado' }
if (Get-Process -Name java,javaw -ErrorAction SilentlyContinue) { throw 'Feche Minecraft e processos Java antes do backup/instalacao (incluindo Gradle daemon: mod\gradlew.bat --stop).' }
$jar = Join-Path $projectRoot 'mod\build\libs\minelife-ai-0.2.0.jar'
if (-not (Test-Path -LiteralPath $jar)) { throw 'Compile o mod antes de instalar' }
$mods = Join-Path $gameRoot 'mods'
if (-not (Test-Path -LiteralPath $mods)) { throw 'Pasta mods nao encontrada' }
if (-not (Get-ChildItem -LiteralPath $mods -Filter 'fabric-api-*1.21.1*.jar')) { throw 'Fabric API 1.21.1 nao encontrada' }
$backupRoot = Join-Path (Split-Path $projectRoot -Parent) ('MineLifeAI-backups\install-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $backupRoot | Out-Null
Copy-Item -LiteralPath $savePath -Destination (Join-Path $backupRoot $World) -Recurse
# Confere cada arquivo copiado antes de modificar mods/config.
$sourceFiles = Get-ChildItem -LiteralPath $savePath -File -Recurse
foreach ($file in $sourceFiles) {
    $relative = $file.FullName.Substring($savePath.Length).TrimStart('\')
    $copy = Join-Path (Join-Path $backupRoot $World) $relative
    if ((Get-FileHash -LiteralPath $file.FullName).Hash -ne (Get-FileHash -LiteralPath $copy).Hash) { throw 'Backup divergente; instalacao interrompida' }
}
Set-Location -LiteralPath $projectRoot
& .\.venv\Scripts\python.exe -c 'from agent.config import load_config; load_config()'
if ($LASTEXITCODE -ne 0) { throw 'Configuracao local indisponivel' }
$modConfig = Join-Path $gameRoot 'config\minelife-ai.json'
if (Test-Path -LiteralPath $modConfig) { Copy-Item -LiteralPath $modConfig -Destination (Join-Path $backupRoot 'minelife-ai.json') }
$existing = @(Get-ChildItem -LiteralPath $mods -Filter 'minelife-ai*.jar')
foreach ($file in $existing) {
    # Move recuperavel apenas dos JARs MineLife identificados. Nunca move saves.
    if (-not $file.FullName.StartsWith($mods.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Mod fora do diretorio esperado' }
    Move-Item -LiteralPath $file.FullName -Destination (Join-Path $backupRoot $file.Name)
}
$backendConfig = Get-Content -LiteralPath (Join-Path $projectRoot 'config\local.json') -Raw -Encoding UTF8 | ConvertFrom-Json
# O mod recebe apenas seu token; configuracoes de provedores ficam no backend.
$minimalConfig = @{ token = $backendConfig.token } | ConvertTo-Json
[System.IO.File]::WriteAllText($modConfig, $minimalConfig, (New-Object System.Text.UTF8Encoding $false))
Copy-Item -LiteralPath $jar -Destination (Join-Path $mods 'minelife-ai-0.2.0.jar')
Write-Host "Mod instalado. Backup verificado em: $backupRoot"
Write-Host 'Abra Fabric 1.21.1, carregue ia em Survival e pressione F8 apos iniciar o backend.'
