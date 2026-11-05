# Fase 0.3 — coleta verificada e exploração controlada

## Diagnóstico e trabalho concluído

O fluxo de coleta dependia de planejamento de mineração e execução do comando sem uma intenção de aquisição suficientemente explícita no plano da meta. O cooldown podia deixar a exploração assumir a vez antes de a coleta terminar. No adaptador do jogo, a validação também precisava considerar a posição inicial do jogador e a mudança observável da entidade-alvo.

A coleta agora é acompanhada por `GoalPlans.params` com limites: até 3 observações elegíveis, 24 verificações e 2 tentativas. A confirmação exige UUID da entidade e aumento compatível no inventário. O evento não atribui a origem de itens quando as evidências não permitem distingui-la. A exploração também ganhou limites: três viagens sem ganho podem pausar esse objetivo; a recuperação pode durar até 90 segundos e pode selecionar outra meta executável. Retornos não são penalizados e não há exploração aleatória.

Resultados de verificação disponíveis:

- 319 testes Python e Fabric passaram.
- `migration --dry-run` sobre a memória real encontrou 50 tabelas e fingerprints intactos no schema 9. O original não foi migrado.
- A correção de coleta passou 17 regressões novas, 26 testes de `mining_cooking`, 35 de `continuous` e o build do mod.
- A adaptação passou 6 testes novos e 3 de `long_life`.

Esses resultados são testes e verificações técnicas; não demonstram coleta ou comportamento em gameplay real.

## Estado parcial

Projetos (3), necessidades (4), LLM (5) e observador (6) permanecem em implementação ou aguardam validação. Não são declarados completos nesta fase. Atualizar esta seção com o resultado final antes do commit.

## Instalação e validação real — ainda não executadas

1. Fechar Minecraft e parar normalmente o backend. Não matar processos. Parar o daemon Gradle com `mod/gradlew.bat --stop`.
2. Fazer o backup da memória com `scripts/backup_memory.py`; quando houver migração autorizada, usar o fluxo de migração que cria backup e verifica fingerprints. Não migrar a memória original durante o dry-run.
3. Após compilar, instalar somente com `scripts/Install-Mod.ps1 -MinecraftDir (Join-Path $env:APPDATA '.minecraft') -World 'ia'`. O script valida os caminhos e o save, cria e verifica o backup antes de substituir arquivos do mod. Esta etapa não foi executada.
4. Para gameplay, usar um mundo Survival separado e descartável, nunca o mundo original `ia`. Não usar cheats, comandos, teleporte, Creative ou jogadores extras.
5. Com ações limitadas às teclas F8, F9 e F10, observar coleta acessível, inacessível, entidade que desaparece e inventário cheio; observar variação e projeto, inclusive após restart; observar Ollama offline e pressão de recursos. Em cada caso registrar evidência correlacionada por sessão, comando e mundo. Só considerar coleta confirmada com UUID correlacionado e aumento verificado do inventário.
6. Interromper com F9/F10 quando necessário e confirmar que parada, desconexão ou restart não geram ação indevida nem evidência sem confirmação. Não publicar diário nesta validação.

## Próxima fase

Validar os itens parciais acima e os cenários reais de instalação, controle, coleta, recuperação e restart. Consciência de sede e temperatura depende de sensores disponíveis; não presumir que essas observações existem. Segurança e industrialização são opcionais e dependem dos resultados dessas experiências.
