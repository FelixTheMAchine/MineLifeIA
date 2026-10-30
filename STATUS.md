# MineLife AI — status 0.2.0 — 2026-10-30

## Estado corrente — primeiro refúgio por blueprint

Continuação sobre `9e5770a`, com checkpoint local `safety/pre-shelter-20261029`. Implementação integrada ao executor e ao planejador existentes; o save não foi editado.

- Blueprint compartilhado `refuge_v1`: footprint 3×3, interior 1×1 de dois blocos de altura, 16 tábuas, porta e 17 etapas. Sensor oferece terreno próximo livre/carregado; cálculo de materiais influencia coleta e crafting, incluindo receitas vanilla de portas. A reserva considera o que ainda falta, e a bancada é posicionada fora da obra/passagem.
- `ConstructionPlanner` persiste projeto, etapas, evidências e revisões. `ShelterController` e a extensão de `BlockPlacementController` executam navegação, colocação física, salto nativo para alcançar o apoio do teto, interação com a porta, entrada e saída. O Java restringe os comandos à geometria e materiais do recurso empacotado.
- Cada componente exige prova de bloco, consumo e USED. A conclusão exige uma inspeção final separada de paredes, teto, piso, interior e porta. Após reinício, presença de bloco é distinguida de colocação atribuível ao agente. Blocos inesperados são preservados; células vazias podem gerar uma etapa de reparo, sujeita a apoio e alcance.
- `NightSurvivalManager` pode direcionar o personagem a um refúgio próximo inspecionado, confirmar entrada/porta fechada e reavaliar a estrutura a cada 15 s durante a espera. Ao amanhecer, pode sair e escolher outra atividade. Uma obra parcial pode ser deixada pela passagem existente se recursos/condições faltarem, sem ser registrada como abrigo pronto.
- O navegador considera a colisão da folha de portas abertas, tanto na busca de caminho quanto na revalidação. F8/F9/F10, desconexão, perigo e cancelamento continuam ativos. A negociação exige `shelters-v1`; backend preserva compatibilidade com observações antigas, sem enviar construção a mod que não anuncia seus executores.
- SQLite v4 adiciona somente `ConstructionProjects`/`ConstructionSteps`. Banco existente recebe backup antes da migração; versão mais nova é recusada, sem downgrade. `--dry-run` permite migrar uma cópia e comparar fingerprints de todas as tabelas anteriores.
- Life Observer mostra projeto e etapas reais. Diário/filosofia distinguem conclusão inspecionada, entrada, saída e obra parcial; auditoria de blocos permanece persistida sem gerar reflexão a cada colocação. Entrar não é declarado como sobreviver a uma noite inteira. Nenhum diário real foi gerado a partir dos testes.

### Verificação desta execução

- `scripts/Test.ps1`: **92 testes Python passaram**; **build Fabric passou**. Inclui 136 assertions anteriores de controle/alimentação/sono e 389 verificações estáticas da geometria do blueprint e de painéis de porta; esses números não representam sessões ou cenários de gameplay.
- Contrato Java HTTP/1.1 → FastAPI recebeu `inspect_shelter` a partir de observação sintética de terreno e confirmou a extensão negociada. Contratos anteriores de crafting/transporte continuam passando.
- Testes de projeto cobrem material→porta→construção, 17 etapas→inspeção final→saída→novo objetivo, fome/pausa/perigo, retomada sem replay, prova ausente, projeto/alvo errado, mundo isolado, porta aberta, teto ausente, bloco inesperado, reparo por revisão e saída de obra parcial.
- Migração v3→v4 e idempotência passaram em fixtures com backup. A cópia temporária da **memória real** preservou fingerprints das **28 tabelas anteriores**, com integridade verificada. A origem manteve os mesmos fingerprints e **não foi migrada nesta execução**.
- A tentativa adicional de bootstrap de registries vanilla em JVM simples falhou por acesso que depende das transformações do Fabric Loader. Esse teste não é apresentado como validado; os testes geométricos são estáticos e estão rotulados. Detalhes em `docs/CONSTRUCTION.md`.
- JAR gerado em `mod/build/libs/minelife-ai-0.2.0.jar`, **não instalado**. Minecraft não foi aberto, não houve gameplay e não foi solicitado teste manual. Mundo, memória de origem e diários privados preservados; publicação de diário permanece desligada.

### Limites e próxima continuidade

O refúgio é mínimo e local. Não nivela terreno, não contém cama ou iluminação, não constrói casas maiores e não garante defesa contra todos os perigos. Retorno distante, caça, cozinha/fornalha, uso automático de ferramentas, armazenamento e combate permanecem pendentes. Reparo só atua em célula vazia com apoio/face alcançáveis. A implementação física ainda depende de validação no cliente Fabric/MCA real.

Próximas dependências viáveis: alimentação preparada em fornalha com combustível/retomada; seleção de ferramentas e mineração com drops corretos; depois ampliar o abrigo e rotas de retorno. A construção não encerra a autonomia. Consulte `docs/CONSTRUCTION.md` para critérios, evidências e limitações.

## Etapa anterior — cadeia de recursos, bancada e fabricação (histórico)

Continuação sobre `4b8b304`, preservando os avanços posteriores à base `5ec88a6`. Checkpoint local `safety/pre-workstations-20261029` criado antes da edição. O projeto não foi reiniciado.

- `agent/crafting.py` integra necessidades de estoque ao ciclo existente: reposição limitada de troncos conhecidos, tábuas, bancada, gravetos, ferramentas e pão a partir de trigo observado. Receitas precisam ser desbloqueadas/anunciadas pelo mod; após sucesso, o planejador escolhe outra oportunidade. Receita conhecida só é repetida enquanto há demanda, mantendo cooldown e orçamento de falhas.
- Novo `BlockPlacementController` coloca bancada/fornalha por `interactBlock`, com item existente, apoio sólido, célula livre e alcance real. O planejador escolhe bancada; a colocação de fornalha não tem ainda objetivo operacional. HotbarLease usa SWAP nativo em slot vazio e restaura somente estado compatível. Resultado exige bloco no servidor, item consumido e USED +1.
- `CraftingController` ampliado: aproximação da bancada, abertura da tela nativa, RecipeMatcher com todos os ingredientes, recipe book, recolhimento de uma produção e fechamento seguro. Receitas 3×3 incluem ferramentas de madeira/pedra, pão, fornalha e baú. Resultado exige consumo exato dos ingredientes, saída e CRAFTED; interface da bancada também é conferida no servidor. Ferramentas fabricadas ainda não são selecionadas automaticamente para mineração geral.
- Memória de estação usa mundo/dimensão e coordenadas. Uma colocação próxima pode motivar revisita para revalidar presença e rota; uma lembrança distante não impede preparar outra bancada necessária. Não há navegação de longa distância à base.
- Alimentação tem prioridade mesmo com limite de uma meta ativa. Tentativas malsucedidas da mesma refeição agora preservam cooldown/orçamento, em vez de gerar novas metas infinitas. Trigo observado pode ser recolhido antes de haver três unidades; pão fabricado e refeição consumida produzem experiências distintas.
- Corrigidas leituras assíncronas de sono que substituíam a confirmação ainda pendente; a prova usa tempo absoluto crescente. Corrigida maturidade de beterraba pelo método específico de CropBlock. Pickup aguarda baseline do servidor antes de iniciar movimento e considera apenas slots de armazenamento ao avaliar espaço.
- Alimentação tolera a previsão do cliente que esvazia a última unidade antes do snapshot. Cancelamento após SWAP, inclusive antes do tick seguinte, tenta restauração condicionada a componentes/quantidade e identidade do jogador. Teclas e controladores são liberados mesmo se outro controlador falhar na restauração.
- F8/F9/F10 preservadas, inclusive nas telas de bancada/sono pertencentes à ação. Interface externa, perda de foco, perigo e desconexão continuam interrompendo o controle. Handshake e health anunciam `workstations-v1`; mod e script recusam reutilizar backend antigo incompatível, com diagnóstico específico.
- Diário e filosofia recebem a colocação verificada como mudança de lugar, sem alegar abrigo ou uso futuro já realizado. Formato histórico e entradas anteriores permanecem intactos. Não houve alteração do esquema SQLite; os testes usam bancos temporários.

### Verificação desta etapa

- `scripts/Test.ps1`: **71 testes Python passaram**; build Fabric **passou**, com **136 assertions Java** (incluem 100 consultas repetidas ao mesmo future pendente, não 136 cenários distintos).
- Contrato executou HttpClient Java → FastAPI/h11 em socket loopback: handshake, extensão de compatibilidade, observação com ingredientes/estação e comando `craft_table`, sem Upgrade. Outro teste de transporte confirmou ack e rejeição de sequência repetida.
- Testes adicionais cobrem cadeia tábuas→bancada→colocação→graveto→picareta, pão→refeição, prioridade da fome, falhas limitadas, cancelamento/reinício sem replay, ingredientes e estatísticas ausentes, estação incorreta, isolamento por mundo e proveniência do diário. Usam mensagens sintéticas; não comprovam física, GUI ou gameplay.
- JAR gerado: `mod/build/libs/minelife-ai-0.2.0.jar`. **Não instalado nesta etapa. Minecraft não foi aberto e nenhuma ação real foi executada.** Save, banco privado e diários reais não foram usados como fixtures nem publicados.

### Limites e próxima continuidade

- Crafting aceita uma lista vanilla de receitas desbloqueadas. Precisa de cursor/grade livres e um slot principal vazio. Para colocar material fora do hotbar, requer um slot vazio no hotbar. Organização geral de inventário permanece pendente.
- Não há abrigo por blueprint, caça, cozinhar/combustível na fornalha, uso de baús, seleção automática de ferramentas, armaduras, combate/fuga, plantio/replantio ou relações MCA. Fabricar os itens não equivale a executar essas habilidades.
- Navegação continua local; sem comida, cama, rota ou recursos viáveis, a espera é explícita. Não se afirma sobrevivência indefinida.
- Próximas dependências: seleção e prova de uso de ferramentas; inventário/fornalha com estados e retomada; blueprint pequeno com material, faces alcançáveis, colocação por etapa e prova do abrigo completo. A validação gráfica dessas capacidades permanece registrada, sem pedir teste manual nesta sessão.
- Publicação automática e pública de diários continuam desligadas. Sincronização de código deve passar pela auditoria do index; nenhum dado privado deve acompanhá-la.

## Histórico das etapas anteriores

Os registros abaixo descrevem o estado **à época de cada etapa**, inclusive limitações depois superadas. O estado atual e os resultados desta execução são os da seção acima.

## Continuação — repouso noturno em cama observada

- O sensor local anuncia camas vanilla que estejam carregadas e visíveis. No Overworld durante a noite, com controle ativo, sem ameaça próxima e rota local, o agente pode aproximar-se e usar uma cama existente pela interação normal do cliente.
- A ação não conclui por clicar: o servidor precisa confirmar aumento de `SLEEP_IN_BED` e transição do horário da noite para o dia. Cama alterada, rota bloqueada, ameaça, interação recusada, timeout ou transição sem estatística resultam em falha e não viram memória de sucesso.
- Quando não observa cama adequada, o agente aguarda com a limitação explícita. Não constrói abrigo e não contorna o bloqueio noturno.
- Reflexões autobiográficas sobre repouso vinculam-se ao evento verificado e não afirmam que o entorno ficou seguro.
- Verificações desta etapa: 57 testes Python passaram; build Fabric passou, incluindo 23 assertions Java de ControlGate/Food/RestEvidence. Nenhuma sessão gráfica Minecraft foi iniciada. O JAR não foi instalado e o save `ia` não foi alterado.

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
