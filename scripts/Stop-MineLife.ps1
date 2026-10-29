$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
$config = Get-Content -LiteralPath 'config\local.json' -Raw | ConvertFrom-Json
try { Invoke-RestMethod -Method Post 'http://127.0.0.1:8765/api/control/stop' -Headers @{Authorization=('Bearer '+$config.token)} | Out-Null } catch { }
Start-Sleep -Milliseconds 500
if (Test-Path -LiteralPath 'data\backend.pid') {
    $backendId = [int](Get-Content -LiteralPath 'data\backend.pid')
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $backendId"
    $expectedPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if ($process -and $process.ExecutablePath -eq $expectedPython -and $process.CommandLine -match '-m agent\.main') {
        Stop-Process -Id $backendId
    }
}
Write-Host 'Parada solicitada. F10 no jogo interrompe imediatamente; desconexao libera o controle em ate 3 segundos.'
