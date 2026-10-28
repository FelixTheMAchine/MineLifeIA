# Ponte local, versão 1

HTTP JSON em `127.0.0.1:8765`, 4 consultas por segundo, sem requisições simultâneas
do mod. Equivalente ao canal WebSocket solicitado: cada observação carrega
resultados pendentes e a resposta carrega comandos, confirmações e controle.
O cliente usa HttpClient assíncrono; nenhuma chamada de rede bloqueia o tick.

`POST /bridge/step` exige `Authorization: Bearer <segredo local>`.
O esquema Pydantic está em `agent/protocol.py`. Envelope: versão, UUID da sessão,
hash do mundo, dimensão, sequência crescente, dia/hora do jogo, estado de controle,
jogador, candidatos a árvore e resultados. Respostas repetem sessão/sequência,
confirmam IDs dos resultados e incluem no máximo um comando.

Comandos: `approach`, `break`, `collect`, cada um com UUID, alvo e prazo máximo de
20 segundos. O backend persiste o comando antes da resposta. O mod deduplica IDs
na sessão; o backend processa cada resultado uma vez e verifica mundo/sessão/alvo.
Um comando sem resultado pode ser reenviado com o mesmo ID. Reconexão cria nova
sessão, interrompe experimentos pendentes e exige nova autorização F8.

A mineração mantém a tecla de ataque pressionada e usa o loop nativo do cliente.
Não chama a remoção direta de blocos e não acelera o progresso de quebra. Câmera,
raycast, alcance de 3,5 blocos e colisões são respeitados. Uma tarefa no thread
do servidor integrado **somente lê** bloco, inventário e estatística MINED antes
e depois. Uma quebra só é aceita quando o alvo vira ar e a estatística aumenta.
A coleta exige ainda aumento da contagem do item, usando a linha de base anterior
à quebra, para detectar também itens coletados durante a mineração.

O cliente desativa controle por perda de backend (até 1,5 s), interface aberta,
perda de foco, modo diferente de Survival, água/fogo/lava, queda, pouca vida/fome
ou monstro próximo. Interrupção libera teclas e cancela quebra. Não há respawn
automático, combate nem promessa de sobrevivência em qualquer situação.

O painel usa o mesmo segredo local, sem persistir no navegador. Host e Origin
são restringidos. Apenas loopback é usado. Nenhum segredo aparece em URL/log.
Uma sessão ativa exclui outra conexão recente. Observações detalhadas são
persistidas a aproximadamente 1 Hz com retenção de 10.000 por mundo; evidências,
eventos, experimentos e diários persistem sem expiração.

Ainda não há transporte com MAC por mensagem ou proteção contra outro processo
local que já possua o token. O modelo de confiança é um único computador pessoal.
