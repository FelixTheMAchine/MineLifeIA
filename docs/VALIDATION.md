# Validação reproduzível

Compilar e passar fixtures não comprova gameplay. Nenhum teste deste documento foi executado no Minecraft nesta revisão. O modo sem LLM continua sendo a configuração de base.

## Verificação local

No diretório do projeto, com Java 21 e Python 3.11:

```powershell
Push-Location mod
.\gradlew.bat build
Pop-Location
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m scripts.verify_memory_upgrade --dry-run
.\.venv\Scripts\python.exe scripts/audit_commit.py
git diff --check
git diff --cached --check
```

Compile antes da suíte Python para que os contratos HTTP Java sejam executados. Esses contratos usam FastAPI real em loopback e observações sintéticas, sem Upgrade. A auditoria examina exatamente os blobs staged; não publica arquivos. O dry-run migra uma cópia temporária do banco real e compara fingerprints; não migra a origem.

`test_long_life.py` varia 160 ciclos de observações: recursos, fome, noite, pausas, resposta perdida e três reinícios. O adaptador sintético conserva inventários e executa cada UUID uma vez. `test_farm_cycle.py` cobre dois ciclos de colheita, coleta comprovada e replantio. `test_cognitive_chain.py` compara duas cópias do mesmo estado para demonstrar a influência de uma interpretação sintética sobre um comando permitido. Nenhum deles demonstra crescimento real ou uma chamada a um modelo externo.

## Preparar gameplay isolado

1. Use uma instância descartável separada do perfil principal, já preparada com Fabric 1.21.1, Fabric API e MCA Reborn 7.7.19. Não modifique autenticação ou launcher. Pelo menu normal, crie um mundo Survival chamado `minelife-validation`; não use comandos, Creative, teleporte ou outro jogador.
2. Feche o Minecraft normalmente. Não encerre processos do usuário à força. Pare somente o daemon de compilação do projeto com `mod/gradlew.bat --stop`, caso necessário para o instalador.
3. Antes de substituir arquivos do mod ou testar ações, execute o instalador existente para essa instância e esse mundo: `scripts/Install-Mod.ps1 -MinecraftDir '<instancia-descartavel>' -World 'minelife-validation'`. Ele verifica caminhos, copia o mundo, compara hashes e preserva arquivos substituídos. Interrompa se qualquer verificação falhar. Nunca selecione o save `ia`.
4. Inicie o backend pelo script existente, confirme saúde e features `storage-v1`/`agriculture-v1`, abra o mundo descartável e autorize localmente por F8. Não exponha porta, configuração, token, banco ou diários. Publicação automática permanece desligada.

## Evidência necessária por cenário

Registre localmente mundo hash, dimensão, sessão, sequência, UUID de comando, resultado e evidência do servidor. Uma captura de tela ou abertura de GUI, isoladamente, não confirma uma ação.

| Cenário | Condição para aceitar o resultado |
| --- | --- |
| Baú fabricado e colocado | Receita/CRAFTED, ingredientes consumidos, bloco presente, USED e consumo de um baú |
| Depositar/retirar | Baseline compatível, mesma GUI no servidor, origem -1, destino +1, demais slots iguais, cursor vazio |
| F10 antes/durante/depois da transferência | Controles liberados; nenhuma repetição cega; intenção preservada; reinspeção dos dois inventários. GUI incerta pode permanecer aberta para evitar descarte de cursor |
| Resposta perdida/reinício | Nova sessão/inspeção, reconciliação expected/before/conflito; nenhuma falsa autoria para resultado sem confirmação |
| Material para projeto | Retirada comprovada, receita ou etapa do projeto emitida em seguida, sem coletar novamente o recurso já disponível |
| Agricultura | Enxada comum real, água observada, solo arado, hidratação medida, semente consumida, maturidade após espera real, remoção e coleta distintas, reserva e replantio |
| Fornalha em sequência | Carga e retirada próprias; calor residual medido suficiente; interrupção por necessidade e reinspeção posterior |
| Abrigo/rota | Inspeção completa correlacionada com projeto/dimensão, chegadas confirmadas, desvios somente por fronteiras carregadas observadas |
| Fome/F8/F9/F10/desconexão | Nenhum comando posterior a parada; cancelamento reconhecido antes da refeição; retomada somente com autorização local aplicável |
| MCA | Ausência de conflitos em runtime; nenhuma alegação de interação social sem executor e evidência próprios |

Se houver cursor incerto, não feche a GUI para tentar forçar recuperação. Preserve a evidência e resolva a interface nativa antes de rearmar o agente. Não altere inventários no save. Autossuficiência permanece pendente até demonstrar no jogo uma produção renovável e vida contínua com essas invariantes.
