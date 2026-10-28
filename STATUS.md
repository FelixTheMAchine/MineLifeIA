# Status — 2026-10-28

## Recuperação e ambiente

A pasta correta do projeto foi confirmada por Get-Location. Na primeira inspeção
ela estava vazia e não continha Git, código ou instruções anteriores. Foi localizado
um backup prévio de ia fora do projeto, sem código recuperável. Nenhum save foi
alterado durante o desenvolvimento e testes automatizados.

Confirmados: Temurin JDK 21.0.12.1, Python 3.11.9, Git 2.56.0. Minecraft 1.21.1,
Loader 0.20.1, Fabric API 0.116.17+1.21.1 e MCA 7.7.19+1.21.1 foram identificados
no diretório real pelos JARs e log. GitHub CLI não está instalado.

## Implementado

- Mod cliente: observação de árvores, câmera, navegação local, mineração nativa,
  coleta, HUD, F8/F9/F10, liberação de teclas e interrupção por desconexão/perigo.
- Ponte HTTP local autenticada, sessão/mundo/IDs, deduplicação, prazos e reconexão.
- Confirmação somente por leituras do servidor integrado, incluindo estatística
  de mineração e inventário. Não há edição direta de mundo/save.
- SQLite persistente; perguntas, hipóteses, comandos, experimentos e conhecimento.
- Diário em primeira pessoa baseado em eventos; reflexões imediatas, fechamento
  de dias anteriores observados e exportação imutável em journals/ por mundo.
- Publicador restrito ao repositório oficial, dry-run sem rede/Git, fila offline,
  ordem por mundo/dia, comparação imutável e bloqueio de conteúdo sensível.
- Painel local, scripts de execução, build, teste, instalação com backup e auditoria.

## Verificado nesta entrega

- Compilação Java/Fabric bem-sucedida com Loom 1.8.13 e Gradle 8.10.2/JDK 21.
- 17 testes automatizados Python passaram, com banco/diários temporários isolados, incluindo
  transporte HTTP por socket loopback real (payloads sintéticos, sem Minecraft).
- `pip check`: sem dependências quebradas.
- Backend inicializado em 127.0.0.1:8765, health e estado autenticado consultados;
  nenhuma sessão de Minecraft nem entradas reais presentes nesse momento.
- Gradle Wrapper com checksum SHA-256 conferido contra a distribuição oficial.
- Dry-run de produção: zero entradas, zero arquivos a publicar; nenhuma experiência
  real foi inventada para preencher o diário.
- Repositório remoto oficial inicialmente privado, depois tornado público pelo
  proprietário e novamente conferido. A conta conectada possui acesso de escrita.
  Não havia branches nem histórico inicial.
- 35 arquivos de código/documentação publicados em main no commit `f599dc9`,
  precedido por `5af8cbf` com as exclusões de arquivos privados. A árvore Git
  remota foi comparada ao index auditado, e main local passou a acompanhar origin/main.
- JAR instalado na pasta mods identificada. Hash do instalado igual ao build.
  Token da configuração do mod conferido contra o backend, sem expor seu valor.
- Backup completo do mundo ia criado por Install-Mod.ps1 antes da instalação,
  com comparação SHA-256 de cada arquivo. Backup fora do repositório, na pasta
  MineLifeAI-backups, execução `install-20261028-153129-275`. O save original não
  foi editado. Processos de teste/compilação foram encerrados ao finalizar.
- Auditoria dos arquivos do commit e `git diff --cached --check` concluídos;
  banco, configurações, logs, caches, saves e diários locais não publicados.

## Pendências e limites

- **Teste no Minecraft não executado.** Compilação e fixtures não validam física,
  input real, compatibilidade em execução com MCA ou sucesso da primeira árvore.
- Navegação é limitada a terreno local com piso seguro; não explora indefinidamente,
  não atravessa água, não constrói passagem. Falhas de alvo ficam registradas.
- Após uma descoberta confirmada, o MVP conserva a pergunta e aguarda novas
  habilidades. Sobrevivência completa, LLM e evolução da personalidade não existem.
- Diário real depende de eventos reais. Dia atual só é finalizado quando um dia
  posterior for observado. Publicação automática permanece desativada.
- Git local sem credenciais HTTPS disponíveis; GitHub CLI ausente. Publicação
  inicial usa o conector autenticado. Futuro envio pelo script requer autenticar
  GitHub CLI, validar diário real e autorizar a configuração local.

## Próximas tarefas

Executar o checklist real do README com backup, coletar evidências de uma árvore,
verificar persistência após reinício, observar uma virada do dia, revisar o Markdown
e validar dry-run real antes de habilitar qualquer publicação do diário.
