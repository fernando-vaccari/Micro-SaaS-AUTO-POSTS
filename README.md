# AUTOPOSTS

Micro-SaaS para transformar uma campanha em vídeos verticais e publicações no Instagram. O cliente configura o nicho, os assuntos, o estilo, os horários e a conta profissional. Ao ativar a campanha, autoriza a geração e a publicação sem aprovar cada vídeo.

O aplicativo contém painel em português, cadastro e login, campanhas, geração de roteiros com IA ou textos fornecidos pelo cliente, renderização real de MP4 com FFmpeg, fila persistente, integração Instagram Login e cobrança opcional com Stripe. A instalação não conecta contas, não efetua cobranças e não publica conteúdo.

## Executar em desenvolvimento

Requisitos: Linux, Python 3.12 ou superior, FFmpeg/ffprobe com encoder `libx264` e fontes DejaVu. Em Debian/Ubuntu, os pacotes de sistema são `ffmpeg`, `fonts-dejavu-core` e `tzdata`. `uv` é recomendado; o instalador também aceita `venv`/`pip`.

Use o checkout existente. Cada tarefa na nuvem já é isolada; não é necessário criar outro clone ou worktree.

```bash
cd /workspace/Micro-SaaS-AUTO-POSTS
./scripts/install.sh
cp -n .env.example .env
./scripts/start.sh
```

O servidor usa a porta 8000. Faça a verificação local, sem precisar publicar uma prévia:

```bash
curl --fail http://127.0.0.1:8000/health
.venv/bin/python -m pytest -q
```

O primeiro cadastro cria uma conta vazia, sem campanhas ou postagens fictícias. Em desenvolvimento, uma chave local é criada em `.data/.app-secret` quando `APP_SECRET` está vazio. Preserve essa chave e o diretório `.data` entre reinicializações.

## Fluxo automático

1. Cadastre a conta e crie uma campanha desativada.
2. Escolha **textos fornecidos** para trabalhar sem serviço de IA, ou **IA** para gerar roteiros a partir do nicho e dos assuntos com sua chave `AI_API_KEY`.
3. Gere uma prévia para conferir o vídeo. A prévia não é publicada, mesmo em uma campanha ativa.
4. Configure uma URL HTTPS pública, o aplicativo Meta e conecte o Instagram profissional pelo próprio painel.
5. Defina os horários e o fuso e ative a campanha. A partir dessa autorização, os novos vídeos seguem para publicação automaticamente.

Pausar interrompe novos trabalhos da campanha e retira suas publicações que ainda aguardam na fila. Uma requisição de publicação que já chegou ao Instagram pode terminar mesmo após a pausa. Confira o estado das publicações no painel.

Os vídeos desta versão são apresentações verticais com texto, fundos e imagens opcionais, com faixa de áudio silenciosa para compatibilidade. O fluxo não inclui narração, pesquisa de fatos, filmagens geradas ou licenciamento de música. O uso de IA não substitui a responsabilidade do cliente pelo conteúdo e pelos direitos sobre materiais enviados.

## Configuração

As variáveis são lidas do processo ou do arquivo local `.env`; valores do processo têm prioridade. Nunca versione arquivos com credenciais.

| Variável | Uso |
| --- | --- |
| `APP_ENV` | `development` ou `production`. |
| `APP_BASE_URL` | Origem pública do aplicativo. HTTPS público é obrigatório para publicar no Instagram e para produção. |
| `APP_SECRET` | Segredo estável com pelo menos 32 caracteres; obrigatório em produção. Protege sessões e tokens armazenados. |
| `DATA_DIR` | Dados persistentes: SQLite, uploads, vídeos e chave local de desenvolvimento. Padrão `.data`. |
| `INSTAGRAM_APP_ID` | Identificador do aplicativo Meta com Instagram Login. |
| `INSTAGRAM_APP_SECRET` | Segredo do aplicativo Meta. |
| `INSTAGRAM_REDIRECT_URI` | Callback exato cadastrado na Meta: origem pública seguida de `/api/integrations/instagram/callback`. |
| `INSTAGRAM_GRAPH_VERSION` | Versão da Graph API; padrão `v25.0`. |
| `AI_API_KEY` | Chave da API OpenAI para campanhas no modo IA. Não é exigida no modo de textos fornecidos. |
| `AI_MODEL` | Modelo de texto; padrão `gpt-4.1-mini`. Custos e disponibilidade dependem da conta do provedor. |
| `STRIPE_SECRET_KEY` | Chave Stripe; opcional enquanto não houver cobrança. Comece em modo de teste. |
| `STRIPE_WEBHOOK_SECRET` | Segredo de assinatura do webhook Stripe. |
| `STRIPE_PRICE_ID` | Preço recorrente do plano Pro configurado na mesma conta Stripe. |

O limite inicial é de 3 vídeos por mês no plano gratuito e 100 no Pro. A criação de prévias também utiliza a cota. A confirmação de pagamento depende do webhook verificado; o retorno do navegador após um checkout não concede o plano.

## Executar com Docker

```bash
cp -n .env.example .env
# Edite .env com as configurações do ambiente.
docker compose up --build -d
docker compose ps
docker compose logs --tail=100 app
```

O serviço fica vinculado ao loopback do host por padrão e usa um volume nomeado para os dados. Configure um proxy reverso com HTTPS para expor o aplicativo em produção. `AUTOPOSTS_BIND_IP` e `AUTOPOSTS_PORT` alteram o vínculo no host; mudar o vínculo não configura domínio, TLS ou firewall.

O servidor e os agendadores rodam em uma única instância. Não use múltiplos workers, réplicas ou volumes locais independentes para a mesma fila.

## Antes de oferecer o serviço a clientes

Veja [operação e publicação](docs/OPERATIONS.md) para configurar Meta, Stripe, HTTPS, persistência, backup e recuperação. O projeto não cria recursos de hospedagem nem publica uma implantação automaticamente.

Há cadastro e login com senha. Recuperação de senha, confirmação de e-mail e envio de mensagens transacionais ainda não fazem parte desta versão. Essas capacidades, termos de uso, política de privacidade e uma política de retenção precisam ser preparados antes de abrir um serviço público a clientes.
