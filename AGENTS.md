# MineLife AI

Trabalhe neste diretório. Preserve código existente e alterações do usuário.
Java 21, Minecraft 1.21.1, Yarn 1.21.1+build.3, Fabric; Python 3.11. Mod 0.2 usa
bridge HTTP/1.1 em loopback; não reintroduza Upgrade/WebSocket sem mudar cliente,
servidor e testes de contrato em conjunto.
Não altere autenticação, launcher ou saves diretamente. Antes de instalar arquivos
do mod ou testar ações reais, feche Minecraft e execute scripts/Install-Mod.ps1,
que verifica caminhos e cria backup do mundo e dos arquivos substituídos.
Não execute testes reais sem backup. Não declare execução no jogo a partir de mocks.
Use APIs reais e compile. Não use comandos, teleporte, Creative ou jogadores extras.
Resultados positivos exigem evidências correlacionadas com sessão/comando/mundo.
Diários não podem afirmar coleta sem aumento verificado do inventário.
Publicação automática fica desativada até teste e aprovação. O usuário autorizou
o commit inicial em main de FelixTheMAchine/MineLifeIA e tornou esse repositório
público durante a sessão. Não crie outro
repositório. Publique diários somente em journals/ nesse repositório oficial.
Diários exigem teste real e autorização específica; exposição pública exige também
journal_allow_public=true na configuração local. Nunca publique memórias privadas.
Não versionar data/, tokens, saves, config/local.json ou caminhos pessoais.
Execute .venv/Scripts/python.exe -m unittest discover -s tests -v e mod/gradlew.bat build.
Migrações devem criar backup, ser aditivas e comparar fingerprints de memória real.
Reflexões e sugestões LLM são narrativas, não fatos; publique diário somente após
validar a proveniência de cada frase. LLM nunca emite comandos físicos.

## POLITICA PERMANENTE: ROTEAMENTO INTELIGENTE DE TOKENS

Esta regra vale para TODAS as sessoes e prompts do MineLife AI.

1. Antes de iniciar cada subtarefa, classifique a dificuldade REAL como MINIMA, MEDIA ou MAXIMA. Classifique pelo risco e pela necessidade de raciocinio, nao pelo tamanho do arquivo.
2. MINIMA = delegar a `minelife_minimo` (GPT-6 Luna, low): localizar arquivos, buscar simbolos, ler logs pontuais, atualizar texto/README, relatorios, pequenas edicoes mecanicas e tarefas repetitivas.
3. MEDIA = delegar a `minelife_medio` (GPT-6.1 Sol, medium): implementacoes circunscritas, testes, correcoes localizadas, APIs conhecidas e integracao moderada.
4. MAXIMA = delegar a `minelife_maximo` (GPT-6 Astra, max): arquitetura de memoria e cognicao, escalonamento de objetivos, bugs intermitentes multicamadas, seguranca ou integridade criticas, refatoracoes de alto risco e desenho de protocolos.
5. Use a ferramenta de terminal diretamente para executar compilacao, formatacao, testes, Git status e comandos deterministas. Nao use o modelo MAX apenas para executa-los; escale somente se o diagnostico for genuinamente complexo.
6. O coordenador principal deve ficar no nivel MEDIO por padrao. Reserve o Astra MAX para subtarefas dificeis de escopo delimitado. Quando a delegacao nao estiver disponivel, nao afirme que trocou de modelo: informe o impedimento e continue com o modelo disponivel.
7. Nao crie um subagente para tarefas triviais que podem ser feitas com uma unica chamada de ferramenta; o overhead de delegacao tambem consome tokens.
8. Nao execute varios agentes escrevendo nos mesmos arquivos; delegue preferencialmente analises independentes, sem conflitos.
9. Entregue apenas resumos curtos dos subagentes, citando arquivos, resultados e problemas. Evite grandes dumps de logs e recarregar arquivos inteiros.
10. Escale de MINIMA para MEDIA e de MEDIA para MAXIMA somente quando aparecer complexidade comprovada, bloqueio real ou risco sistemico. Rebaixe novamente apos resolver a parte dificil.
11. Priorizacao de custo NUNCA pode suprimir validacao de seguranca, integridade, testes obrigatorios ou preservacao de saves, memoria, tokens e dados privados.
12. Ao final, informe brevemente quais niveis foram usados e as tarefas concluidas, sem inventar medidas de tokens economizados.