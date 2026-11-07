# Edição comercial — R$ 149,99/mês

Usa o código único do repositório com APP_EDITION=saas. Não há cópia divergente da interface. O plano público é Studio: 20 vídeos e 40 imagens por período, valores/cotas configuráveis. Contratos Stripe antigos continuam reconhecidos.

1. Execute `./scripts/install.sh` e `.venv/bin/python -m scripts.configure_editions`.
2. Configure .env: APP_ENV=production, APP_BASE_URL HTTPS, STORAGE_BACKEND=r2 e as chaves R2. O APP_SECRET já gerado deve permanecer estável.
3. Configure Mercado Pago conforme `docs/mercado-pago/`. O retorno do checkout não libera acesso; somente pagamento aprovado consultado na API após webhook assinado.
4. Ative Kokoro com `docker compose -f compose.yaml -f compose.ai.yaml --profile public up -d --build`, após preencher domínio e ACME_EMAIL no .env.
5. Configure Meta/SMTP; faça as homologações reais antes de vender. A primeira campanha recebe fotos, prompt e conexão autorizada; as próximas execuções não exigem aprovação por post.

Não usar APP_EDITION=demo para clientes pagantes. O código não provisiona serviços, cobra ou conecta contas por conta própria.
