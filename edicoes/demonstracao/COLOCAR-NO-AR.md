# Colocar a edição teste completa no ar

Esta edição usa o mesmo código e interface da comercial, sem assinatura. Checkout e cobrança estão bloqueados no servidor. A publicação Instagram é real quando autorizada; não exige aprovação de cada publicação após ativar o piloto automático. Contas, banco e arquivos da demo ficam separados da edição comercial.

## 1. Servidor que continua ligado

Você precisa de um servidor Linux com Docker e Docker Compose, disco persistente e acesso público às portas 80/443. Use preferencialmente 4 GB de RAM ou mais para aplicação, FFmpeg e voz Kokoro. O notebook pode ficar desligado. Nenhum servidor foi contratado ou provisionado por este projeto. Um servidor gratuito depende da disponibilidade e condições do provedor; não há garantia de infraestrutura integralmente gratuita. R2 e Vercel não executam este backend completo.

Para o HTTPS automático abaixo, use um hostname cujo DNS aponte para o IP público desse servidor. Pode ser um subdomínio gratuito disponível no seu provedor; não precisa comprar um domínio. Portas 80/443 devem estar livres: este exemplo pressupõe um servidor dedicado à demo. Se já existir outro proxy nesses ports, integre a rota nele em vez de iniciar outro Caddy.

## 2. Baixar e preparar

Em Ubuntu 24.04, com Docker e Compose já instalados, prepare também os requisitos locais:

```bash
sudo apt-get update
sudo apt-get install -y git python3.12 python3.12-venv ffmpeg fonts-dejavu-core tzdata
git clone https://github.com/fernando-vaccari/Micro-SaaS-AUTO-POSTS.git
cd Micro-SaaS-AUTO-POSTS
./scripts/install.sh
.venv/bin/python -m scripts.configure_editions
nano .env.demo
```

O instalador requer Python 3.12+ com venv. O preparador cria os arquivos privados e chaves sem imprimir valores, preservando configurações existentes. Não publique `.env.demo` nem compartilhe suas chaves. Faça backup seguro do volume e da chave DEMO_APP_SECRET; não troque essa chave após cadastrar contas e integrações.

## 3. Configurar a demo

Em `.env.demo`, mantenha as chaves geradas e configure os campos abaixo. Os exemplos de hostname devem ser substituídos pelos seus endereços reais.

```dotenv
APP_EDITION=demo
APP_ENV=production
APP_BASE_URL=https://auto-posts-rouge.vercel.app
AUTOPOSTS_DOMAIN=backend-demo.seu-dominio
ACME_EMAIL=seu-email
DEMO_ALLOW_PUBLISHING=true
STORAGE_BACKEND=r2
R2_ACCOUNT_ID=seu-account-id
R2_BUCKET_NAME=seu-bucket-privado-exclusivo-da-demo
R2_ACCESS_KEY_ID=sua-chave-s3
R2_SECRET_ACCESS_KEY=seu-segredo-s3
INSTAGRAM_APP_ID=seu-app-id-meta
INSTAGRAM_APP_SECRET=seu-app-secret-meta
INSTAGRAM_REDIRECT_URI=https://auto-posts-rouge.vercel.app/api/integrations/instagram/callback
LEGAL_OPERATOR_NAME=nome-do-responsavel
LEGAL_CONTACT_EMAIL=email-de-contato
MEDIA_TTL_HOURS=10
```

Configure também SMTP_HOST, SMTP_FROM, SMTP_PORT, SMTP_MODE, SMTP_USERNAME e SMTP_PASSWORD com um remetente válido para verificação de e-mail e recuperação de senha. Mantenha os campos Mercado Pago vazios na demo. Configure AUTOPOSTS_GATEWAY_SECRET com uma chave aleatória privada de pelo menos 32 caracteres e copie a mesma chave para o Vercel. Gere-a em um gerenciador de senhas; não use DEMO_APP_SECRET para isso.

No Cloudflare, crie o bucket R2 privado e um par de credenciais S3 com acesso somente a ele. Um token de API genérico da Cloudflare não substitui as chaves S3. O R2 tem franquias gratuitas, mas habilitação/faturamento e excedentes seguem as condições da Cloudflare. Veja [R2](../../docs/hospedagem/R2.md). Não configure acesso público ao bucket.

Se preferir hospedar também a interface diretamente nesse servidor e dispensar Vercel, use `https://SEU-HOSTNAME-BACKEND` como APP_BASE_URL e como origem do callback Meta. Nesse caso o segredo do gateway Vercel pode ficar vazio.

## 4. Iniciar backend, voz e HTTPS

```bash
docker compose --env-file .env.demo -f compose.demo.yaml -f compose.demo.public.yaml up -d --build
docker compose --env-file .env.demo -f compose.demo.yaml -f compose.demo.public.yaml ps
```

O primeiro build baixa os modelos de voz e pode demorar. Caddy emite o certificado quando DNS e portas estiverem corretos. O banco fica no volume demo-data e os modelos em demo-models; Caddy possui volumes próprios de certificados. Não use `down -v`, pois apaga volumes. Os serviços reiniciam automaticamente enquanto Docker e o servidor estiverem ativos.

Para diagnosticar inicialização, consulte localmente `docker compose --env-file .env.demo -f compose.demo.yaml -f compose.demo.public.yaml logs --tail=100 demo ai caddy`. Não publique logs sem revisar possíveis dados pessoais.

## 5. Conectar o Vercel existente

No projeto do site, Settings → Environment Variables, ambiente Production:

- AUTOPOSTS_BACKEND_URL: `https://SEU-HOSTNAME-BACKEND`, sem `/api` e diferente do endereço Vercel.
- AUTOPOSTS_GATEWAY_SECRET: exatamente a chave privada do backend.
- APP_EDITION: `demo`.
- LEGAL_OPERATOR_NAME e LEGAL_CONTACT_EMAIL: seus dados de responsável.

Settings → Build and Deployment: Framework **Other**, Root Directory raiz do repositório, Node **24.x**, Install Command `npm ci --ignore-scripts`, Build Command `npm run build`, Output Directory `dist`. Faça Redeploy da branch main. Não selecione FastAPI para esse frontend. Nenhuma credencial R2, Meta ou Mercado Pago deve ir para o navegador.

O aviso “Estúdio em configuração” só desaparece quando o gateway alcança o backend pronto. Se persistir, verifique URL, HTTPS, saúde dos containers e variáveis do ambiente Production; trocar apenas APP_EDITION não liga o backend.

## 6. Habilitar e validar o fluxo real

1. Cadastre uma conta e valide o e-mail; teste recuperação de senha.
2. Execute o workflow GitHub **Testar armazenamento Cloudflare R2**, com variáveis e secrets conforme a documentação R2. Apenas R2_ROUNDTRIP_OK confirma upload/leitura/exclusão reais. Configurar o bucket no servidor não configura automaticamente os secrets do GitHub.
3. Configure um aplicativo oficial Meta e cadastre exatamente o callback HTTPS informado. Conecte uma conta profissional elegível de teste. Para clientes externos, obtenha as permissões/revisões exigidas pela Meta.
4. Envie fotos próprias, escreva o prompt, escolha voz feminina ou masculina e ative o piloto automático. Essa ativação autoriza publicações reais na conta conectada. Comece com uma conta de demonstração e confira o primeiro resultado na biblioteca e no Instagram.
5. Verifique geração, narração, agendamento e publicação nos horários definidos. Depois da autorização inicial, o processamento roda no servidor, sem notebook e sem aprovação por post. Acompanhe falhas e reconexões exigidas pela plataforma.

A mídia gerada vence após 10 horas; itens de agendamentos pendentes e fontes necessárias a campanhas ativas são protegidos para não quebrar publicações. Portanto a exclusão não é incondicional para todos os arquivos ao completar 10h. Metadados e histórico permanecem. A demo possui limites padrão de 20 vídeos e 40 imagens por período, ajustáveis no servidor.

## Limites da entrega e edição comercial

A geração disponível monta vídeos com fotos, movimento, textos, transições e narração Kokoro feminina/masculina em CPU. Isso não equivale a vídeo fotorrealista generativo ou clonagem de voz homologada. Não há garantia de serviços externos ilimitados e gratuitos. R2, Instagram e pagamentos precisam de validação com suas credenciais; o projeto não declara essa homologação já feita.

Para vender a assinatura de R$149,99, mantenha outra instalação com APP_EDITION=saas, segredo, banco e bucket próprios, e siga [Mercado Pago](../../docs/mercado-pago/README.md). O gateway cobra as tarifas do próprio serviço. Não converta o banco de demonstração em comercial nem exponha essa demo como se tivesse limites/entitlements de produção.
