# AUTO POSTS

Micro SaaS em português para criar imagens e Reels, organizar biblioteca e executar campanhas com publicação oficial no Instagram. Esta entrega continua o código Python existente, conforme o pedido mais recente. A migração parcial para Workers foi preservada em `archive/cloudflare-wip-20261021`; a versão Python anterior está em `archive/python-mvp`.

**Situação:** aplicação testada localmente; integrações externas ainda precisam de validação. O último teste real B2 rejeitou o Key ID. Não é uma declaração de produto pronto para venda.

## Arquitetura

FastAPI serve API e interface existente. Um SQLite persistente é a fonte única para clientes, assinaturas, campanhas, consumo e fila. Um worker no mesmo serviço processa tarefas com reserva atômica, tentativas limitadas e lease. FFmpeg gera MP4 H.264/AAC 1080×1920; Pillow gera JPEG 1080×1350. Em produção, mídia privada fica no Backblaze B2, com confirmação por HEAD e URLs temporárias.

O servidor deve continuar ligado. Não há dependência do computador do cliente. **Este backend Python/FFmpeg não é executável no Cloudflare Workers Free**; Cloudflare pode fornecer DNS e proxy HTTPS. Docker e Caddy estão preparados para um host persistente. Não há dois bancos sincronizados nem usuário global compartilhado.

## Executar localmente

Requer Python 3.12+, FFmpeg com libx264, ffprobe, fontes DejaVu e tzdata. No Debian/Ubuntu, instale `ffmpeg fonts-dejavu-core tzdata`.

```bash
cp .env.example .env
./scripts/install.sh
./scripts/start.sh
```

O modo development permite experimentar localmente com 3 vídeos e 2 imagens. Não cria assinatura paga nem publica sem conta e autorização. Não utilize esse modo em um serviço público comercial.

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q autoposts scripts tests
node --check autoposts/static/app.js
.venv/bin/python -m scripts.generate_demo
```

Não existe build Node obrigatório: FastAPI serve os arquivos em `autoposts/static`. Não use `wrangler deploy` para esta arquitetura.

## Funcionalidades

- Cadastro, sessões, CSRF, senhas scrypt, recuperação por SMTP, verificação de e-mail, alteração de senha e exclusão com limpeza confirmada.
- Imagens e vídeos reais com cenas, cores, CTA, marca, logo, fundo e movimento opcional. Vídeos de 6–60 segundos; campanhas usam 45 segundos por padrão. Templates sem IA paga; roteiro por IA é opcional.
- Biblioteca privada, download, fila persistente, retry com backoff e prevenção de conclusão sem upload confirmado.
- Campanhas diárias ou com dias da semana, horário/fuso, prévia, pausa, retomada, agendamento e publicação manual confirmada.
- OAuth oficial Instagram, tokens criptografados, renovação e processamento de imagens/Reels. Ativar campanha autoriza publicações automáticas futuras; prévia não publica.
- Quatro assinaturas, checkout/portal, webhooks assinados, histórico, limites separados para imagens/vídeos e teste Starter.
- Limpeza de mídia após 10 dias sem atividade, configurável; preserva pendências e materiais em uso por campanhas ativas.

| Plano | Mensalidade | Vídeos | Imagens |
|---|---:|---:|---:|
| Starter | R$ 29,99 | 10 | 5 |
| Pro | R$ 69,99 | 20 | 10 |
| Business | R$ 109,99 | 50 | 25 |
| Premium | R$ 159,99 | 80 | 40 |

Starter: sete dias de teste, e-mail confirmado, cartão no Stripe e controle de reutilização por hash do e-mail. Isso reduz abuso, sem garantir identificação única de uma pessoa. Preços e limites são variáveis de ambiente. Criar um post reserva um crédito; regenerar um resultado já gerado consome outro. Excluir posts não restitui créditos. Falhas temporárias reutilizam o arquivo renderizado. O ciclo pago acompanha o período confirmado pelo Stripe; sandbox usa mês UTC.

## Configuração e deploy

Todas as opções estão em [.env.example](.env.example), sem necessidade de editar fontes. As chaves do GitHub Actions não são automaticamente disponibilizadas ao servidor: configure-as também no gerenciador seguro de variáveis do host.

Consulte [operações e credenciais](docs/OPERATIONS.md), [arquitetura e auditoria](docs/ARCHITECTURE.md), [validação](docs/VALIDATION.md) e [checklist de lançamento](docs/LAUNCH_CHECKLIST.md).

Para HTTPS público: configure um host persistente, DNS do domínio, variáveis de produção/B2/SMTP/Stripe/Meta e execute `docker compose --profile public up -d --build`. O perfil padrão expõe somente loopback; o perfil public adiciona Caddy nas portas 80/443. Instruções detalhadas e backup estão no guia de operações.

GitHub Actions valida testes e gera um MP4 de demonstração. O workflow B2 é manual; escolha a branch desta entrega. O renderizador remoto também é manual, opcional, e aceita apenas tarefas autenticadas do servidor. Nada publica na produção automaticamente ao fazer push.

## Custos e limites

Python, FastAPI, FFmpeg e Pillow são gratuitos. Armazenamento, tráfego, CPU de renderização, domínio, SMTP e tarifas Stripe podem gerar custos. B2 e Cloudflare têm cotas e políticas próprias, que devem ser conferidas antes de operar. GitHub Actions não é uma fazenda de renderização comercial ilimitada. Para testes gratuitos, use a máquina local ou este ambiente; para produção confiável, use um host Docker com disco persistente, backup e capacidade suficiente (por exemplo, VPS econômica). Nenhum serviço pago foi provisionado nem cobrança real executada nesta entrega.
