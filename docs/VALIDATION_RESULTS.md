# Resultado de validação — 2026-10-31

## Execuções concluídas

- Baseline local inicial: 148 testes Python aprovados e build Fabric aprovado. As 41 alterações staged anteriores foram preservadas no checkpoint `abd8996`.
- Marco de logística/agricultura: 204 testes aprovados e build Fabric aprovado, checkpoint `ac81b4c`.
- Validação final: `.venv/Scripts/python.exe -m unittest discover -s tests -v`: **220 testes aprovados, zero falhas, zero skips**, em 87,826 segundos.
- `mod/gradlew.bat build`: **BUILD SUCCESSFUL**, Java 21, Minecraft 1.21.1 e Yarn 1.21.1+build.3. Checks Java executaram 136 assertions de controle/alimentação/repouso, 389 de geometria e 10 de seleção de ferramentas. Essas 535 assertions não são testes de gameplay.
- `scripts.verify_memory_upgrade --dry-run`: esquema 7, integridade da cópia verificada e **fingerprints das 28 tabelas históricas idênticos**; banco real não migrado. Testes de migração também preservaram intenção de transferência v6 e verificaram backup/idempotência.

## Cadeias exercitadas

| Verificação | Evidência automatizada |
| --- | --- |
| Baú → materiais → projeto | Retirada comprovada nos dois inventários seguida de crafting; retirada de carvão seguida de reinspeção de fornalha |
| Resposta perdida | Intenção persistida antes do comando; reinspeção após reinício distingue estado esperado, intacto e conflito; não cria fato de transferência perdida |
| Agricultura | Dois ciclos sintéticos de colheita, coleta de sementes com aumento de inventário e replantio, começando por preparo com enxada e hidratação observada |
| Estoque alimentar | Excedentes guardados acima das reservas; fome → inspeção → retirada comprovada → comando de alimentação separado |
| Continuidade | 160 ciclos variáveis, três reinícios, noite, fome, perigo, F10/pausas e resposta perdida, conservando materiais e UUIDs de execução |
| Projetos | Dependências persistentes, mudança de seleção por déficit real, suspensão/reinício, cooldown aplicado ao executor, abandono sem recriar o mesmo local e retomada explícita |
| Cognição | Crafting comprovado → memória recuperada → interesse/preferência → interpretação sintética → prioridade diferente em cópias equivalentes do banco → comando permitido |
| Transporte | Nove testes de transporte, incluindo HttpClient Java contra FastAPI real em loopback HTTP/1.1, sem Upgrade, com cancelamento correlacionado e alimentação posterior |

## Limites da evidência

Não houve instalação do mod, execução gráfica, alteração de launcher/autenticação ou ação no save principal. Não existia uma ferramenta de controle do cliente gráfico nesta sessão. A geração textual dos testes é sintética: nenhum provedor LLM foi chamado e nenhum modelo grande foi baixado. MCA, interfaces, crescimento real, navegação física e autonomia de vários dias permanecem pendentes do roteiro [VALIDATION.md](VALIDATION.md).

Projetos hierárquicos acompanham os executores atuais de abrigo e fornalha; não sintetizam qualquer habilidade nova. Reservas de alimentos usam pisos conservadores por quantidade, sem estimar uma dieta nutricional completa. Transferências são unitárias e limitadas a baús simples e stacks padrão. Cursor incerto pode exigir recuperação na interface nativa.

MÍNIMO/Luna foi usado em reconhecimento e documentação; MÉDIO/Sol em controladores, integração e testes; MÁXIMO/Astra em invariantes de armazenamento e revisão de integridade. Depois do limite de uso dos subagentes, o trabalho continuou com o coordenador disponível, sem troca de modelo alegada. `.codex/config.toml` estava ausente; os três agentes estavam definidos em `.codex/agents/`.
