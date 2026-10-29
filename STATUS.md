# MineLife AI — status 0.2.0 — 2026-10-29

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
