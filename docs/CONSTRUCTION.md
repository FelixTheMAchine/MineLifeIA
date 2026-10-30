# Primeiro abrigo: implementação e limites

O projeto `refuge_v1` é um refúgio de emergência, com footprint 3×3, interior 1×1 e dois blocos de altura livre. Usa **16 tábuas e uma porta de madeira**, em 17 interações de colocação. A receita vanilla de portas usa mais seis tábuas e produz três portas; o projeto usa uma e mantém as outras. Bancada e ferramentas são necessidades separadas.

O blueprint é um recurso compartilhado pelo Python e pelo JAR: `mod/src/main/resources/minelife_ai/blueprints/refuge_v1.json`. Ele define alvos, apoios, faces e ordem. Os cantos antecedem as laterais para manter faces visíveis. Um pequeno beiral apoia o teto central; sua colocação exige um salto normal. A porta fica ao sul e é colocada por último. Não há comandos administrativos, edição do save nem criação de itens.

## Ciclo operacional

1. O mod anuncia no máximo quatro terrenos próximos, carregados, livres e visíveis, com piso sólido e acesso externo. Não derruba plantas, não nivela terreno e não remove construções para abrir espaço.
2. O backend cria um projeto persistente, ainda sem fatos de construção. Uma inspeção do servidor confirma quais células estão vazias ou presentes.
3. O cálculo de materiais influencia a reposição de troncos e as receitas já anunciadas. A bancada deve ficar fora do footprint e da passagem. A construção começa somente com reserva para as etapas ainda faltantes e a porta pronta.
4. Cada comando `build_shelter` navega para o interior e coloca **um** componente. Alcance, apoio, raycast, colisões, item e Survival são revalidados. A colocação só avança com bloco correto, USED +1 e consumo de uma unidade no servidor. A porta também exige suas duas metades e orientação corretas.
5. Uma inspeção final separada confere todos os componentes, piso, interior e porta. Dezessete respostas de colocação, sozinhas, não concluem o abrigo.
6. À noite, na ausência de uma cama utilizável, o plano pode entrar no abrigo próximo, fechar a porta e confirmar posição interna e estrutura. Durante a espera, reavalia a geometria em intervalos de pelo menos 15 segundos. Ao amanhecer, sai, fecha a porta e continua o planejamento normal.

O projeto está integrado ao painel, aos objetivos, à memória, ao diário e às reflexões. Os registros de cada bloco ficam na auditoria, mas não geram uma reflexão filosófica a cada colocação. Conclusão inspecionada, entrada e saída têm eventos distintos. Entrar em um refúgio não prova ter sobrevivido a uma noite inteira.

## Interrupção, persistência e recuperação

`ConstructionProjects` e `ConstructionSteps` são tabelas aditivas do esquema SQLite v4. Migração de banco existente gera backup antes de criar o novo esquema. Não modifica eventos, conhecimento ou diários antigos. Um esquema mais recente é recusado, sem downgrade.

Após reinício, os comandos anteriores são interrompidos pelo mecanismo existente. O projeto precisa ser inspecionado novamente. Um bloco encontrado sem resposta de colocação é marcado `present`, não `placed`: isso comprova presença, sem atribuir a ação ao agente. Uma célula antes comprovada que esteja vazia ganha nova revisão para permitir reparo, sujeito a materiais, apoio e alcance. Blocos inesperados são preservados e bloqueiam a obra; não são removidos automaticamente.

F8, F9, F10, perda de conexão, mudança de mundo, perigo e interfaces externas cancelam os executores. Hotbar temporário é restaurado somente se ainda pertence ao mesmo jogador e mantém o estado esperado. A porta pode permanecer aberta se houver uma interrupção; isso não produz sucesso e é reavaliado depois. Um projeto parcial pode ser abandonado fisicamente pela passagem existente se faltarem recursos ou condições, sem ser chamado de abrigo concluído.

Para conferir uma migração sem alterar a memória real:

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_memory_upgrade --dry-run
```

Esse comando cria uma cópia temporária consistente via SQLite, compara fingerprints de todas as tabelas anteriores, testa integridade e verifica novamente a origem. Não inicia cognição ou Minecraft.

## Limitações verificadas

- Há um projeto operacional de refúgio por mundo/dimensão nesta fase. O esquema admite novos projetos, mas não há gerador de casas maiores ou estilos arquitetônicos. Concluir o refúgio não encerra exploração ou outros objetivos.
- Navegação e retorno são locais, até a região que o navegador consegue alcançar. Não há viagem autônoma de volta a uma base distante.
- Só aceita terreno já adequado; não constrói fundação, escadas ou pontes. Materiais/receitas indisponíveis geram espera explícita e outras oportunidades.
- A colocação usa tábuas e portas vanilla permitidas, não areia, gravidade, líquidos ou blocos desconhecidos. Precisa de slot livre no hotbar se o material não estiver nele.
- Reparo é limitado a células vazias do blueprint e faces alcançáveis. Não há demolição/reconstrução geral, garantia contra incêndio/ataque, iluminação, cama interna ou combate defensivo.
- A inspeção mede uma estrutura concreta naquele momento. Não demonstra proteção permanente ou ausência de todos os riscos externos.
- Não houve gameplay nesta implementação. Uma tentativa de inicializar registries vanilla fora do Loader para testar formas de porta falhou com `IllegalAccessError` em `SimpleRegistry`/`RegistryEntry.Reference`; essas classes exigem transformações de runtime. A suíte usa geometria estática explicitamente identificada e não apresenta isso como teste de portas no jogo.

APIs consultadas: [DoorBlock no Yarn 1.21.1+build.3](https://maven.fabricmc.net/docs/yarn-1.21.1+build.3/net/minecraft/block/DoorBlock.html) e [CollisionView](https://maven.fabricmc.net/docs/yarn-1.21.1+build.3/net/minecraft/world/CollisionView.html). Os controladores compilam com essas mappings. O navegador verifica o volume percorrido do jogador ao atravessar uma porta aberta, pois a folha da porta continua tendo colisão.
