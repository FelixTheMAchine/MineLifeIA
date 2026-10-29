# MineLife AI

Agente experimental de vida artificial simulada que controla o personagem local no Minecraft Java 1.21.1 com Fabric. Ele observa, propõe objetivos limitados por capacidades reais, executa ações nativas e só incorpora resultados sustentados por evidências do servidor integrado. Personalidade e narrativa representam comportamento simulado; o projeto não afirma consciência.

## Estado alcançado

A versão atual desenvolve um ciclo contínuo de observação, necessidades, memória, seleção de objetivos, ações e reflexão. Há percepção de blocos visíveis e árvores próximas, navegação BFS em terreno local seguro, observação de blocos, mineração nativa de troncos, verificação de coleta, crafting de receitas vanilla desbloqueadas que cabem na grade 2×2, exploração de fronteiras locais, banco SQLite com migração respaldada, diário determinístico e painel. F8 autoriza, F9 pausa/retoma e F10 interrompe.

O código Java compila e a comunicação HTTP/1.1 Java–FastAPI foi exercitada em loopback com fixtures. O comportamento desta versão e o crafting **ainda precisam de validação na interface real do Minecraft**. Uma sessão anterior do MVP 0.1 confirmou a descoberta de um tronco de bétula e a persistência do diário; isso não comprova o novo executor de crafting nem toda a versão 0.2. Consulte [STATUS.md](STATUS.md) para a verificação corrente.

Alimentação autônoma foi implementada para alimentos com componente Food já no hotbar: usa o comando normal de consumir e só registra o resultado quando o servidor confirma aumento de fome e consumo de exatamente uma unidade. Ainda não coleta, cozinha ou planta alimentos; sem comida segura, aguarda. Também não estão implementados combate, abrigo noturno, mineração geral com ferramentas, crafting 3×3 em bancada, construção física de projetos, agricultura, fornalhas, comércio, relações com MCA Reborn, família ou civilização. O LLM é um conselheiro opcional e não escreve fatos no diário. Exploração termina na fronteira local que o navegador consegue certificar. Capacidades novas precisam de validação no jogo antes de serem tratadas como testadas.

## Requisitos e preparação

Windows 11, JDK 21, Python 3.11, Minecraft 1.21.1 com Fabric Loader, Fabric API 1.21.1 e Git. O build usa Gradle Wrapper 8.10.2 e Fabric Loom 1.8.13. O MCA Reborn pode permanecer instalado; não há integração social funcional nesta etapa.

No PowerShell, a partir deste repositório:

```powershell
Set-Location (Join-Path $HOME 'Documents\MineLifeAI')
powershell -ExecutionPolicy Bypass -File .\scripts\Setup.ps1
```

Para instalar/atualizar o mod, feche Minecraft e os processos Java/Gradle. O instalador verifica o diretório e o mundo `ia`, copia o save para `..\MineLifeAI-backups`, compara hashes, guarda o mod/configuração anterior e somente então instala o JAR. Para a primeira execução integrada:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Start-MineLife.ps1 -Setup -InstallMod -MinecraftDir "$env:APPDATA\.minecraft"
```

Se o launcher usa outro diretório, passe seu caminho real em `-MinecraftDir`. O backend e o painel são iniciados; o script não abre nem autentica no launcher. Abra Minecraft normalmente, escolha Fabric 1.21.1, entre em `ia` em Survival e pressione **F8**. Para execuções seguintes, use `Start-MineLife.ps1`. O botão do painel não pode armar o personagem sem autorização local por F8.

O painel local fica em `http://127.0.0.1:8765`. Cole nele o token local de `config/local.json`; o navegador o mantém apenas em memória. Não compartilhe esse token. F8 desativa/reativa, F9 pausa/retoma e F10 é a parada de emergência, que exige F8 para rearmar. Interface aberta, perda de foco, perigo físico ou heartbeat ausente liberam o controle e interrompem a ação. `Stop-MineLife.ps1` solicita parada autenticada do backend.

## Cognição, evidência e memória

O motor cognitivo não encerra depois de uma descoberta confirmada. Em cada ciclo temporizado, considera perigos, perguntas, conhecimento, receitas que o mod realmente anuncia, habilidades executáveis e fronteiras carregadas. Mantém limites de metas simultâneas, retentativas, observações e frequência de planejamento. Um objetivo sem habilidade é mostrado como bloqueado; falhas recebem espera e alternativas. Apenas o mod executa input físico.

A navegação certifica piso, espaço livre, líquidos e perigos próximos a cada passo; não quebra obstáculos nem promete caminhos em regiões distantes. O controlador de crafting verifica receita desbloqueada, inventário, grade, consumo, resultado e estatística de crafting do servidor. Sua grade atual é somente a do inventário 2×2. Abrir uma interface pausa o controle.

`data/memory.sqlite3` contém memórias isoladas pela identidade hash do mundo. A atualização de esquema cria backup SQLite antes de aplicar migrações. Eventos, observações, conhecimentos, hipóteses, experimentos, metas, perguntas, interesses, motivações, habilidades, regiões, reflexões, personalidade e diário sobrevivem a reinícios. Não apague `data/` se quiser manter a memória.

O Life Journal escreve somente a partir de eventos registrados e exporta arquivos por mundo em `journals/<hash-do-mundo>/`. A coleta requer aumento de inventário verificado; crafting requer entrada consumida, saída recebida e estatística correspondente. Dias só são fechados depois que um dia posterior é observado. Arquivos locais de diário são ignorados pelo Git.

O ciclo atual pode recolher itens observados no chão após confirmar tanto o aumento do inventário quanto a redução/remoção da mesma entidade pelo servidor. Com fome baixa, pode colher cultivos vanilla maduros visíveis durante o dia. A remoção do bloco não prova que um alimento caiu: o item e seu consumo precisam de confirmações próprias. Alimentação trata corretamente a última unidade e restaura o slot temporariamente trocado ao cancelar quando o estado permite. Essas capacidades novas passaram por testes automatizados e compilação, mas ainda aguardam validação dentro do Minecraft.

## Modelo de linguagem opcional

O backend funciona sem provedor. Por padrão, `config/local.json` não contém configuração LLM e o modo é `none`. Um adaptador opcional aceita Ollama local ou uma API compatível com chat completions. Configure cópia local de `config/example.json`; guarde chaves de API apenas em variável de ambiente, nunca no JSON versionado. Não confunda uma assinatura ChatGPT com crédito da API. O adaptador aplica timeout, cache, limite de chamadas e tamanho de resposta. Suas sugestões podem ordenar uma meta já existente, mas não emitem comandos físicos, não confirmam fatos e não são incorporadas ao diário.

O hardware local não foi usado para selecionar ou baixar modelo; não há modelo Ollama configurado. Não se presume inferência em GPU nem se recomenda instalar um modelo grande sem medir memória e impacto no Minecraft.

## Protocolo local

O mod negocia versão em `GET /bridge/handshake`, então envia observações e resultados em `POST /bridge/step`, usando HTTP/1.1 para `127.0.0.1:8765`. A bridge usa token bearer local, sessão, mundo, dimensão, sequência, ID de comando, confirmação, heartbeat, prazos, deduplicação e nova autorização após reconexão. É loopback; Uvicorn usa h11, sem WebSocket. A resposta de `/health` sozinha não demonstra comunicação: o teste Java de contrato envia handshake e observação e recebe um comando de uma instância FastAPI temporária.

Detalhes: [docs/PROTOCOL.md](docs/PROTOCOL.md). A ponte não é protegida contra outro processo local que já conheça o token. Não abra a porta na rede.

## Testes e build

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Test.ps1
```

O script compila/valida o mod (`gradlew build`, incluindo 14 verificações do `ControlGate`) e então executa a suíte Python. Os testes usam mundo e SQLite temporários; transporte em loopback e fixture Java não iniciam Minecraft nem comprovam física real. Execute `python scripts/verify_memory_upgrade.py` para comparar hashes de tabelas reais antes/depois da migração. `python scripts/audit_commit.py` audita blobs staged e recusa dados privados.

O JAR de distribuição é `mod/build/libs/minelife-ai-0.2.0.jar` (gerado, ignorado pelo Git). O wrapper necessário para compilar permanece versionado.

## GitHub e dados privados

O único repositório de código é [FelixTheMAchine/MineLifeIA](https://github.com/FelixTheMAchine/MineLifeIA). Tokens, `config/local.json`, `data/`, bancos, logs, backups, saves, ambientes virtuais, builds e diários locais são ignorados e também auditados antes do commit. Revise `git diff` e `git status` antes de publicar.

A publicação de diário está desativada. O publicador aceita apenas dias concluídos, valida evento/evidência, ordem, destino fixo e conteúdo, mantém fila offline e recusa substituir arquivos. O repositório é público: um envio público de diário requer configuração local e autorização explícitas posteriores. Não execute `Publish-Journal.ps1 -Publish` neste estágio.

## Roadmap

Veja [ROADMAP.md](ROADMAP.md). Sobrevivência noturna e alimentação; crafting 3×3 e outras interfaces; construção física; agricultura/redstone/economia; MCA, relações, família e comunidade são etapas futuras. A memória autobiográfica e as reflexões contextuais atualmente cobrem somente acontecimentos relevantes para as capacidades implementadas. Componentes do painel ou metas bloqueadas não contam como capacidade implementada.
