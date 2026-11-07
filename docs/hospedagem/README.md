# Onde hospedar: Cloudflare R2 e processamento CPU

O AUTO POSTS tem três partes:

| Parte | Onde funciona |
|---|---|
| Página de apresentação/domínio | Frontend já incluído no SaaS; Cloudflare DNS/proxy |
| Fotos, imagens geradas, Reels e amostras cifradas | Cloudflare R2 privado |
| Contas, SQLite, agenda, FFmpeg e Kokoro CPU | Host que execute Python/Docker com disco persistente |

Cloudflare Workers Free e R2 não executam esse conjunto Python/FFmpeg/ONNX. Não há um `wrangler deploy` que transforme este backend em serviço Workers. Não foi contratado nenhum host pago nesta entrega.

## Domínio e HTTPS

A página de apresentação, o login, o estúdio e a API são servidos pelo próprio app, no mesmo endereço HTTPS. Configure o domínio/subdomínio no host CPU e no Cloudflare DNS; mantenha Full (strict) ao usar proxy. Não é necessário outro construtor de sites.

## Opções gratuitas para testar

- Este ambiente ou computador CPU: nenhum gateway de IA pago; precisa permanecer ligado para cumprir agenda.
- Hugging Face Spaces CPU básico: pode servir uma demo Docker se os recursos/termos vigentes permitirem. Confira https://huggingface.co/docs/hub/spaces-overview. Armazenamento local gratuito pode ser efêmero e a aplicação pode dormir; isso não atende a uma promessa de disponibilidade comercial, banco persistente ou horário garantido. Não recomendado como única cópia de clientes pagantes/assinaturas.
- Ofertas always-free de provedores com VM e disco persistente, quando disponíveis: exigem cadastro/elegibilidade/capacidade e podem pedir cartão. Não foram provisionadas nem prometidas vagas. O modelo CPU não exige GPU.

Não há garantia de uma hospedagem gratuita permanente que entregue disponibilidade, persistência e recursos suficientes para um SaaS comercial. Para venda com previsibilidade, use um host persistente adequado; se tiver custo, o valor depende do fornecedor. Kokoro ONNX testado usou cerca de 565 MB de pico no processo; some API, FFmpeg, sistema e cache. Um plano de 512 MB não é suficiente para esse conjunto.

## Docker

```bash
./scripts/install.sh
.venv/bin/python -m scripts.configure_editions
# Preencha .env e credenciais no host, depois:
docker compose -f compose.yaml -f compose.ai.yaml --profile public up -d --build
```

Caddy fornece HTTPS no domínio configurado; o app permanece em loopback e o processador IA só é acessível pela rede interna. Configure APP_ENV=production, APP_SECRET estável, APP_BASE_URL HTTPS, R2 e integrações. A demo tem compose/volume/chave próprios: `edicoes/demonstracao/README.md`.

Para produção: um processo Uvicorn por SQLite/volume, backups privados fora do host, monitoramento de tarefas e capacidade. A automação roda no servidor após a autorização inicial; não depende de um navegador aberto, mas depende do host em funcionamento.
