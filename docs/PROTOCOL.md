# Bridge local do MineLife AI 0.2

A bridge usa HTTP/1.1 JSON em `127.0.0.1:8765`; Uvicorn está fixado no parser h11 e com WebSocket desligado. O mod faz handshake autenticado `GET /bridge/handshake` e depois envia `POST /bridge/step`. O backend não é publicado para interfaces de rede.

## Sessão e segurança

Cada observação identifica sessão aleatória, mundo por hash, dimensão, sequência crescente, dia/hora, jogador, inventário, blocos, receitas anunciadas, capacidades, estado F8/F9/F10 e IDs de resultados. Não são transmitidos caminho do save ou seed em claro. O backend restringe Host/Origin e exige bearer local nas rotas, exceto `/health`. O instalador copia apenas o token necessário ao mod; a chave opcional de LLM fica no ambiente do backend.

O handshake informa protocolo 1, HTTP/1.1, heartbeat, prazo de lease e ações suportadas. O mod limita uma requisição em trânsito, usa timeout de 1,8 s e reconecta com backoff limitado. Ausência de resposta por 3 s libera teclas, cancela ações locais, cria nova sessão e exige nova autorização por F8. Sequência fora de ordem, sessão/dimensão trocadas e resultados que não correspondem a ID, mundo ou sessão não são aceitos.

Uma resposta contém IDs de resultados confirmados, no máximo um comando e o estado cognitivo. Os IDs são UUIDs e persistem antes do envio. A deduplicação Java tem tamanho limitado; o backend não reenvia comando de uma sessão antiga após reinício. A lease e o emergency stop independem do planejamento, que roda em baixa frequência.

## Ações implementadas

- `approach`: BFS local encontra rota em piso sólido, sem líquidos/perigos e com espaço para o jogador; cada próximo passo é revalidado.
- `break` / `collect`: interação e tecla de ataque nativas no mundo integrado. A remoção exige bloco-alvo→ar e aumento de estatística MINED; coleta exige aumento do inventário em relação ao baseline.
- `observe`: raycast de alcance real confirma a presença do bloco pelo estado do servidor. Não confirma propriedades ou drops.
- `explore`: navega até fronteira local informada pelo mod. Caminho BFS é recalculado e resultado exige posição/dimensão confirmadas pelo servidor.
- `craft`: apenas receitas Minecraft desbloqueadas, aceitas pelo recipe book e cabendo na grade 2×2, entre tábuas, gravetos e bancada. O executor nativo verifica tela/grade vazia, clique de receita, item resultante, consumo, aumento de inventário e estatística CRAFTED. Receita sem prova vira falha, sem aprendizado.

O executor não remove nem coloca blocos diretamente, não usa comandos, teleporte, Creative, jogador adicional ou clique para abrir telas. Crafting avançado 3×3 e uso da bancada ainda não existem. Abrir interface interrompe o controle.

## Evidência e protocolo de resultados

Cada resultado é associado ao comando criado pelo backend, sessão, mundo e experimento. Campos vindos do cliente não bastam por si só: sucesso é revalidado contra estado/inventário/estatística no servidor integrado. O backend exige alvo e delta de inventário/estatística esperados antes de criar conhecimento confirmado. Remoção e coleta são eventos diferentes. Hipótese e reflexão filosófica guardam IDs das evidências; rascunho de LLM tem status `unverified` e não altera conhecimento, metas físicas nem diário.

Testes de contrato executam HttpClient Java contra FastAPI temporária em socket loopback e verificam versão HTTP 1.1, ausência de Upgrade, handshake, observação, comando e confirmação. São teste de transporte, não execução gráfica nem prova de movimento dentro do Minecraft.

## Diagnóstico

- `GET /health` prova apenas que um servidor responde e contém versão do backend.
- `GET /api/state` exige token e mostra heartbeat, estado, motivo de espera, ciclos, objetivo e capacidades recebidas.
- Logs Java registram ação, status e classe de erro sem token; logs locais não devem ser publicados.
- `Unsupported upgrade request` não se aplica ao transporte atual: o cliente usa HTTP/1.1 sem WebSocket/Upgrade e o servidor executa somente h11. Se surgir HTTP inválido, confirme que só há uma instância na porta local e que o processo tem a mesma versão do projeto.
- Após pause, emergência ou reconexão, o mod só volta a agir quando as condições físicas forem seguras e F8/F9 permitirem.

O modelo de confiança é um computador local; outro processo que já possua o token pode usar a API local. Não encaminhe a porta, não publique tokens e não use painel em origem remota.
