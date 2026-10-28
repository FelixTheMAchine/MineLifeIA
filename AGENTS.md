# MineLife AI

Trabalhe neste diretório. Preserve código existente e alterações do usuário.
Java 21, Minecraft 1.21.1, Yarn 1.21.1+build.3, Fabric; Python 3.11.
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
