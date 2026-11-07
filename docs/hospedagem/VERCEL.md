# Vercel: corrigir FUNCTION_INVOCATION_FAILED e conectar o SaaS

A página inicial e o favicon agora são entregues diretamente pelo Vercel, a partir de **dist**. Eles não invocam Python nem dependem da API. A configuração anterior ainda roteava os arquivos pela função FastAPI e a imagem enviada confirma uma falha de invocação, mas não revela sua exceção interna.

A API foi isolada em **api/gateway.mjs**, uma função Node 24 sem dependências externas. Ela encaminha as operações ao backend persistente existente. O pacote foi construído com o SDK oficial @vercel/node, materializado e invocado por HTTP localmente. Não importa o banco nem os modelos de IA.

| Parte | Entrada / destino |
|---|---|
| Vercel: página, CSS, JavaScript, favicon e bootstrap público | arquivos de dist, servidos diretamente |
| Vercel: encaminhamento da API | api/gateway.mjs, Node 24 |
| Host CPU: contas, sessões, banco, fila, FFmpeg e automação | autoposts.main:app, como já usado no Docker |
| Narração | Processador privado Kokoro no host CPU |
| Fotos e vídeos privados em produção | Cloudflare R2 |

## 1. Refazer o deploy da branch main

No projeto Vercel, configure:

- **Root Directory:** raiz do repositório, sem selecionar autoposts ou ai_worker.
- **Framework Preset:** **Other**, não FastAPI.
- **Install Command:** `npm ci --ignore-scripts`.
- **Build Command:** `npm run build`.
- **Output Directory:** `dist`.
- **Node.js:** 24.x, já definido em package.json.
- **Branch:** main, usando o commit desta correção ou mais recente.

vercel.json já declara essas opções. Não mantenha overrides antigos de Python/Workers no painel. Faça um novo deploy sem reaproveitar o cache da configuração anterior. Recarregar uma implantação antiga não atualiza código, rotas ou runtime.

O código foi enviado ao GitHub; o ambiente não tem acesso autenticado à conta Vercel para alterar o projeto ou acionar redeploy pelo painel. A validação HTTP do domínio também depende de a política de rede do ambiente permitir o endereço.

O build é Node sem pacotes de produção: copia os arquivos públicos e gera um favicon válido e site-config.json. O bootstrap exporta somente preço, cotas e estado público, nunca URL do backend, chaves ou credenciais. Pesos, banco, arquivos .env e código Python são excluídos do pacote Vercel. O adaptador ASGI autoposts.vercel permanece no repositório para compatibilidade e testes, mas não é mais a entrada do Vercel; pyproject.toml não seleciona FastAPI.

## 2. Conectar o backend persistente

Na seção **Settings → Environment Variables** do Vercel, adicione:

```dotenv
AUTOPOSTS_BACKEND_URL=https://seu-backend.exemplo.com
```

Esse é um exemplo de formato, não um servidor provisionado. Use a URL HTTPS real do host que executa o backend. Informe somente a origem, sem /api, caminhos, credenciais ou query string. **Não use o próprio endereço Vercel**: isso criaria um loop, agora bloqueado pelo código.

Configure o ambiente desejado (Production e/ou Preview) e refaça o deploy depois de salvar. O gateway precisa alcançar o backend por HTTPS com certificado válido. Credenciais R2/Meta/Mercado Pago/SMTP e APP_SECRET permanecem somente no backend. O modelo .env.vercel.example lista as variáveis específicas da interface.

Se o host CPU ainda não existe, siga [hospedagem](README.md). Nenhum host foi contratado nesta correção. R2 não executa Python, SQLite, FFmpeg ou Kokoro; Vercel sozinho não fornece esse processamento persistente nesta arquitetura. Não há garantia de hospedagem comercial gratuita permanente; confira as franquias e termos dos provedores.

## 3. Ajustar as URLs públicas no backend

O backend deve conhecer o endereço usado pelo cliente:

```dotenv
APP_ENV=production
APP_BASE_URL=https://auto-posts-rouge.vercel.app
INSTAGRAM_REDIRECT_URI=https://auto-posts-rouge.vercel.app/api/integrations/instagram/callback
STORAGE_BACKEND=r2
```

Mantenha o APP_SECRET existente, com pelo menos 32 caracteres, e o volume/banco existentes. Não gere outra chave para corrigir o deploy. A chave existente protege tokens e gravações cifradas.

Cadastre a mesma URL de retorno no aplicativo Meta. Para Mercado Pago, use https://auto-posts-rouge.vercel.app/api/billing/mercadopago/webhook. Para domínio próprio, substitua as URLs pelo domínio público final. Esses endereços devem coincidir com APP_BASE_URL para a validação de origem/CSRF e cookies seguros.

Para que os limites por IP diferenciem os clientes atrás do Vercel, configure também **AUTOPOSTS_GATEWAY_SECRET** com o mesmo valor aleatório forte (pelo menos 32 caracteres) no Vercel e no backend. Use uma chave específica, separada do APP_SECRET. O backend só aceita a identidade de cliente encaminhada quando essa chave confere; cabeçalhos enviados pelo usuário não bastam. Sem a chave, os limites usam o IP do proxy e podem agrupar clientes. Não envie essa chave por chat ou GitHub.

O gateway preserva cookies individuais, cabeçalho CSRF, método, corpo original de webhooks, assinatura, query string e chave de idempotência. Não repete automaticamente operações de escrita. Não guarda cookies entre clientes e não encaminha requisições para URLs escolhidas por usuários.

## 4. Como fica sem o backend conectado

A página pública abre, mas exibe **Estúdio em configuração**. Login/cadastro mostram uma explicação e não pedem senha. Operações de conta, geração e cobrança retornam 503 com código seguro. Nenhum usuário, pagamento ou banco temporário é inventado.

Isso permite verificar o site sem outra queda de inicialização. **Não significa que o SaaS esteja operacional.** Para login, biblioteca, geração e publicação reais, AUTOPOSTS_BACKEND_URL precisa apontar para o backend persistente ativo. Com ele conectado, as mesmas funcionalidades e edições existentes continuam sendo atendidas pelo backend.

## 5. Arquivos e limites

O gateway limita arquivos a 4 MB para respeitar a margem do limite de payload de funções Vercel. Fotos maiores, até 25 MB, são preparadas automaticamente no navegador, mantendo a proporção e convertendo para JPEG antes do envio. Áudios acima do limite recebem orientação antes do upload. O backend tradicional conserva seus limites anteriores quando acessado diretamente.

Renderizadores remotos que enviam vídeos grandes devem acessar diretamente a URL do backend, com o token de serviço existente; não envie esse resultado grande pelo gateway.

Vídeos grandes devem ser armazenados no R2. A rota autenticada responde com redirecionamento para a URL assinada; o gateway não baixa nem reenvia o vídeo inteiro pelo limite da função. Respostas grandes recebidas diretamente do backend são recusadas de forma controlada. Em produção não use armazenamento local para downloads pelo Vercel.

O gateway tem prazo total de 50 segundos, abaixo dos 60 configurados para a função. Backend lento ou indisponível gera 503 controlado; isso não inicia uma segunda criação ou cobrança. Renderização e agenda continuam na fila do servidor, depois que a requisição termina.

## Diagnóstico

| Resultado | Significado / ação |
|---|---|
| Página pública abre, aviso de configuração | Falta conectar/configurar o backend; não vender como serviço ativo |
| BACKEND_NOT_CONFIGURED | Preencher AUTOPOSTS_BACKEND_URL e refazer deploy |
| BACKEND_CONFIGURATION_INVALID | Usar uma origem HTTPS pública válida, sem caminho ou credenciais |
| BACKEND_PROXY_LOOP | O destino aponta para o próprio site; usar a URL do host CPU |
| BACKEND_UNAVAILABLE / BACKEND_TIMEOUT | Conferir funcionamento, HTTPS e tempo de resposta do backend |
| BACKEND_RESPONSE_TOO_LARGE | Usar mídia privada R2 com redirecionamento, não download local grande |
| 500 FUNCTION_INVOCATION_FAILED ainda aparece | Conferir commit e Root Directory; ler Runtime Logs do novo deploy para identificar outra exceção |

/health retorna 503 e service_ready=false sem backend; conectado, encaminha a verificação real do backend. Uma página pública 200 não comprova geração, assinatura ou publicação reais.

## Validação desta correção

- **211 testes Python** do backend e do adaptador ASGI preservado.
- **25 testes Node** da nova API e da entrega estática. Um teste faz a API retornar 500 e confirma que /, favicon, login e arquivos continuam em 200.
- `npm ci`, `npm test` e `npm run build` passaram.
- SDK oficial @vercel/node 30.0.0 gerou Lambda nodejs24.x com apenas dois módulos. O pacote foi materializado, importado e atendeu requisições HTTP localmente, sem Python.
- Chromium validou página pública mesmo com API simulada em 500. Com backend Python demo por HTTP local, validou cadastro/cookies, foto maior que 4 MB preparada antes de enviar e voz Kokoro real até MP4 1080×1920/AAC.

Essas evidências não comprovam um redeploy na conta do operador. Nenhuma publicação Meta ou cobrança foi executada. Consulte [relatório específico](../VERCEL_VALIDATION.md) e [guia principal](../../GUIA-DE-INSTALACAO/README.md).
