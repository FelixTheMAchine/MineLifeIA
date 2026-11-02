# Mente local opcional (Ollama)

A camada de mente é opcional e fica desativada por padrão (`llm.provider: "none"`). Ela produz narrativas e propostas tipadas, sem autoridade para emitir comandos físicos. O backend e o agente continuam operando sem provedor.

## Ativação

1. Instale Ollama pelo [site oficial](https://ollama.com/download). Esta documentação não instala nem baixa componentes.
2. Use a configuração local criada pelo fluxo existente (`scripts/Setup.ps1` na preparação inicial). Copie somente a seção `llm` de `config/example.json` para `config/local.json`: preserve o token e todas as demais opções. O exemplo não contém credenciais e não substitui o arquivo local completo.
3. Configure `llm.provider` como `ollama` e `llm.model` como `qwen3:1.7b`. Para baixar explicitamente esse modelo depois de instalar Ollama, execute `ollama pull qwen3:1.7b` no terminal. O projeto não baixa modelos automaticamente.
4. O endereço padrão é `http://127.0.0.1:11434`. Em geral o serviço local já inicia com Ollama; se não estiver ativo, abra outro terminal e execute `ollama serve` manualmente. Scripts de inicialização do MineLife não reiniciam nem gerenciam serviços Ollama de terceiros.

A configuração de referência usa CPU (`num_gpu: 0`, `num_thread: 2`). Não se presume suporte ou uso de GPU, inclusive em placas RX 580. Janela de contexto (`num_ctx`), orçamento de contexto (`context_tokens`), temperatura, limite de saída, timeout, intervalo/frequência, habilitação de raciocínio profundo, cooldowns e limites de RAM/CPU são controlados pelos valores de configuração e guardas no código. Comece com os padrões e ajuste somente após observar o consumo local. `deep_thinking` é opt-in e vem desativado; cooldowns limitam chamadas profundas e falhas.

Para parar de usar o provedor, altere apenas `llm.provider` para `none` em `config/local.json`. Essa é também a configuração padrão determinística, sem chamadas ao modelo. Não remova o token nem substitua o arquivo.

As opções são lidas na inicialização do backend. Depois de editar, encerre com Ctrl+C somente o backend que você iniciou e execute `scripts/Start-Backend.ps1`. Abra Minecraft pelo procedimento existente. Para instalar um JAR novo ou testar ações reais, feche Minecraft e execute antes `scripts/Install-Mod.ps1`, que verifica caminhos e cria os backups exigidos; não altere o save diretamente. Nenhum script do Mind inicia ou encerra Minecraft.

| Ajuste | Padrão | Efeito |
|---|---:|---|
| `num_ctx` / `context_tokens` | 4096 / 1800 | Janela do modelo / orçamento estimado por bytes UTF-8, reservando espaço para schema, sistema e resposta; não é contagem exata de tokenizer. |
| `max_output_tokens` / `temperature` | 384 / 0.2 | Limite de geração e variação da saída. |
| `interval_seconds` / `calls_per_hour` | 60 / 12 | Frequência e teto de tentativas, incluindo retentativas. |
| `timeout_seconds` / `keep_alive` | 30 / `2m` | Prazo total por requisição e retenção do modelo no servidor. |
| `queue_size` / `job_ttl_seconds` | 2 / 120 | Fila pendente e validade de trabalho. |
| `max_retries` / `failure_cooldown_seconds` | 1 / 120 | Retentativa limitada de indisponibilidade/erro do servidor; timeout não é repetido imediatamente. |
| `deep_thinking` / `deep_cooldown_seconds` | false / 600 | Reflexão ampliada optativa após marcos retidos, somente se `/api/show` anunciar suporte. |
| `min_free_ram_mb` / `max_cpu_percent` | 2048 / 85 | Adia a inferência ao observar pressão de recursos do sistema. |
| `disable_on_budget_overrun` | false | Quando true, suspende novas inferências até reiniciar o backend se exceder recursos ou duração. |

Os guardas de RAM/CPU atuam antes das chamadas; não garantem um FPS mínimo nem interrompem trabalho remoto já iniciado. A duração máxima é limitada pelo timeout. O Observer mostra latência retornada pela API, contadores, fila, estado do fallback e leituras de recursos disponíveis. Não há medição de FPS implementada.

## Limites e evidências

As interfaces existentes são `LocalModelProvider` (`agent/local_model.py`), `CognitiveScheduler` (`agent/cognitive_scheduler.py`) e `ThoughtGenerator`, `ContextBuilder`, `IntentionValidator`, `ReflectionManager` e `MemoryRetriever` (`agent/mind.py`), com os modelos tipados `Thought`, `Proposal`, `Reconsideration` e `MindOutput`. A saída segue schema estrito; pensamentos, hipóteses e reflexões são narrativas não verificadas. Uma intenção é limitada e vinculada ao escopo vigente e às evidências fornecidas; o executor conserva a autoridade física. Não há cadeia de pensamento privada nem emissão de comandos físicos.

A interface de avaliação cognitiva é `ReflectionManager.record_selection/record_outcome`, persistida em `MindEvaluations`: relaciona intenção, objetivo, experimento, comando e evento. Falha ou cancelamento registra resultado insuficiente, sem transformar uma narrativa em hipótese refutada. O aprendizado gradual existente em `IdentityEngine` continua dependendo de experiências verificadas; o modelo não escreve pesos ou traços. Revisões narrativas ficam em `MindThoughts`, preservando as memórias factuais originais. O cache de projeções derivadas tem 32 entradas e revalida fingerprints; não há embeddings nem outro modelo.

O contexto carrega manifestos de evidência e fingerprints de eventos e memórias de origem. Saídas de um escopo obsoleto são descartadas; ao mudar mundo, dimensão, sessão ou época de controle, a fila pendente é limpa. Uma chamada HTTP ativa pode continuar ocupando a única vaga até retornar: cancelamento local não confirma cancelamento remoto no Ollama. Não trate narrativa ou sugestão como fato, resultado do jogo ou evidência para diário.

## Diagnóstico e benchmark sintético

A ferramenta de diagnóstico é somente leitura: consulta configuração existente, estado de processos, bridge, CLI/API do Ollama e metadados locais, sem inicializar o backend nem executar migrações. Ela não altera configuração ou memória:

```powershell
.venv/Scripts/python.exe -m scripts.mind_diagnostic
```

O benchmark é uma operação explícita, usa apenas contexto sintético e não lê memória privada nem saves. O padrão é uma amostra, sem thinking. Opções reais: `--samples 1|2|3`, `--thinking off|on|both`, `--timeout SEGUNDOS` (até 60) e `--model NOME`:

```powershell
.venv/Scripts/python.exe -m scripts.benchmark_mind
.venv/Scripts/python.exe -m scripts.benchmark_mind --samples 1 --thinking both
```

Ele recusa prosseguir se detectar Minecraft ativo ou não conseguir confirmar que está parado. Mesmo um benchmark concluído mede somente resposta ao cenário sintético; não prova inferência real no jogo nem gameplay.

O backend pode criar backup SQLite antes de migrações aditivas de memória. A verificação de uma migração futura deve preservar o banco original, comparar fingerprints e cumprir o procedimento de backup; não execute migração apenas para diagnosticar Ollama. Para validação exigida pelo projeto:

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
mod/gradlew.bat -p mod build
```

Referências oficiais: [download do Ollama](https://ollama.com/download), [API de chat](https://docs.ollama.com/api/chat), [listar modelos](https://docs.ollama.com/api/tags), [modelos carregados](https://docs.ollama.com/api/ps) e [capacidade de thinking](https://docs.ollama.com/capabilities/thinking).
