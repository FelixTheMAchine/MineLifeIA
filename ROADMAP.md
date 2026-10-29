# Roadmap

O status diferencia implementação, validação automatizada e observação no jogo. Não há marco de dias fixo; objetivos futuros surgem apenas quando o contexto e as habilidades suportam ações.

## Em uso e coberto por testes locais

- Repouso noturno inicial usando cama vanilla existente no Overworld: interação nativa, rota local e ausência de ameaça próxima revalidadas, com sucesso somente após estatística `SLEEP_IN_BED` e transição para o dia confirmadas pelo servidor. Sem cama segura, ainda aguarda; abrigo físico continua pendente. Ainda sem teste em gameplay.

- Continuação: pickup de `ItemEntity` exige UUID e prova dupla do servidor (inventário aumenta e a mesma entidade diminui/desaparece); prioridade para comida segura observada quando a fome está baixa. Colheita nativa inicial de trigo/cenoura/batata/beterraba maduros durante o dia confirma apenas bloco removido/estatística MINED; drops e refeição são confirmações separadas. Nenhum desses novos comportamentos foi ainda validado em gameplay.
- Reflexões contextuais sobre necessidade e escolha após refeição verificada, e sobre cultivo removido sem presumir seus drops.

- Controle do personagem local no integrado, autorização F8/F9/F10, pausa segura, handshake HTTP/1.1 autenticado e recuperação de desconexão.
- Percepção local, observação de blocos visíveis, aproximação/mineração de troncos, prova de remoção/coleta, navegação segura em região local e crafting de receitas desbloqueadas 2×2 para tábuas, gravetos e bancada.
- Cognição em ciclos limitados, objetivos por mundo, cooldowns, limites de repetição, oportunidades derivadas, exploração por fronteiras anunciadas e estado explícito de espera.
- SQLite migrável com backup, personalidade/interesses que alteram prioridades e margem de segurança, memórias episódicas salientes, recuperação lexical e reflexões contextuais ligadas à evidência.
- Diário narrativo por eventos com manifest de proveniência, lembranças anteriores e interpretações provisórias. Rascunhos de LLM são persistidos como não verificados e nunca entram no conhecimento factual ou no diário publicável.
- Alimentação de emergência com comida segura existente no hotbar: execução pela tecla nativa e confirmação de fome/inventário no servidor. Esta implementação ainda precisa de teste de gameplay.
- Life Observer com mente estruturada e rascunhos rotulados. Publicador de diário para o repositório oficial, mas envio automático/publicação de diário permanecem desativados.

## Necessita validação no Minecraft desta versão

- Movimento 0.2, parada em perda de conexão, sensor de blocos, coleta, exploração local, estado prolongado da autonomia e crafting real na tela 2×2.
- Persistência ao reiniciar backend depois da migração do banco legado, integração de tela com o perfil MCA instalado e funcionamento em terrenos/situações reais.

Um teste anterior do MVP 0.1 confirmou quebra e coleta de um tronco de bétula e diário persistente. Esse resultado não valida alterações recentes no navegador, protocolo, crafting, filosofia ou escrita narrativa.

## Próximas capacidades, depois de validar a base

1. Obter comida: coleta segura, inspeção de animais/plantas e, depois, cozinha; a habilidade atual somente come itens já no hotbar. Em seguida, sobrevivência noturna com cama/abrigo, rota de retirada e resposta a perigos sem congelamento indefinido.
2. Inventário e crafting 3×3 por bancada, fornalhas, ferramentas, armadura e uso de itens com provas de consumo/resultado.
3. Navegação por rotas maiores, memória de retorno, caminhos alternativos e recuperação de terreno; sem assumir que uma fronteira local seja segura para viajar longas distâncias.
4. Projetos físicos de construção com cálculo de materiais, posicionamento nativo de blocos e inspeção/correção.
5. Agricultura e mecanismos com verificação física; então estoques e economia de trocas reais.
6. Inspecionar API e interfaces de MCA Reborn 7.7.19 no ambiente instalado; implementar memória social, interação, relacionamentos e família somente sobre interfaces reais validadas.
7. Projetos comunitários e vila, dependentes de construção, sobrevivência, armazenagem e integração social já comprovadas.

Nenhuma etapa de combate, construção física, fazendas, comércio, integração social, casamento, família, vila ou sobrevivência prolongada deve ser marcada como feita até que exista executor real, evidência observável e validação apropriada.
