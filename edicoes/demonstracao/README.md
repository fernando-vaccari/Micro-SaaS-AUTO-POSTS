# Edição de demonstração — mesma interface, sem assinatura

A demo executa exatamente o mesmo código. APP_EDITION=demo é uma configuração do servidor; não existe parâmetro do navegador que transforme a edição comercial em demo.

```bash
./scripts/install.sh
.venv/bin/python -m scripts.configure_editions
docker compose --env-file .env.demo -f compose.demo.yaml up -d --build
```

O comando gera o app na porta local 8001 e o processador Kokoro privado. O projeto Compose autoposts-demo é independente do comercial; iniciar ou parar a demo não substitui os serviços comerciais. Banco/arquivos ficam no volume demo-data; os modelos em demo-models. A demo tem sua própria chave e não compartilha o banco comercial. Não use `down -v` para preservar os dados.

Sem Docker: inicie o processador de voz conforme `docs/ias-gratuitas/INSTALAR.md` e execute `.venv/bin/python -m scripts.start_demo`.

A criação funciona sem pagamento, com limites de 20 vídeos e 40 imagens por período (configuráveis). Checkout, portal e webhooks de cobrança são bloqueados no servidor. Publicação real está habilitada, mas exige HTTPS público, R2 configurado, conexão OAuth profissional e autorização ao ativar/agendar. A demo nunca simula publicação bem sucedida.

Em URL pública, ajuste .env.demo: APP_ENV=production, APP_BASE_URL e callback HTTPS, STORAGE_BACKEND=r2, credenciais de bucket próprio e identificação do operador. Não use a chave ou volume comercial. O gateway de pagamento não é necessário na demo; se usar o frontend Vercel, configure o gateway de API conforme o guia abaixo.

Após conectar Instagram, envie fotos, escreva o prompt, escolha voz feminina ou masculina e ative o piloto. O fluxo gera, monta, narra e publica automaticamente. Ajustes de rotina e pausa ficam em Automações. A biblioteca mostra o resultado e as falhas. R2/Meta precisam de homologação real; a edição demo não contorna limites dessas plataformas.

Guia completo, com HTTPS, R2, Vercel e validação: [COLOCAR-NO-AR.md](COLOCAR-NO-AR.md). O HTTPS opcional está em `compose.demo.public.yaml`.
