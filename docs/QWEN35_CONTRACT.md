# Qwen3.5: contrato cognitivo e validação

Esta correção é restrita ao Mind, provider, scheduler, benchmark e testes. O trabalho local de coleta e sensores da fase 0.4 foi preservado. Novas capacidades físicas ficaram suspensas durante o diagnóstico. Não houve instalação de mods ou gameplay.

## Causa demonstrada

Uma reprodução real com `qwen3.5:4b-q4_K_M`, usando o contrato anterior e somente o contexto sintético existente, terminou em 48,281 s. O JSON era válido, a validação Pydantic passou e o parser rejeitou **uma referência de memória inexistente**. As referências de evidência eram válidas. O contexto não oferecia memórias, mas o schema estático permitia strings arbitrárias em `memory_ids` e nas reconsiderações.

O benchmark escondia essa rejeição em `thought_contract_or_parse_error`. Além disso, contava referências apenas de eventos e só após o parser aceitar a resposta. Assim, zero no relatório anterior não demonstrava ausência de referências inventadas. A resposta da execução histórica de 40,594 s não estava disponível; a reprodução identifica a causa observada nesta investigação, sem atribuir retroativamente conteúdo àquela resposta.

Também foi reproduzida uma divergência de validação: o filtro do provider ignorava referências locais de schema, uniões, constantes e limites, deixando algumas estruturas inválidas chegarem ao Pydantic.

## Correção

- `ThoughtGenerator.schema(context)` deriva um subconjunto do schema Pydantic: exige pelo menos um pensamento e restringe identificadores aos eventos e memórias oferecidos. Sem memórias, exige listas vazias de memórias e reconsiderações. Sem evidências, não oferece proposta. O schema estático e o parser continuam aceitando os formatos legados válidos.
- O prompt distingue explicitamente identificadores de evento e memória e informa os campos obrigatórios da raiz e de cada pensamento. Nenhum evento ou identificador é criado para completar a resposta.
- Um experimento intermediário com `anyOf` na raiz produziu omissão de `version` em 17,859 s. A geração final usa uma única raiz com `required` e `thoughts.minItems=1`. A validação final de conteúdo não vazio permanece no Pydantic.
- O provider valida os construtos usados pelo contrato, inclusive `$ref`, `anyOf`, tipos estritos, valores nulos, enums, constantes e limites. Não consulta referências de schema externas. Pydantic e validação semântica de proveniência continuam obrigatórios.
- Erros públicos distinguem JSON inválido, resposta vazia, schema incompatível, campo ausente, tipo incorreto, validação Pydantic, referências de evento/memória inexistentes, contexto obsoleto e erro interno. Saem apenas categorias, campos conhecidos, contadores e métricas; nunca texto de exceção, input de Pydantic, prompts ou respostas.
- O benchmark preserva métricas mesmo quando a resposta é rejeitada. Usa `failed` para tentativas que falharam e `null` para contagens não medidas. A ausência de uma medição nunca vira zero referências inválidas.
- O scheduler utiliza o mesmo schema contextual e mantém fila limitada, cooldown, rejeição de contexto obsoleto e fallback determinístico. Modelos não recebem autoridade física.

A API oficial recebe o JSON Schema em `format`, com `think=false` e `stream=false`, conforme a [documentação do Ollama](https://docs.ollama.com/capabilities/structured-outputs). O teste HTTP confere o schema efetivamente transmitido contra `ThoughtGenerator.schema(context)`.

## Evidência da execução final

Com Minecraft comprovadamente fechado, foi executado:

```powershell
.\.venv\Scripts\python.exe -m scripts.benchmark_mind --samples 1 --thinking off --timeout 60 --model qwen3.5:4b-q4_K_M
```

| Medida | Resultado |
| --- | --- |
| Status | `completed` |
| JSON / parser | válido / aceito |
| Pensamentos aceitos | 2 |
| Referências de evidência | 2 válidas, 0 inválidas |
| Referências de memória | 0 usadas, 0 inválidas |
| Tempo total da amostra | 20,766 s |
| Tempo de geração informado pelo Ollama | 12,115444 s |
| Tokens gerados / velocidade | 102 / 8,419 tokens/s |
| Tokens de entrada | 475 |
| Carregamento do modelo | 0,0031685 s |
| RAM livre antes / depois | 4.981,24 / 4.791,39 MiB |
| CPU medida no intervalo | 54,51% |
| Memória privada lida / gameplay verificado | não / não |

Schema enviado, SHA-256: `221003af2e127e7db0cb2f0c0367a4a9c5235e59321d31ab51ef06360a40ffbc`.

Parâmetros preservados: contexto 4096, saída máxima 384 tokens, quatro threads, `num_gpu=0`, temperatura 0,2 e timeout de 60 s. Nenhuma configuração privada foi alterada. O modelo já estava carregado na amostra final; uma única amostra não comprova latência de partida fria, estabilidade prolongada ou desempenho durante gameplay.

## Regressões e limites

Os testes cobrem respostas canônicas, eventos e memórias válidos/inventados, campos obrigatórios aninhados, tipos, enums, null, limites, não finitos, estruturas vazias, erros inesperados, privacidade dos diagnósticos, métricas de falhas, contexto expirado, schema transmitido e preservação dos parâmetros. O bloqueio quando Minecraft está aberto ou seu estado é desconhecido permanece testado.

Os testes de HTTP usam fixtures e não são inferência real. Somente a amostra descrita acima comprova geração real e aceitação do parser; ela não comprova experiência subjetiva, aprendizagem no mundo ou ação física. O matcher do provider cobre o vocabulário dos contratos deste projeto; ele não se apresenta como um validador genérico de todo JSON Schema.

Para verificar mudanças futuras, repita o benchmark somente após a confirmação de Minecraft fechado, sem ampliar automaticamente timeout, temperatura, contexto ou orçamento de RAM. Consulte `STATUS.md` para a validação final da suíte e do build.
