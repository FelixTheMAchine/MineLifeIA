# Piloto manual da fase 0.7 (15 a 20 minutos)

O teste automatizado é sintético. Este piloto exige observação humana e não deve ser descrito como concluído antes de evidências do jogo. Use um mundo descartável em Survival, com um jogador, sem comandos, Creative ou teleporte. No estado local verificado antes deste guia, `minelife-validation` ainda não existia; o JAR instalado era 0.2.0, mas seu hash diferia do build atual. O backend não respondeu em `/health`, e havia processo Java ativo.

1. Crie `minelife-validation` pela interface do Minecraft, sem armar F8. Feche o jogo. No PowerShell, a partir da raiz do repositório, pare o backend e o daemon Gradle, se estiverem ativos:

   ```powershell
   .\scripts\Stop-MineLife.ps1
   .\mod\gradlew.bat --stop
   ```

2. Faça backup consistente da memória real e instale o build somente depois de fechar todos os processos Java. O instalador verifica o save, cria backup com hashes e preserva o JAR e a configuração substituídos. Interrompa se qualquer verificação falhar:

   ```powershell
   .\.venv\Scripts\python.exe .\scripts\backup_memory.py
   .\scripts\Install-Mod.ps1 -MinecraftDir (Join-Path $env:APPDATA '.minecraft') -World 'minelife-validation'
   ```

3. Confirme que os hashes dos JARs coincidem. Inicie o backend com a configuração local existente e confirme versão e protocolo, sem imprimir o token:

   ```powershell
   $game = Join-Path $env:APPDATA '.minecraft'
   (Get-FileHash .\mod\build\libs\minelife-ai-0.2.0.jar).Hash -eq (Get-FileHash (Join-Path $game 'mods\minelife-ai-0.2.0.jar')).Hash
   .\scripts\Start-MineLife.ps1 -NoBrowser
   Invoke-RestMethod 'http://127.0.0.1:8765/health' | Select-Object version,protocol,features
   ```

   O hash deve ser `True`, e o backend deve informar versão `0.2.0`, protocolo `1` e as extensões negociadas. Abra o painel local, entre no mundo descartável em Fabric 1.21.1 e Survival, e pressione F8. F9 pausa; F10 interrompe imediatamente. Não abra o mundo se alguma conferência falhar.

4. Observe por 15 a 20 minutos: evento de quebra, entidade de drop, tentativa de pickup, UUID e aumento de inventário; seleção de objetivos, intenção Qwen aceita ou rejeitada, diferença de escolha, comando e resultado correlacionado; falhas, retomada, memória e preferência atualizadas. Registre `não observado` quando não surgir uma oportunidade válida para o Qwen. Bloco removido sem aumento de inventário não comprova coleta. Use o painel e IDs de mundo, sessão, objetivo, comando, evento e plano para correlacionar cada afirmação.

5. Termine com F10, feche Minecraft e execute `.\scripts\Stop-MineLife.ps1`. Preserve o backup e os logs localmente; não publique diários, memória, token ou save.
