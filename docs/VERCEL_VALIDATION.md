# Validação atual: entrega estática e API Node no Vercel

A imagem mais recente do operador mostra 500 FUNCTION_INVOCATION_FAILED na página inicial e no favicon. Os testes ASGI anteriores não comprovaram o funcionamento do pacote no runtime Vercel; a configuração anterior ainda entregava o site por uma função Python. Sem o traceback de Runtime Logs, não foi confirmada a exceção específica dessa implantação.

## Correção atual

- **Framework Other**, Node 24, `npm ci --ignore-scripts`, `npm run build`, saída **dist**. `vercel.json` declara essas opções e as rotas.
- Página inicial, login/cadastro, JavaScript, CSS, bootstrap público e favicon são arquivos estáticos. A falha de uma função não faz o Vercel invocá-la para servir esses arquivos.
- Somente API, mídia autenticada, saúde e páginas legais usam `api/gateway.mjs`. A função usa apenas módulos nativos Node e `web/config.mjs`; não instala/importa Python, FastAPI, banco ou modelos de IA.
- Sem backend, acesso e cobrança ficam bloqueados com mensagem clara. Se a API falhar, o frontend usa o bootstrap público estático para exibir a página e informar indisponibilidade, sem criar conta ou sessão autenticada fictícia.
- Cookies separados, CSRF, corpo original, query, assinatura de webhook e idempotência continuam encaminhados ao backend persistente. POST não é repetido automaticamente. Credenciais internas não vão para a saída estática nem para cabeçalhos públicos.
- `autoposts.main:app` continua sendo o backend CPU. O antigo adaptador ASGI permanece no repositório e nos testes de compatibilidade, mas não é selecionado no Vercel.

## Evidências

**211 testes Python** passaram, preservando o backend e os contratos ASGI. **25 testes Node** passaram para a nova entrega/API. Entre eles, um servidor faz toda API responder 500 e ainda assim /, favicon, login, cadastro e assets retornam 200.

`npm ci`, `npm test` e `npm run build` passaram. O lockfile foi gerado em diretório limpo e contém zero dependências externas de produção ou desenvolvimento. A saída não inclui banco, .env, modelos nem URL/chave privada do backend.

**SDK oficial @vercel/node 30.0.0:** a função foi construída em diretório isolado como Lambda nodejs24.x, handler api/gateway.mjs, com dois módulos: api/gateway.mjs e web/config.mjs. O pacote resultante foi materializado, importado e respondeu a GET /api/session e POST /api/auth/register por HTTP local. Não foi somente uma importação do código-fonte no processo de teste.

**Chromium:** página e favicon servidos diretamente; frontend continuou abrindo quando a API simulada retornou 500, usando o bootstrap estático. Cadastro ficou sem campos de senha nessa condição. Mobile 390px sem overflow. Com API Node e backend demo Python em processos distintos, conectados por HTTP de loopback, passaram cadastro/cookies, foto PNG maior que 4 MB preparada antes do envio e criação de vídeo com **Kokoro real**. O MP4 foi baixado pelo gateway e reproduzido no navegador; ffprobe confirmou H.264 1080×1920, AAC estéreo 48 kHz e 15 segundos.

O teste reproduzível é scripts/smoke_vercel_browser.py; `--failure-url` ativa a simulação de API em falha. O adaptador local `scripts/serve-vercel-local.mjs` serve o dist e a função padrão Node. Somente no ambiente de teste permite apontar o transporte para backend HTTP de loopback; o código de produção exige destino HTTPS público válido.

Capturas em docs/screenshots/vercel-*.png. O vídeo artifacts/vercel-kokoro-demo.mp4 é ignorado pelo Git. Nenhuma foto/voz pessoal de cliente foi utilizada.

## Limites e operação

A URL informada é https://auto-posts-rouge.vercel.app/. A tentativa de leitura foi bloqueada pela política de saída do ambiente (túnel 403); a liberação foi salva como proposta e não comprova aplicação ao runtime. Não houve acesso autenticado ao painel/Runtime Logs Vercel nem confirmação de redeploy nessa conta.

Não foram provisionados servidor CPU, domínio ou credenciais. R2, Meta, Mercado Pago e SMTP não foram homologados com credenciais reais nesta correção; não houve publicação nem cobrança real.

A página pública funcionar não significa que o SaaS completo esteja operacional. Para login, banco persistente, geração e automação, é necessário configurar AUTOPOSTS_BACKEND_URL com um servidor CPU ativo. R2 armazena mídia e não executa esse backend. Não foi prometida hospedagem comercial ilimitada ou permanentemente gratuita.

Passo a passo atualizado: [hospedagem/VERCEL.md](hospedagem/VERCEL.md).
