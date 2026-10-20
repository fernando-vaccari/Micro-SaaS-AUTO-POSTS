# Validação realizada em 20/10/2026

## Resultado local

- `./scripts/install.sh` executado e repetido sem alterar o lockfile; 29 dependências consistentes.
- `.venv/bin/python -m pytest -q`: **66 testes aprovados**. Há um aviso de depreciação do TestClient de Starlette para httpx, sem falha de teste.
- `node --check autoposts/static/app.js` e `git diff --check`: aprovados.
- Inicialização nativa por `scripts/start.sh`, inclusive a partir de outro diretório; `/health` confirmou banco e FFmpeg.
- Fluxo HTTP real: cadastro, campanha com pauta autoral, prévia, geração de roteiro, renderização e download privado. MP4 de 24 segundos, H.264/AAC, 1080×1920, validado com ffprobe. A prévia não foi agendada e o acesso sem login ao vídeo privado foi negado.
- Teste integrado `tests/test_pipeline.py`: uma campanha ativa gerou conteúdo, renderizou MP4 real e chegou à publicação sem chamada manual a `/render` ou `/schedule`. Somente a API externa do Instagram foi simulada; o container foi persistido antes do passo de publicação e não houve repetição.
- Chromium: cadastro, login, criação/edição de campanha, consentimento de ativação, erro visível de configuração ausente, prévia e criação manual; navegação desktop/mobile e reprodução nativa do vídeo. Sem erros JavaScript ou overflow horizontal em 390 px.
- Docker: imagem construída com TLS verificado, usando opcionalmente a CA confiável da nuvem via segredo BuildKit. Container sem privilégios (`uid=10001`), healthcheck saudável, SQLite e FFmpeg operacionais. Repetido no container o fluxo de cadastro → campanha → geração → MP4 real → download privado. O container de teste foi encerrado após a validação.

Capturas usam uma conta e campanhas de teste isoladas: [painel desktop](screenshots/dashboard.png) e [campanhas no celular](screenshots/mobile.png). Não são dados de clientes nem prova de publicações realizadas.

## Integrações externas

OAuth, renovação de token, etapas de publicação e cobrança foram validados com respostas simuladas dos provedores. Não foram usados tokens de Instagram, chave de IA ou conta Stripe reais. Nenhum Reel foi publicado e nenhuma cobrança foi efetuada.

Para validar a operação externa faltam URL pública HTTPS, credenciais IA/Meta e conta profissional autorizada. Uso por contas de clientes também depende das permissões/revisões exigidas pela Meta. Stripe permanece opcional e precisa primeiro de teste completo com a conta do operador.

## Persistência e publicação

O rascunho do ambiente salva `install_script`, `start_skill`, requisitos de configuração e domínios de rede. Essa gravação não publica o ambiente e não implanta o SaaS na Internet. A restauração em uma nova tarefa ainda não foi validada. Consulte [README](../README.md), [operação](OPERATIONS.md) e [lançamento](LAUNCH_CHECKLIST.md) antes de oferecer o serviço publicamente.
