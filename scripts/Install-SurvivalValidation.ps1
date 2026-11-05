[CmdletBinding()]
param([string]$MinecraftDir = '', [ValidateSet('phase04-validation')][string]$World = 'phase04-validation')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
if (-not $MinecraftDir) { $MinecraftDir = Join-Path $projectRoot 'data\validation\phase04' }
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$prepare = Join-Path $PSScriptRoot 'prepare_survival_validation.py'
function Assert-JavaClosed {
    if (Get-Process -Name java,javaw -ErrorAction SilentlyContinue) {
        throw 'Feche Minecraft e Java, incluindo o daemon Gradle, antes de instalar.'
    }
}
function Get-ValidatedPlan {
    $output = & $python $prepare --instance $MinecraftDir --validate-install
    if ($LASTEXITCODE -ne 0) { throw 'Preflight offline recusou a instalacao; nenhum arquivo sera instalado.' }
    return ($output -join "`n" | ConvertFrom-Json)
}
Assert-JavaClosed
$plan = Get-ValidatedPlan
# Install-Mod verifies the save and every replaceable file before any dependency is copied.
$backup = & (Join-Path $PSScriptRoot 'Install-Mod.ps1') -MinecraftDir $plan.installation.instance -World $World -BackupOnly
if (-not $backup -or -not (Test-Path -LiteralPath (Join-Path $backup 'replacement-manifest.json'))) { throw 'Backup verificado indisponivel' }
# Revalidate pins, paths and existing jars after backup; do not trust an old preparation report.
Assert-JavaClosed
$plan = Get-ValidatedPlan
$mods = Join-Path $plan.installation.instance 'mods'
$manifest = @(Get-Content -LiteralPath (Join-Path $backup 'replacement-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json)
$current = @(Get-ChildItem -LiteralPath $mods -File -Filter '*.jar')
$config = Join-Path $plan.installation.instance 'config\minelife-ai.json'
if (Test-Path -LiteralPath $config) { $current += Get-Item -LiteralPath $config }
if ($current.Count -ne $manifest.Count) { throw 'Arquivos substituiveis mudaram apos backup' }
foreach ($file in $current) {
    $relative = $file.FullName.Substring($plan.installation.instance.Length).TrimStart('\')
    $saved = @($manifest | Where-Object { $_.relative_path -eq $relative })
    if ($saved.Count -ne 1 -or (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA512).Hash -ne $saved[0].sha512) { throw 'Arquivo mudou apos backup' }
    $copy = Join-Path (Join-Path $backup 'files') $relative
    if ((Get-FileHash -LiteralPath $copy -Algorithm SHA512).Hash -ne $saved[0].sha512) { throw 'Backup de arquivo substituivel divergente' }
}
foreach ($pin in $plan.runtime) {
    Assert-JavaClosed
    $source = Join-Path $plan.cache $pin.filename
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA512).Hash.ToLowerInvariant() -ne $pin.sha512) { throw 'Cache mudou apos validacao' }
    Copy-Item -LiteralPath $source -Destination (Join-Path $mods $pin.filename)
    if ((Get-FileHash -LiteralPath (Join-Path $mods $pin.filename) -Algorithm SHA512).Hash.ToLowerInvariant() -ne $pin.sha512) { throw 'Copia de dependencia divergente; consultar backup' }
}
Assert-JavaClosed
if ((Get-FileHash -LiteralPath $plan.installation.jar -Algorithm SHA512).Hash.ToLowerInvariant() -ne $plan.installation.jar_sha512) { throw 'Build MineLife mudou apos validacao' }
& (Join-Path $PSScriptRoot 'Install-Mod.ps1') -MinecraftDir $plan.installation.instance -World $World
Write-Host "Dependencias oficiais instaladas somente na instancia isolada. Backup anterior a qualquer copia: $backup"
Write-Host 'Instalacao nao constitui teste real; gameplay e coleta permanecem sem validacao.'
