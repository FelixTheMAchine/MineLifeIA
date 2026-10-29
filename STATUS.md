# MineLife AI — status 0.2.0 — 2026-10-29

## Continuação — comida observada e colheita local

- Corrigido o resultado da alimentação da última unidade: sucesso usa diferença total de inventário no snapshot do servidor e aumento de fome, não exige que o slot continue ocupado. Falha, falta de nutrição, troca de slot, evidência indisponível e timeout de restauração têm motivos distintos. Cancelamento/erro passam pelo `finish`/`stop`, que libera uso e tenta reverter o swap temporário.
- A percepção de itens no chão e o controlador `pickup` já existentes agora alimentam comida somente quando o item tem componente Food e consta da lista segura vanilla. Confirmar pickup exige aumento de inventário mais redução ou remoção, no servidor, da mesma entidade UUID observada.
- Nova capability `harvest`: sensor Java identifica trigo, cenoura, batata e beterraba vanilla maduros próximos. O agente pode colhê-los quando está com fome, sem comida em inventário/chão e durante o dia. A ação usa quebra nativa; sucesso exige maturidade observada no estado do servidor antes da ação, bloco original removido e estatística MINED incrementada. Isso comprova apenas remoção, nunca os drops. Drops são recolhidos depois via `pickup`; alimento só é confirmado com mudança de fome.
- A remoção verificada de cultivo e refeições podem gerar perguntas filosóficas contextuais sobre necessidades e escolhas; a interpretação diz expressamente quando os drops ainda não foram verificados.
- Verificações desta continuação: 53 testes Python e build Gradle Fabric passaram (18 assertions Java de ControlGate/FoodEvidence). Cobrem consumo, pickup, harvest e proveniência, mas não simulam Minecraft. A versão ainda não foi executada no jogo.
- Limites mantidos: caça de animais, cozimento/fornalha, cama, abrigo físico, ferramentas e crafting 3×3 continuam sem executores reais. Não foi instalado novo JAR nem aberto/alterado o save nesta continuação.

## Continuação posterior — alimentação de emergência

- O protocolo agora anuncia alimentos disponíveis nos nove espaços do hotbar com item, slot, quantidade e nutrição obtidos do componente Food real do stack.
- Quando fome alcança o limite prudente, o backend prioriza um item permitido e envia a ação `eat`. O mod seleciona temporariamente esse slot e mantém a tecla de uso normal; não cria nem move itens.
- A ação só gera conhecimento/evento após snapshots do servidor integrado confirmarem aumento do nível de fome e consumo de exatamente uma unidade. Alimentos com efeitos negativos conhecidos e chorus fruit são recusados.
- Sem alimento permitido, o agente permanece em `WAITING_FOR_SAFE_ACTION` com motivo explícito. Coleta/cozimento/plantio de comida e sobrevivência prolongada continuam ausentes.
- Testes automatizados cobrem seleção, prioridade, alimento recusado, falta de comida e rejeição de evidência incompleta. O build Fabric confirma APIs de 1.21.1. Isso não demonstra consumo em jogo; nenhuma sessão Minecraft foi executada nesta continuação.
- Após o processo Java encerrar naturalmente, `scripts/Install-Mod.ps1` concluiu a instalação e criou backup verificado do mundo antes de substituir o mod. Nenhum processo foi terminado manualmente. A instalação foi em disco; não houve abertura do mundo ou validação de gameplay.
- Validação final: `scripts/Test.ps1` passou com build Fabric e 45 testes Python; JAR construído e instalado conferem por SHA-256. O sistema continua sem teste de gameplay nesta execução.

## Ponto de partida e preservação

Workspace do projeto e remote oficial confirmados; branch `main` é a única branch de publicação. Existe o checkpoint `safety/pre-0.2-20261028` no commit anterior ao trabalho 0.2. O histórico remoto não foi reescrito. Alterações locais e a memória anterior foram mantidas.

Antes desta extensão, a versão 0.1 havia sido observada pelo usuário no Minecraft: um tronco de bétula foi removido, 1 item foi coletado e o diário sobreviveu ao reinício. A base SQLite preservava 3 eventos, 1 conhecimento confirmado, 1 hipótese, 1 experimento, 1 objetivo e 2 entradas de diário.

## Implementado nesta continuidade

- Motor contínuo: descoberta concluída não interrompe planejamento; escolhe alvos novos, receitas desbloqueadas e fronteiras anunciadas. Planejamento fica limitado por intervalo, número de metas, retentativas e cooldowns. Pausa, emergência, desconexão, perigo e ausência de ação segura permanecem estados distintos.
- Exploração: memória em regiões locais, candidatos de fronteira anunciados pelo mod, BFS sobre chão sólido e revalidação durante o movimento. Não há viagens longas, cavernas ou promessa de caminho seguro geral.
- Crafting real 2×2: inventário é inspecionado, somente receitas vanilla desbloqueadas compatíveis e anunciadas são consideradas; o executor usa recipe book/telas nativas. A confirmação requer receita, consumo, aumento de item e estatística CRAFTED lidos do servidor. Crafting 3×3 e usar bancada não estão implementados.
- Personalidade e motivações persistentes: preset ampliado, mudanças pequenas vinculadas a eventos, interesses de engenharia/agricultura/arquitetura/mineração/exploração usados em prioridades. Prudência altera a margem de pausa e a personalidade influencia escolhas viáveis. Sociabilidade não produz ações sem integração MCA.
- Memória autobiográfica: migração SQLite v3 aditiva, tabela de eventos salientes e recuperação lexical por mundo. Reflexões contextuais de conhecimento, criação, lugares e falhas guardam perguntas, versões anteriores e IDs de evidência.
- Diário: entradas novas usam proveniência versionada, fatos dos eventos, interpretação filosófica explicitamente provisória e associação a lembrança anterior. Validação reproduz o texto a partir de fontes; entradas antigas permanecem imutáveis. Publicador valida esse formato e não aceita texto alterado sem prova.
- LLM opcional: tarefas estruturadas de cognição, filosofia, autobiografia, metas e interpretação social. Contexto inclui experiências, lembranças e reflexões. Saídas são propostas não verificadas em SQLite/Observer; somente preferência por uma meta já existente pode ordenar o planejamento. LLM continua desligado por padrão e não redige o diário público.
- Life Observer separa observação, interpretação, pergunta, hipótese, decisão, reflexão, lembrança e sugestão não verificada.
- Instalador configura o mod com apenas seu token local. Cópia do save e hashes de backup precedem qualquer substituição.

## Validação executada

- Remote oficial confirmado, público e com acesso de escrita. Antes da atualização `main` estava em `8afd0de268d9bf7a5cdf8a2e5b7d5c7ee03cdf55`.
- `python -m unittest discover -s tests -v`: 41 testes passaram em SQLite temporário, incluindo continuação após descoberta, crafting com prova, autonomia sem repetição, limites/cooldown, reconexão, isolamento, personalidade, memória filosófica, proveniência do diário, rascunhos LLM não verificados e transporte Java HTTP/1.1 contra FastAPI loopback. Não é teste dentro do jogo.
- `mod/gradlew.bat build`: sucesso. O teste `ControlGate` executou 14 verificações de tecla/epoch; o build confirma compatibilidade das chamadas de API usadas pelo código, não gameplay.
- `pip check`: dependências consistentes. Parser PowerShell: scripts sem erros sintáticos.
- JAR 0.2 instalado pelo `Install-Mod.ps1` depois de cópia e comparação SHA-256 do mundo `ia`; hash do JAR instalado corresponde ao build. O Minecraft permaneceu fechado durante a atualização.
- Migração do banco local v2→v3 com backup SQLite verificado; `integrity_check=ok`, fingerprints das tabelas históricas idênticos. Permaneceram exatamente 3 Events, 1 Knowledge, 1 Hypothesis, 2 JournalEntries, 1 Experiment e 1 Goal.
- O contrato Java–Python verificou handshake + observação + comando via HTTP/1.1, sem Upgrade. Ainda não observou o mod em cliente Minecraft na versão 0.2.
- Backend iniciado pelo script e consultado com o token local: handshake autenticado, protocolo 1/HTTP/1.1 e estado `PAUSED`; nenhuma sessão Minecraft foi alegada. Serviço foi encerrado depois da verificação.

## Estado que exige jogo real

- A versão 0.2 ainda não teve movimento, exploração, crafting ou parada de emergência observados no Minecraft. O sucesso real anterior foi na 0.1 e não valida mudanças recentes.
- A tela 2×2/recipe book e a resposta do integrado não foram acionadas em jogo. Compatibilidade em runtime com MCA Reborn permanece desconhecida.
- Não existem combate, fuga, alimentação, cama/abrigo, sobrevivência noturna funcional, mineração geral com ferramentas, interfaces 3×3/fornalha/baús, construção física, agricultura, redstone, economia, ações sociais MCA, casamento, família ou vila.
- Filosofia cobre atualmente conhecimento, criação, lugares alcançados e falhas repetidas; não implementa todas as categorias solicitadas. Memória associativa é lexical e local, ainda não uma narrativa de longo prazo ilimitada.
- O LLM não foi conectado, nenhum modelo foi escolhido/baixado e não houve chamada de API. Propostas de diário ficam separadas da narrativa factual para não publicar afirmações que não possam ser verificadas.
- Navegação fica restrita a fronteiras próximas com piso carregado. À noite ou sem caminho viável, o agente pode aguardar; não possui abrigo/fuga para continuar em segurança.

## Dados privados e publicação

O banco migrado e seus backups, saves, token, configurações, logs e diários ficam locais e são ignorados pelo Git. Publicação automática e de diários continua desligada. Nenhum diário ou memória real acompanha a sincronização de código.

## Próximo trabalho

Validar 0.2 no cliente: movimento/árvore, segundo objetivo, crafting 2×2 e F10/desconexão. Em seguida implementar necessidades básicas seguras (comida, abrigo noturno e recuperação) antes de ampliar crafting, construção, agricultura ou MCA. Atualizar este arquivo somente com evidência observada.
