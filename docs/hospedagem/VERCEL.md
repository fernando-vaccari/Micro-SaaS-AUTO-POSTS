# Vercel: corrigir FUNCTION_INVOCATION_FAILED e conectar o SaaS

O Vercel agora usa **autoposts.vercel:app**, definido em pyproject.toml. A entrada anterior autoposts.main:app criava chave local, banco e processos contínuos; isso é incompatível com o ambiente de uma função serverless. A falha por disco somente de leitura foi reproduzida localmente. A imagem 500 enviada pelo operador não contém o traceback do deploy, portanto não confirma sozinha qual exceção aconteceu na conta Vercel.

A nova entrada não importa o banco, não grava APP_SECRET em arquivo, não cria SQLite em /tmp e não inicia threads de renderização ou agendamento. Ela serve a interface e encaminha as operações ao backend persistente existente.

| Parte | Entrada / destino |
|---|---|
| Vercel: interface, arquivos do site e encaminhamento da API | autoposts.vercel:app |
| Host CPU: contas, sessões, banco, fila, FFmpeg e automação | autoposts.main:app, como já usado no Docker |
| Narração | Processador privado Kokoro no host CPU |
| Fotos e vídeos privados em produção | Cloudflare R2 |

## 1. Refazer o deploy da branch main

No projeto Vercel, configure:

- **Root Directory:** raiz do repositório, sem selecionar autoposts ou ai_worker.
- **Framework Preset:** FastAPI.
- **Build Command, Install Command e Output Directory:** padrões automáticos do framework, sem comandos antigos de Workers ou servidor Uvicorn permanente.
- **Branch:** main, usando o commit desta correção ou mais recente.

O repositório inclui pyproject.toml, vercel.json, .python-version e .vercelignore. O runtime é Python 3.12; o pacote inclui explicitamente autoposts/static/**. Pesos de IA, bancos, arquivos .env e diretórios de desenvolvimento ficam fora do upload. Não use ai_worker.app:app como entrada do site.

Faça um novo deploy a partir do GitHub; recarregar uma implantação antiga não atualiza o código. Esta correção não foi implantada diretamente na conta Vercel, à qual o ambiente de desenvolvimento não tem acesso.

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
APP_BASE_URL=https://seu-site.vercel.app
INSTAGRAM_REDIRECT_URI=https://seu-site.vercel.app/api/integrations/instagram/callback
STORAGE_BACKEND=r2
```

Mantenha o APP_SECRET existente, com pelo menos 32 caracteres, e o volume/banco existentes. Não gere outra chave para corrigir o deploy. A chave existente protege tokens e gravações cifradas.

Cadastre a mesma URL de retorno no aplicativo Meta. Para Mercado Pago, use https://seu-site.vercel.app/api/billing/mercadopago/webhook. Para domínio próprio, substitua as URLs pelo domínio público final. Esses endereços devem coincidir com APP_BASE_URL para a validação de origem/CSRF e cookies seguros.

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

211 testes automatizados no conjunto completo, incluindo 34 contratos de gateway. Testes locais cobrem entrada em disco somente de leitura, ausência de APP_SECRET, cookies seguros separados, isolamento de contas, CSRF, corpo de webhook, concorrência/idempotência, limites, timeouts e erros sanitizados.

Chromium validou página pública e cadastro bloqueado sem backend; com backend demo de teste, validou cadastro, foto maior que 4 MB preparada antes do upload, voz Kokoro real e MP4 1080×1920/AAC através do gateway. O backend de teste foi conectado em processo local com transporte ASGI, não a uma implantação real Vercel/R2/Meta/Mercado Pago.

Consulte [relatório específico](../VERCEL_VALIDATION.md) e [guia principal](../../GUIA-DE-INSTALACAO/README.md). Fontes oficiais: https://vercel.com/docs/frameworks/backend/fastapi e https://vercel.com/docs/functions/limitations .
