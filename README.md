# MineLife AI

Agente experimental para controlar **o personagem local** no Minecraft Java
1.21.1 com Fabric. O primeiro objetivo é observar uma árvore, testar a quebra
de um tronco e registrar apenas o que foi comprovado. Repositório oficial:
[FelixTheMAchine/MineLifeIA](https://github.com/FelixTheMAchine/MineLifeIA), tornado
público pelo proprietário durante a integração. Memória e configurações permanecem locais.

## Estado desta versão

Mod Java compilável, backend local FastAPI, memória SQLite, diário Markdown e
publicador com modo de teste. Os testes automatizados usam dados de teste
isolados; **o ciclo dentro do Minecraft ainda requer validação manual**.
Não há descobertas reais nem dias inventados incluídos no repositório.
Veja [STATUS.md](STATUS.md) para resultados e limitações.

## Preparar e executar no Windows

Requisitos: JDK 21, Python 3.11, Git, Minecraft 1.21.1 com Fabric Loader e Fabric API.
O MCA Reborn pode permanecer instalado; esta etapa não automatiza suas interfaces.

```powershell
Set-Location "$HOME\Documents\MineLifeAI"
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\mod\gradlew.bat -p mod build
.\mod\gradlew.bat -p mod --stop
```

O JAR é `mod/build/libs/minelife-ai-0.1.0.jar`. O Gradle Wrapper, incluindo seu
JAR e checksum da distribuição, está versionado. Não é necessário instalar Gradle.

Feche Minecraft e processos Java antes da instalação. Confira o diretório real
do jogo; neste computador a inspeção confirmou `%APPDATA%\.minecraft` por seus
mods, save e log. O script exige um caminho explícito, valida o save e copia o
mundo para um backup externo, conferindo hashes antes de instalar o mod.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Install-Mod.ps1 -MinecraftDir "$env:APPDATA\.minecraft" -World ia
powershell -ExecutionPolicy Bypass -File .\scripts\Start-Backend.ps1
```

Abra Minecraft pelo launcher normalmente, selecione Fabric 1.21.1 e carregue `ia`
em Survival. O mod só age no mundo local com servidor integrado.

- **F8**: autorizar e ativar / desativar completamente.
- **F9**: pausar / retomar uma autorização ainda válida.
- **F10**: emergência; exige F8 para rearmar.
- Abrir uma interface, perder foco, ficar em perigo ou perder a conexão interrompe
  o controle. A perda de conexão é detectada em até 1,5 segundo.

O HUD mostra o estado. Abra `http://127.0.0.1:8765` para acompanhar o Life Observer.
Copie o valor de `token` de `config/local.json` para o campo do painel. Não o
publique. O token fica somente em memória no navegador. O painel exige autorização
local F8 antes de permitir início/retomada. Volte o foco para Minecraft para agir.

## Primeiro teste real

1. Faça a instalação com backup pelo script acima.
2. Abra `ia` durante o dia, com vida e comida suficientes, próximo de uma árvore
   natural a até 12 blocos, em terreno caminhável. Deixe espaço livre ao redor.
3. Inicie o backend e pressione F8. Observe a aproximação, a quebra e a coleta.
4. Confira o experimento e a reflexão no painel. Uma remoção de bloco dá apenas
   conhecimento parcial; coleta exige aumento de inventário após quebra confirmada.
5. Pressione F10 para testar a devolução do controle. Reative com F8 e interrompa
   o backend para verificar a parada por desconexão. Nunca teste próximo a um precipício.
6. Reinicie o backend. O banco permanece em `data/memory.sqlite3`; a descoberta
   confirmada deve continuar no painel quando o mundo reconectar. Reative por F8.
7. Para fechar o diário diário, permaneça conectado até observar o próximo dia
   do Minecraft. Não use comandos para adiantar o tempo neste teste.

Não é garantido encontrar caminho em qualquer terreno. O navegador procura
caminhos locais, evita líquidos e perigos próximos e recusa rotas sem piso seguro.
Se não houver árvore viável, o agente aguarda. Após a primeira descoberta, ele
mantém a nova pergunta e aguarda as próximas habilidades; não implementa ainda
uma vida Survival completa.

## Memória e Life Journal

SQLite mantém `Events`, `Observations`, `Knowledge`, `Hypotheses`, `Experiments`,
`Goals`, `JournalEntries`, comandos e fila de publicação. Eventos têm UUID,
mundo, sessão, dia, horário UTC, descrição, verificação e evidência.

O identificador de mundo deriva de um hash do diretório canônico, criação da
pasta e seed. Nenhum caminho local é enviado ao GitHub. Mover/copiar o mundo para
outro diretório cria uma identidade distinta. Não restaurar um save antigo por
cima do atual sem planejar também a relação com sua memória.

Entradas ficam em:

```text
journals/<identificador-do-mundo>/day_001.md
journals/<identificador-do-mundo>/reflections/day_001_<uuid>.md
```

O número é o dia real observado no Minecraft, não um contador fictício começando
sempre em 1. Uma entrada diária é concluída quando um dia posterior é observado,
inclusive depois de reiniciar o backend. O último dia permanece aberto se o jogo
for fechado antes da virada. Reflexões são exportadas após eventos significativos.
Não se cria entrada para um dia sem eventos, nem se sobrescreve entrada concluída.

A narrativa determinística em primeira pessoa utiliza somente descrições de
eventos verificados. Personalidade e sentimentos narrados são simulações. Nenhum
modelo grande ou API paga é necessário. Integração com LLM ainda está no roadmap
e deverá preservar a validação factual.

## GitHub e publicação do diário

O projeto e os diários usam **somente o repositório oficial MineLifeIA**. Não há
criação automática de outro repositório. O `origin` esperado é exatamente:

```text
https://github.com/FelixTheMAchine/MineLifeIA.git
```

`journals/` é ignorado pelos commits normais. O publicador valida cada entrada
contra os eventos e o texto canônico no SQLite e prepara apenas dias concluídos,
com suas reflexões. A fila é ordenada por mundo/dia. Arquivos remotos idênticos
são reconhecidos; arquivos divergentes impedem publicação. Nenhuma sobrescrita,
force-push ou inclusão do banco, saves, tokens e logs é permitida.

```powershell
# Dry-run: lista arquivos/hashes; não faz commit, clone ou push.
powershell -ExecutionPolicy Bypass -File .\scripts\Publish-Journal.ps1
```

Para habilitar um envio manual posteriormente, instale GitHub CLI, autentique a
conta com acesso de escrita ao repositório e configure o Git:

```powershell
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
gh repo view FelixTheMAchine/MineLifeIA --json nameWithOwner,isPrivate
```

Depois de validar um diário real e autorizar a publicação, adicione
`"journal_publish_approved": true` ao `config/local.json`. Como o repositório agora
é público, a publicação de diários também exige `"journal_allow_public": true`;
sem essa escolha explícita o script recusa enviar narrativas para um repositório
público. Depois execute:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Publish-Journal.ps1 -Publish
```

**A publicação automática permanece desligada.** Não há agendamento nem push
no loop de controle. A fila sobrevive a falhas de autenticação ou rede. O envio
manual usa checkout isolado em `data/publish-work/`, verifica visibilidade e remote,
adiciona somente a lista permitida e faz push normal para `main`. Se houver
concorrência no remoto, interrompe e tenta novamente em uma próxima execução.

## Testes e segurança do commit

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Test.ps1
.\.venv\Scripts\python.exe scripts\audit_commit.py
git diff --cached --check
```

Os testes exercitam persistência, isolamento entre mundos, resultados sem prova,
deduplicação, fechamento de dias, exportação imutável, validação de conteúdo,
fila offline e autenticação HTTP. Eles não atestam funcionamento no Minecraft.

O `.gitignore` protege ambientes locais, caches, builds, bancos, logs, tokens,
chaves, saves e o diário ainda não aprovado. Use `audit_commit.py` para conferir
os blobs realmente preparados no index. Nenhum scanner substitui a revisão do diff.

## Referências de implementação

- [Yarn 1.21.1 — ClientPlayerInteractionManager](https://maven.fabricmc.net/docs/yarn-1.21.1+build.3/net/minecraft/client/network/ClientPlayerInteractionManager.html): mineração e interações nativas.
- [Fabric — Loom 1.8 e Gradle 8.10](https://fabricmc.net/2024/10/14/1212.html): cadeia de compilação.
- [Fabric — Java 21](https://wiki.fabricmc.net/tutorial:setup): ambiente de desenvolvimento.

Protocolo e limites estão em [docs/PROTOCOL.md](docs/PROTOCOL.md) e
[ROADMAP.md](ROADMAP.md).
