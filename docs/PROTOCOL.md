# Bridge local do MineLife AI 0.2

## Extensões da revisão 2026-10-31

- `storage` anuncia até oito posições de baús vanilla simples observados. `player.inventory` contém contagens consolidadas. As ações `storage_inspect`, `storage_deposit` e `storage_withdraw` recebem `storage: {job_id, baseline?, item_id?, source_slot?, destination_slot?}`. Snapshots incluem `slots` (27), `player_slots` (36), `inventory`, `station`, `dimension`, `sync_id`, `station_opened` e `cursor_empty`. Cada célula tem `id`, `count`, `components` e `standard`. Transferências usam `PICKUP` nativo para uma unidade. O baseline completo e o estado esperado são persistidos antes do envio. Uma nova abertura pode trocar `sync_id`; a prova antes/depois de uma transferência exige o mesmo handler. Reconciliação exige nova inspeção: estado esperado encerra a intenção sem atribuir transferência; baseline intacto permite nova intenção; outro estado bloqueia a estação. Cancelamento incerto mantém a GUI aberta para evitar descarte de cursor não confirmado.
- `till` prepara farmland com enxada comum. Ferramentas encantadas ou inquebráveis não são elegíveis. `plant` exige umidade observada positiva e reserva de sementes; não confere irrigação futura nem crescimento. Colheita e drops permanecem provas distintas.
- A fornalha pode usar calor residual apenas quando o estado observado satisfaz `BurnTime >= cook_ticks + 40`; reinspeciona antes da próxima unidade.
- Rotas de retorno permitem até três segmentos sem novo avanço, afastamento de até seis blocos do melhor avanço e 64 segmentos totais, sempre a partir de fronteiras observadas. Isso não demonstra uma rota em chunks desconhecidos.
- A resposta pode conter `interrupt: UUID` do comando em andamento quando há fome e alimento disponível. O cliente só cancela o comando correspondente após validar sessão, sequência e epoch, estando ativo e armado. O backend aguarda o resultado `cancelled` antes de emitir alimentação; F10 continua sendo parada de emergência independente.

Esses contratos foram exercitados por testes automatizados e build, não por gameplay. O mod desta revisão não foi instalado nem executado no cliente.

A lista transferível inclui recursos vanilla, alimentos seguros permitidos, trigo e sementes de trigo/beterraba, sempre com componentes padrão. O planejador preserva três unidades por tipo de alimento, seis cenouras/batatas/trigo e oito sementes, somando demandas de projetos. Retirada de comida considera uma meta absoluta de três alimentos no total. Sob fome, o modo de armazenamento só inspeciona ou retira alimentos; não deposita nem busca material de construção. Ferramentas e alimentos inseguros continuam fora da lista. Transferir alimento não confirma ingestão.

Projetos de abrigo/fornalha são acompanhados em `LongProjects`, `ProjectDependencies`, `ProjectGoalLinks` e `ProjectDecisions` (SQLite v7). Essa camada não cria comandos: acrescenta foco limitado a objetivos já permitidos e registra condições, estagnação, suspensão e retomada. Conclusão depende de evidência do executor; inspeções de abrigo novas também incluem `dimension`. Não há inferência de execução a partir de texto LLM.

A bridge usa HTTP/1.1 JSON em `127.0.0.1:8765`; Uvicorn está fixado no parser h11 e com WebSocket desligado. O mod faz handshake autenticado `GET /bridge/handshake` e depois envia `POST /bridge/step`. O backend não é publicado para interfaces de rede.

## Sessão e segurança

Cada observação identifica sessão aleatória, mundo por hash, dimensão, sequência crescente, dia/hora, jogador, inventário, blocos, receitas anunciadas, capacidades, estado F8/F9/F10 e IDs de resultados. Não são transmitidos caminho do save ou seed em claro. O backend restringe Host/Origin e exige bearer local nas rotas, exceto `/health`. O instalador copia apenas o token necessário ao mod; a chave opcional de LLM fica no ambiente do backend.

O handshake informa protocolo 1, HTTP/1.1, heartbeat, prazo de lease, ações suportadas e `features: ["workstations-v1", "shelters-v1", "mining-cooking-v1"]`. O cliente desta revisão exige `mining-cooking-v1` antes de enviar campos novos; `/health` informa as extensões para o script de inicialização. Clientes antigos podem continuar enviando o formato anterior. Ações são usadas apenas quando constam das capabilities da observação (até 24; o mod atual anuncia 21).

O mod limita uma requisição em trânsito, usa timeout de 1,8 s e reconecta com backoff limitado. Ausência de resposta por 3 s libera teclas, cancela ações locais e exige nova autorização por F8; falha de transporte cria nova sessão. Sequência fora de ordem, sessão/dimensão trocadas e resultados que não correspondem a ID, mundo ou sessão não são aceitos.

Uma resposta contém IDs de resultados confirmados, no máximo um comando e o estado cognitivo. Os IDs são UUIDs e persistem antes do envio. A deduplicação Java tem tamanho limitado; o backend não reenvia comando de uma sessão antiga após reinício. A lease e o emergency stop independem do planejamento, que roda em baixa frequência.

## Ações implementadas

- `approach`: BFS local encontra rota em piso sólido, sem líquidos/perigos e com espaço para o jogador; cada próximo passo é revalidado.
- `break` / `collect`: interação e tecla de ataque nativas no mundo integrado. A remoção exige bloco-alvo→ar e aumento de estatística MINED; coleta exige aumento do inventário em relação ao baseline.
- `observe`: raycast de alcance real confirma a presença do bloco pelo estado do servidor. Não confirma propriedades ou drops.
- `explore`: navega até fronteira local informada pelo mod. Caminho BFS é recalculado e resultado exige posição/dimensão confirmadas pelo servidor.
- `craft`: receitas Minecraft desbloqueadas da lista permitida que cabem em 2×2 (tábuas, gravetos, bancada, tochas). O executor verifica grade/cursor livres, ingredientes e espaço, usa recipe book e coleta a saída pela interface nativa.
- `craft_table`: receitas 3×3 permitidas, como ferramentas de madeira/pedra/ferro, pão, fornalha e baú. Exige bancada observada e alcançável. O controlador abre e identifica o handler nativo, preenche uma receita e recolhe uma produção. Inventário e CRAFTED precisam confirmar todos os ingredientes e a saída exata. Fabricar esses itens não implementa automaticamente todos os seus usos.
- `place`: posiciona bancada/fornalha em célula livre com apoio sólido, alcance e raycast. Exige bloco antes vazio, bloco depois correto, consumo de exatamente um item e USED +1 no servidor. Não é um blueprint de abrigo.
- `mine`: minera um recurso de superfície anunciado com ferramenta adequada ou mão vazia quando permitido. Remoção exige bloco→ar, MINED +1 e desgaste +1 (zero para mão vazia), com snapshots do servidor. Inventário adquirido durante a ação é registrado separadamente, sem atribuir origem específica a cada item. Não abre túneis nem minera sem apoio.
- `furnace_inspect`, `furnace_load`, `furnace_take`: fases curtas de um trabalho persistente. GUI nativa deve corresponder ao bloco/handler/syncId no servidor. Inspeção lê slots; carga exige estação fria/vazia e transferências exatas de uma entrada e um combustível. Retirada exige redução do slot e aumento correspondente do inventário. Preparo só é atribuído após carga previamente verificada; recuperação de conteúdo compatível sem essa prova não é uma fabricação confirmada.
- `plant`: usa semente permitida em célula vazia sobre farmland existente. Exige solo, planta jovem, consumo de uma unidade e USED +1 confirmados. Não confirma crescimento ou colheita futura.
- `eat`: seleciona alimento permitido nos slots 0–35, usa a tecla nativa e confirma aumento de fome mais consumo de uma unidade. Troca temporária de slot é revertida se o estado continua compatível. Slot vazio na última unidade aguarda a leitura do servidor; não prova consumo sozinho.
- `pickup`: aproxima-se de ItemEntity observado; sucesso exige aumento de inventário e redução/remoção da mesma entidade UUID no servidor. Sumir do chão sozinho não confirma coleta.
- `harvest`: aproximação e quebra nativa de trigo/cenoura/batata/beterraba maduros; servidor deve confirmar maturidade antes, remoção e MINED. Não comprova drops ou alimentação.
- `sleep`: usa cama vanilla observada no Overworld à noite; requer SLEEP_IN_BED crescente e tempo absoluto avançando da noite para o dia. Cancelamento acorda o jogador quando o controlador iniciou o sono.
- `build_shelter`: coloca um componente de um blueprint conhecido, com projeto, âncora, índice e material. O Java deriva alvo/apoio/face do recurso empacotado. Resultado precisa conter projeto/índice correspondentes, bloco, inventários, USED e prova adicional de porta quando aplicável.
- `inspect_shelter`: lê somente as células do projeto conhecido em chunks carregados próximos. Retorna componentes, piso, interior, porta, passagem, posição e completude. Inspeção de estrutura parcial é uma execução válida, mas não cria abrigo concluído.
- `enter_shelter` / `leave_shelter`: navegam pela porta/passagem, usando interação nativa e colisões. Entrada exige estrutura completa, porta fechada e posição interna; saída de obra parcial é permitida com passagem/piso viáveis e é registrada como tal. Não confirmam sobrevivência de uma noite inteira.

O executor nunca escreve blocos ou inventário diretamente no servidor/save e não usa comandos, teleporte, Creative ou jogador adicional. Os snapshots do integrado são leituras. Interações físicas passam pelo cliente. Telas alheias à ação pausam o controle; bancada/fornalha pertencentes ao controlador e a tela de sono são permitidas. F8/F9/F10 também são lidas nessas telas. Cancelamento libera todas as teclas mesmo se uma restauração de inventário falhar; só restaura slots quando ainda pertencem ao mesmo jogador e estado esperado. Recursos já transferidos à fornalha permanecem nela e exigem nova inspeção, não um rollback fictício.

## Observações de crafting e colocação

Cada receita inclui `id`, `output_id`, `output_count`, `inputs` (item→quantidade), `grid` (2 ou 3) e `station` (posição da bancada ou null). Os campos históricos `input_id`/`input_count` permanecem compatíveis com 2×2; em ofertas novas correspondem a um dos ingredientes. O mod usa RecipeMatcher para selecionar ingredientes reais; o backend valida limites e não inventa receitas. São no máximo 32 ofertas.

`placement_spots` contém até 12 células observadas, cada uma com `x/y/z` e `support`, imediatamente abaixo. O comando carrega `target` e `placement: {item_id, support}`. Geometria, entidades, inventário e alcance são revalidados antes do clique. `craft_table` carrega a oferta completa em `recipe`, incluindo `station`; seu resultado inclui `station_opened`, `grid`, `station`, `recipe`, `crafted_delta` e inventários antes/depois. Prova de outra bancada, ingrediente não consumido ou quantidade inesperada é recusada.

`shelter_sites` contém até quatro âncoras de terreno livre observado, ainda sem atribuir uma construção existente. As ações do projeto carregam `shelter: {project, blueprint, anchor}` e, para colocação, `step`/`item_id`. Inspeção retorna `cells` na ordem canônica (índice, posição e ID), `floor_solid`, `interior_clear`, `door_valid`, `door_open`, `entrance_clear`, `complete`, `inside`, `outside` e `position`. O backend verifica geometria e consistência desses campos antes de atualizar etapas. Todos os resultados conservam a correlação original por comando/sessão/mundo. Veja [CONSTRUCTION.md](CONSTRUCTION.md).

## Evidência e protocolo de resultados

`player.tools` contém até 36 ferramentas com slot, tipo, desgaste e usabilidade. `mining` anuncia até 16 alvos e a ferramenta escolhida (`tool_id`, `tool_slot`, `tool_damage`, `tool_max_damage`, `tool_speed`, `tool_suitable`, `tool_required`, `tool_wear`, `tool_material`). A oferta inteira é revalidada antes da execução. Mão vazia requer slot vazio no hotbar e bloco que dispense ferramenta; a coleta nativa pode ocupar esse slot depois da remoção.

`cooking` anuncia até 16 combinações reais de receita, entrada, saída, `cook_ticks`, combustível e `fuel_ticks`; combustível ausente é `null` e não autoriza carga. `blocks[].lit` informa fornalha acesa observada. Comandos carregam `furnace: {job_id, recipe, recover}` e alvo; resultados contêm snapshots `before`/`after` com estação, dimensão, interface, inventário e três slots (`id`, `count`), além de `take_slot` na retirada. Cancelamento/falha invalida a inspeção em cache; reinício inspeciona novamente. Conteúdo conflitante é preservado.

`farmland` anuncia até 12 posições de ar sobre solo agrícola, `x/y/z`, `moisture` (0–7) e `water` opcional, sem `support`. O executor deriva o apoio imediatamente abaixo. Observações legadas sem `moisture` continuam aceitas com valor -1; clientes novos aguardam hidratação e preservam uma semente. O comando contém `planting: {item_id, crop_id}` e alvo; prova inclui solo, idade zero, inventários e USED. `tilling` anuncia até 12 ofertas com solo, enxada e água observada; o comando `till` recebe a oferta em `tilling`. `placement_spots` mantém seu formato diferente com `support` explícito.

Cada resultado é associado ao comando criado pelo backend, sessão, mundo e experimento. Campos vindos do cliente não bastam por si só: sucesso é revalidado contra estado/inventário/estatística no servidor integrado. O backend exige alvo e delta de inventário/estatística esperados antes de criar conhecimento confirmado. Remoção e coleta são eventos diferentes. Hipótese e reflexão filosófica guardam IDs das evidências. Uma intenção estruturada de LLM pode ajustar a prioridade de habilidades disponíveis; não emite ações, não anula segurança nem vira fato. Prosa livre permanece não verificada; composição factual do diário aceita somente referências/afirmações exatas autorizadas.

Testes de contrato executam HttpClient Java contra FastAPI temporária em socket loopback e verificam versão HTTP 1.1, ausência de Upgrade, handshake, observação, comando e confirmação. São teste de transporte, não execução gráfica nem prova de movimento dentro do Minecraft.

## Diagnóstico

- `GET /health` prova apenas que um servidor responde e contém versão/extensões do backend.
- `backend_update_required_mining_cooking_v1`: o mod é mais recente que o processo Python. Reinicie o backend com os scripts do projeto; não altere o token ou transporte para contornar a incompatibilidade.
- `GET /api/state` exige token e mostra heartbeat, estado, motivo de espera, ciclos, objetivo e capacidades recebidas.
- Logs Java registram ação, status e classe de erro sem token; logs locais não devem ser publicados.
- `Unsupported upgrade request` não se aplica ao transporte atual: o cliente usa HTTP/1.1 sem WebSocket/Upgrade e o servidor executa somente h11. Se surgir HTTP inválido, confirme que só há uma instância na porta local e que o processo tem a mesma versão do projeto.
- Após pause, emergência ou reconexão, o mod só volta a agir quando as condições físicas forem seguras e F8/F9 permitirem.

O modelo de confiança é um computador local; outro processo que já possua o token pode usar a API local. Não encaminhe a porta, não publique tokens e não use painel em origem remota.

APIs consultadas para esta extensão: [RecipeMatcher, Yarn 1.21.1+build.3](https://maven.fabricmc.net/docs/yarn-1.21.1+build.3/net/minecraft/recipe/RecipeMatcher.html) e [CraftingScreenHandler](https://maven.fabricmc.net/docs/yarn-1.21.1+build.3/net/minecraft/screen/CraftingScreenHandler.html). A compilação usa essas mappings; a consulta/compilação não substitui validação do comportamento em jogo.
