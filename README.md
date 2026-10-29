# MineLife AI

Agente experimental de vida artificial simulada que controla o personagem local no Minecraft Java 1.21.1 com Fabric. Ele observa, propõe objetivos limitados por capacidades reais, executa ações nativas e só incorpora resultados sustentados por evidências do servidor integrado. Personalidade e narrativa representam comportamento simulado; o projeto não afirma consciência.

## Estado alcançado

A versão atual desenvolve um ciclo contínuo de observação, necessidades, memória, seleção de objetivos, ações e reflexão. Há percepção local, navegação BFS, mineração nativa de troncos, coleta de itens, colheita de cultivos maduros, alimentação, repouso em cama existente, crafting 2×2 e 3×3 e colocação de estação de trabalho. SQLite, diário e painel preservam a separação entre tentativas e resultados comprovados. F8 autoriza, F9 pausa/retoma e F10 interrompe.

O código Java compila e a comunicação HTTP/1.1 Java–FastAPI foi exercitada em loopback com fixtures. O comportamento desta versão e o crafting **ainda precisam de validação na interface real do Minecraft**. Uma sessão anterior do MVP 0.1 confirmou a descoberta de um tronco de bétula e a persistência do diário; isso não comprova o novo executor de crafting nem toda a versão 0.2. Consulte [STATUS.md](STATUS.md) para a verificação corrente.

O planejador pode encadear reposição limitada de madeira, fabricação de tábuas e bancada, colocação física da bancada, gravetos e ferramentas. Receitas 3×3 incluem pão quando há trigo suficiente. A escolha usa receitas desbloqueadas e ingredientes anunciados pelo jogo; não cria itens. A fabricação é interrompível e só vira conhecimento após consumo dos ingredientes, recebimento da saída e estatística CRAFTED confirmados pelo servidor. Uma receita já aprendida pode ser repetida para atender estoque limitado, sem encerrar a cognição.

Alimentos permitidos podem vir dos 36 slots principais, de itens observados no chão e de cultivos maduros. A remoção de um cultivo não comprova coleta: os drops e a refeição exigem confirmações separadas. À noite, a capacidade atual usa cama existente; sem alternativa segura, aguarda com motivo explícito. Ainda faltam caça, cozinhar na fornalha, plantio/replantio, combate/fuga, mineração geral com seleção de ferramentas, construção de abrigos, comércio e relações MCA. Fabricar uma ferramenta, fornalha ou baú não significa que seu uso esteja implementado. O LLM é opcional e não escreve fatos no diário.

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

O painel local fica em `http://127.0.0.1:8765`. Cole nele o token local de `config/local.json`; o navegador o mantém apenas em memória. Não compartilhe esse token. F8 desativa/reativa, F9 pausa/retoma e F10 é a parada de emergência, que exige F8 para rearmar. Interface externa à ação, perda de foco, perigo físico ou heartbeat ausente liberam o controle e interrompem a ação. A bancada aberta pelo controlador e a tela de sono da ação são exceções controladas; F8/F9/F10 continuam sendo lidas nessas telas. `Stop-MineLife.ps1` solicita parada autenticada do backend.

Ao atualizar esta revisão, reinicie o backend antigo: `/health` e o handshake devem anunciar `workstations-v1`. O script recusa reutilizar processo antigo, mesmo que ambos mostrem versão 0.2.0. Atualize o mod pelo instalador apenas com Minecraft fechado e backup; compilar não instala automaticamente o JAR.

## Cognição, evidência e memória

O motor cognitivo não encerra depois de uma descoberta confirmada. Em cada ciclo temporizado, considera perigos, perguntas, conhecimento, receitas que o mod realmente anuncia, habilidades executáveis e fronteiras carregadas. Mantém limites de metas simultâneas, retentativas, observações e frequência de planejamento. Um objetivo sem habilidade é mostrado como bloqueado; falhas recebem espera e alternativas. Apenas o mod executa input físico.

A navegação verifica piso, espaço livre, líquidos e perigos próximos a cada passo; não quebra obstáculos nem promete caminhos em regiões distantes. O crafting usa o livro de receitas nativo, uma produção por comando, e valida a alocação de todos os ingredientes. A bancada precisa ser observada ou revisitada a partir de uma colocação anteriormente comprovada. O controlador aproxima-se, abre sua interface, fabrica e fecha a tela. Uma bancada lembrada distante não bloqueia permanentemente outra estação necessária.

A colocação atual aceita bancada e fornalha, mas o planejador seleciona apenas a bancada. Exige célula vazia observada, apoio sólido sem interface, alcance, raycast e espaço sem entidades. Usa um item existente e `interactBlock`; prova requer bloco correto, redução de uma unidade e incremento de USED. Quando o item está fora do hotbar, precisa de um slot vazio no hotbar para a troca reversível. Crafting exige um slot principal vazio e cursor/grade livres. Falhas e falta de espaço geram cooldown; não descartam itens para prosseguir.

`data/memory.sqlite3` contém memórias isoladas pela identidade hash do mundo. A atualização de esquema cria backup SQLite antes de aplicar migrações. Eventos, observações, conhecimentos, hipóteses, experimentos, metas, perguntas, interesses, motivações, habilidades, regiões, reflexões, personalidade e diário sobrevivem a reinícios. Não apague `data/` se quiser manter a memória.

O Life Journal escreve somente a partir de eventos registrados e exporta arquivos por mundo em `journals/<hash-do-mundo>/`. A coleta requer aumento de inventário verificado; crafting requer entrada consumida, saída recebida e estatística correspondente. Dias só são fechados depois que um dia posterior é observado. Arquivos locais de diário são ignorados pelo Git.

O ciclo atual pode recolher itens observados no chão após confirmar tanto o aumento do inventário quanto a redução/remoção da mesma entidade pelo servidor. Com fome baixa, pode colher cultivos vanilla maduros visíveis durante o dia. A remoção do bloco não prova que um alimento caiu: o item e seu consumo precisam de confirmações próprias. Alimentação trata corretamente a última unidade e restaura o slot temporariamente trocado ao cancelar quando o estado permite. Essas capacidades novas passaram por testes automatizados e compilação, mas ainda aguardam validação dentro do Minecraft.

Durante a noite, se encontrar uma cama vanilla carregada, visível, no Overworld e alcançável sem ameaça próxima, o agente pode tentar repousar pela interação normal. O evento só é confirmado com estatística `SLEEP_IN_BED` e transição de horário verificadas no servidor. Sem cama ou rota segura, aguarda; ainda não constrói abrigo. Esta etapa também aguarda validação em gameplay.

## Modelo de linguagem opcional

O backend funciona sem provedor. Por padrão, `config/local.json` não contém configuração LLM e o modo é `none`. Um adaptador opcional aceita Ollama local ou uma API compatível com chat completions. Configure cópia local de `config/example.json`; guarde chaves de API apenas em variável de ambiente, nunca no JSON versionado. Não confunda uma assinatura ChatGPT com crédito da API. O adaptador aplica timeout, cache, limite de chamadas e tamanho de resposta. Suas sugestões podem ordenar uma meta já existente, mas não emitem comandos físicos, não confirmam fatos e não são incorporadas ao diário.

O hardware local não foi usado para selecionar ou baixar modelo; não há modelo Ollama configurado. Não se presume inferência em GPU nem se recomenda instalar um modelo grande sem medir memória e impacto no Minecraft.

## Protocolo local

O mod negocia protocolo e a extensão `workstations-v1` em `GET /bridge/handshake`, então envia observações e resultados em `POST /bridge/step`, usando HTTP/1.1 para `127.0.0.1:8765`. A bridge usa token bearer local, sessão, mundo, dimensão, sequência, ID de comando, confirmação, heartbeat, prazos, deduplicação e nova autorização após reconexão. É loopback; Uvicorn usa h11, sem WebSocket. A resposta de `/health` sozinha não demonstra comunicação: o teste Java de contrato envia uma observação com receita 3×3 e recebe um comando `craft_table` de uma instância FastAPI temporária.

Detalhes: [docs/PROTOCOL.md](docs/PROTOCOL.md). A ponte não é protegida contra outro processo local que já conheça o token. Não abra a porta na rede.

## Testes e build

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Test.ps1
```

O script compila/valida o mod (`gradlew build`, incluindo verificações de ControlGate, alimentação e repouso) e então executa a suíte Python. O resultado corrente está em [STATUS.md](STATUS.md). Os testes usam mundo e SQLite temporários; transporte em loopback e fixture Java não iniciam Minecraft nem comprovam física real. `python scripts/verify_memory_upgrade.py` compara hashes de tabelas reais antes/depois de uma migração, quando necessária; esta revisão não muda o esquema. `python scripts/audit_commit.py` audita blobs staged e recusa dados privados.

O JAR de distribuição é `mod/build/libs/minelife-ai-0.2.0.jar` (gerado, ignorado pelo Git). O wrapper necessário para compilar permanece versionado.

## GitHub e dados privados

O único repositório de código é [FelixTheMAchine/MineLifeIA](https://github.com/FelixTheMAchine/MineLifeIA). Tokens, `config/local.json`, `data/`, bancos, logs, backups, saves, ambientes virtuais, builds e diários locais são ignorados e também auditados antes do commit. Revise `git diff` e `git status` antes de publicar.

A publicação de diário está desativada. O publicador aceita apenas dias concluídos, valida evento/evidência, ordem, destino fixo e conteúdo, mantém fila offline e recusa substituir arquivos. O repositório é público: um envio público de diário requer configuração local e autorização explícitas posteriores. Não execute `Publish-Journal.ps1 -Publish` neste estágio.

## Roadmap

Veja [ROADMAP.md](ROADMAP.md). Abrigo físico, cozinha, uso das ferramentas, rotas maiores, agricultura/redstone/economia e vida social MCA permanecem próximos desenvolvimentos. A memória autobiográfica e as reflexões contextuais cobrem acontecimentos relevantes às capacidades implementadas. Colocar uma estação não é construir uma casa; metas bloqueadas não contam como capacidade executável.
