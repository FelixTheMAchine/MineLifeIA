# Protocolo de comparação experimental

## Pergunta e condições

Pergunta: a recuperação de memória episódica verificável melhora decisões de um agente com modelo local sob orçamento computacional controlado?

O primeiro ensaio de infraestrutura está em `scripts/experiment_compare.py` (`python -m scripts.experiment_compare --seeds 7 19 41`). Ele clona a mesma fixture sintética para bancos temporários independentes, usa sugestão tipada roteirizada idêntica em B/C e confirma que B omite episódios enquanto C os recupera. **Esse ensaio não chama LLM e não testa a hipótese científica**; serve para validar isolamento, contratos e proveniência antes de medições com modelo real.

`scripts/experiment_real_compare.py` usa a mesma fixture com até uma inferência Ollama local por braço B/C, sem ler configuração ou memória privada. Seu relatório separa saída válida, intenção vinculada, influência na escolha e resultado físico (ausente nesta fixture). Se faltar RAM, o processo Minecraft estiver ativo/desconhecido, ocorrer timeout ou a primeira inferência não terminar, o par fica parcial e não pode ser usado para inferir efeito da memória. O guarda experimental exige 4.096 MB de RAM livre antes da chamada; essa reserva foi elevada após uma execução local inconclusiva com pressão de memória, não é uma calibração universal.

- **A — determinístico:** planejador atual sem chamada ao LLM e sem recuperação episódica.
- **B — LLM sem episódios:** mesmo planejador e modelo de C, com intenções contextuais, mas sem memórias episódicas recuperadas.
- **C — LLM com episódios verificáveis:** configuração B com recuperação limitada a episódios cuja proveniência e resultado estejam confirmados.

Fixar versão do código, configuração, prompt, modelo e quantização, timeout, orçamento de tokens, parâmetros do provedor, capacidades e limites de segurança. A indisponibilidade do LLM em B/C deve ser registrada como fallback, nunca ocultada. Não permitir ao modelo emitir ações físicas ou criar fatos.

## Cenários, sementes e isolamento

Manter um manifesto versionado de cenários que especifique estado inicial, observações disponíveis, objetivos elegíveis, recursos, perigos, transições e condição de término. A suíte sintética deve cobrir necessidade imediata, projeto de múltiplas etapas, erro anterior relevante/irrelevante, falha e recuperação após reinício, referência ausente ou obsoleta e cenário sem memória útil.

Cada cenário recebe um identificador e semente fixa; usar a mesma semente e estado inicial nas três condições. Registrar a semente junto da versão do gerador. A aleatoriedade do modelo deve ser fixada quando suportada; caso contrário, registrar parâmetros e repetições, sem alegar determinismo.

Cada repetição usa banco SQLite descartável e diretório de estado próprios, inicializados da mesma fixture imutável. A/B não podem ler tabelas de episódios; B/C não compartilham bancos nem estado mutável. Um teste de reinício fecha e reabre o mesmo banco da repetição. Nunca apontar os experimentos para `data/`, configuração local ou save principal.

Gameplay, se conduzido em etapa separada, exige mundo Survival descartável por repetição, cópia de baseline documentada e backup antes de instalar/testar. Não usar comandos, Creative ou jogadores extras. Não misturar sessões, mundos ou resultados sintéticos com gameplay.

## Pareamento e execução

Executar A, B e C sobre cada cenário pareado. Alternar ou randomizar a ordem das condições por bloco de cenário para reduzir efeitos de carga/temperatura. Fazer repetições suficientes para reportar dispersão e falhas; publicar previamente quantidade, exclusões e critérios de término. Não remover timeouts, fallbacks ou resultados ruins da análise principal. Comparar B−A, C−B e C−A por cenário, além dos totais agregados.

## Métricas e proveniência

Registrar por repetição: condição, cenário/versão/semente, código/configuração/modelo, estado inicial e hash da fixture; objetivos concluídos; ações propostas, permitidas, falhas e retries; repetição de erros; recuperação; continuidade de projetos após reinício; referências inválidas; latência cognitiva e total; tokens; CPU/RAM quando disponíveis; timeouts e frequência de fallback.

Cada decisão deve poder ser ligada a IDs de sessão, mundo ou fixture, objetivo, plano, intenção, memória recuperada, comando e resultado. Uma referência de memória inclui seu ID e evidência de origem; resultado positivo requer confirmação pelo estado observado/servidor, não texto do modelo. Guardar logs locais com dados sensíveis removidos. Relatar dados ausentes como ausentes, não como zero.

Contar separadamente falhas operacionais, resultados físicos confirmados e resultados inconclusivos. Um timeout ou erro de evidência pode aumentar tentativas/cooldown, mas não deve ser somado como fracasso comprovado da estratégia nem usado como sinal negativo de preferência.

O evento `goal_selected` registra uma **decisão**, o ID do comando e o ID da observação que a originou; não registra resultado físico. A observação da decisão é persistida mesmo fora da amostragem periódica. `mode=ranked` inclui alternativas, componentes heurísticos e baseline sem bônus da mente. `mode=direct` cobre urgência ou projeto escolhido antes do ranking e não afirma comparação. `LifeMetrics` conta a seleção apenas se observação, comando, sessão, mundo e objetivo corresponderem. `mind_changed_choices` exige também `MindEvaluations` com seleção influenciada. `preference_weighted_choices` conta escolhas com componente de preferência aprendida não nulo; não mede influência causal de memória episódica. Esta exige comparação pareada com e sem recuperação.

Como `Observations` retém as 10 mil linhas recentes por mundo, decisões antigas podem perder a observação bruta. `older_missing_goal_observations` conta separadamente vínculos ausentes cuja decisão antecede a observação mais antiga ainda retida; essa idade sugere retenção, mas não prova a causa da perda. Essas decisões não entram em `goal_selections` nem são tratadas como resultado físico.

## Natureza das evidências

Fixtures, adaptadores falsos e simulações são **sintéticos**; seus resultados medem apenas comportamento no cenário controlado. Respostas reais do LLM em fixture continuam sendo avaliação sintética, não gameplay. Uma execução no Minecraft só é **gameplay** quando houver evidência correlacionada de sessão, hash do mundo, comando e estado/resultados do servidor. Relatar as duas categorias em tabelas e conclusões separadas. Não inferir sobrevivência real, autonomia longitudinal ou validade ecológica a partir de fixtures.

## Ameaças à validade e relato

Diferenças entre condições além da recuperação de episódios (prompt, orçamento, timeout ou versão), vazamento de estado entre bancos, cenários pouco representativos, variabilidade do modelo, carga da máquina, seleção de sementes e baixa quantidade de repetições podem enviesar a comparação. A avaliação de memória deve separar qualidade da recuperação da qualidade da decisão. Uma memória pode ajudar ou prejudicar; não assumir efeito positivo.

Publicar método, manifesto, código/commit, dependências, parâmetros, sementes, quantidade de repetições, falhas, exclusões justificadas, intervalos/dispersão e limitações. Fixtures ilustrativas devem ser identificadas como sintéticas. Não apresentar resultados antes da execução nem reivindicar conclusões científicas além das evidências coletadas.
