# Roadmap

O status diferencia implementação, validação automatizada e observação no jogo. Não há marco de dias fixo; objetivos futuros surgem apenas quando o contexto e as habilidades suportam ações.

## Implementado e coberto por testes locais

- Cadeia de fabricação com receitas anunciadas: recursos conhecidos podem ser repostos conforme estoque, tábuas/bancada/graveto em 2×2, colocação nativa de bancada e fabricação 3×3 de ferramentas/pão. O planejador respeita ingredientes, estação observada, capacidades e demanda; não termina após aprender uma receita. Ferramentas/fornalha/baú fabricados ainda não têm todos os seus usos automatizados.
- Colocação inicial de estação: espaço livre, apoio sólido e alcance observados; item consumido e USED +1 confirmados. Não é construção de abrigo. Troca temporária de hotbar e interface de crafting possuem cancelamento; F8/F9/F10 continuam ativos nas telas pertencentes à ação.
- HTTP/1.1 com extensão `workstations-v1`; incompatibilidade com backend antigo é diagnosticada antes de enviar novas observações. Teste de transporte Java–FastAPI também cobre a oferta e o comando 3×3.

- Repouso noturno inicial usando cama vanilla existente no Overworld: interação nativa, rota local e ausência de ameaça próxima revalidadas, com sucesso somente após estatística `SLEEP_IN_BED` e transição para o dia confirmadas pelo servidor. Sem cama segura, ainda aguarda; abrigo físico continua pendente. Ainda sem teste em gameplay.

- Continuação: pickup de `ItemEntity` exige UUID e prova dupla do servidor (inventário aumenta e a mesma entidade diminui/desaparece); prioridade para comida segura observada quando a fome está baixa. Colheita nativa inicial de trigo/cenoura/batata/beterraba maduros durante o dia confirma apenas bloco removido/estatística MINED; drops e refeição são confirmações separadas. Nenhum desses novos comportamentos foi ainda validado em gameplay.
- Reflexões contextuais sobre necessidade e escolha após refeição verificada, e sobre cultivo removido sem presumir seus drops.

- Controle do personagem local no integrado, autorização F8/F9/F10, pausa segura, handshake HTTP/1.1 autenticado e recuperação de desconexão.
- Percepção local, observação de blocos visíveis, aproximação/mineração de troncos, prova de remoção/coleta, navegação segura em região local e crafting de receitas desbloqueadas 2×2 para tábuas, gravetos e bancada.
- Cognição em ciclos limitados, objetivos por mundo, cooldowns, limites de repetição, oportunidades derivadas, exploração por fronteiras anunciadas e estado explícito de espera.
- SQLite migrável com backup, personalidade/interesses que alteram prioridades e margem de segurança, memórias episódicas salientes, recuperação lexical e reflexões contextuais ligadas à evidência.
- Diário narrativo por eventos com manifest de proveniência, lembranças anteriores e interpretações provisórias. Rascunhos de LLM são persistidos como não verificados e nunca entram no conhecimento factual ou no diário publicável.
- Alimentação de emergência com comida permitida nos slots principais 0–35: execução pela tecla nativa, confirmação de fome/inventário e restauração condicionada do slot. Prioridade sobre projetos e tentativas limitadas. Esta implementação ainda precisa de teste de gameplay.
- Life Observer com mente estruturada e rascunhos rotulados. Publicador de diário para o repositório oficial, mas envio automático/publicação de diário permanecem desativados.

## Necessita validação no Minecraft desta versão

- Movimento 0.2, parada em perda de conexão, sensores, coleta/colheita, alimentação da última unidade, sono, exploração e autonomia prolongada.
- Cadeia física completa de bancada: colocação, abertura/fechamento, fabricação 2×2/3×3, retorno dos materiais após cancelamento, F10 durante GUI, uso do pão fabricado e ausência de duplicação. Os testes de protocolo não substituem essa execução.
- Persistência ao reiniciar backend depois da migração do banco legado, integração de tela com o perfil MCA instalado e funcionamento em terrenos/situações reais.

Um teste anterior do MVP 0.1 confirmou quebra e coleta de um tronco de bétula e diário persistente. Esse resultado não valida alterações recentes no navegador, protocolo, crafting, filosofia ou escrita narrativa.

## Próximas capacidades

1. Completar obtenção/preparação de comida: fornalha real com combustível, retorno de resultados e retomada; plantio/replantio; eventual caça limitada a espécies permitidas. Coleta e colheita iniciais já existem, mas não constituem abastecimento completo.
2. Usar ferramentas fabricadas e ampliar gestão de inventário: seleção apropriada, desgaste, mineração/drop específico, armaduras e armazenamento. O 3×3 atual já fabrica parte dos itens, mas não executa essas tarefas.
3. Navegação por rotas maiores, memória de retorno, caminhos alternativos e recuperação de terreno; sem assumir que uma fronteira local seja segura para viajar longas distâncias.
4. Projetos de abrigo: aproveitar o executor de colocação, ampliar faces/alcance, calcular materiais, decompor blueprint, verificar proteção e corrigir etapas. Integrar retirada/retorno seguro à sobrevivência noturna. Hoje só estações são colocadas.
5. Agricultura e mecanismos com verificação física; então estoques e economia de trocas reais.
6. Inspecionar API e interfaces de MCA Reborn 7.7.19 no ambiente instalado; implementar memória social, interação, relacionamentos e família somente sobre interfaces reais validadas.
7. Projetos comunitários e vila, dependentes de construção, sobrevivência, armazenagem e integração social já comprovadas.

Nenhuma etapa de combate, construção de estruturas, fazendas, comércio, integração social, casamento, família, vila ou sobrevivência prolongada deve ser marcada como feita até que exista executor real, evidência observável e validação apropriada. Não é necessário solicitar teste manual para continuar desenvolvendo dependências isoladas; mantenha a pendência de gameplay explícita.
