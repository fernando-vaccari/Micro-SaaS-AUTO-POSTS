# Validação da correção de inicialização no Vercel

## Problema observado e reprodução

A imagem enviada mostra **500 FUNCTION_INVOCATION_FAILED**, sem traceback. Portanto, não estabelece qual exceção ocorreu no deploy da conta do operador.

Na entrada anterior, importar autoposts.main já carregava core.load_settings, que pode criar .data/.app-secret. O lifespan também cria banco/diretórios e inicia workers. Em uma reprodução controlada, fazer Path.mkdir retornar EROFS (disco somente de leitura) interrompeu a importação. Produção sem APP_SECRET também interrompia a entrada antes de servir a página.

## Correção entregue

- Entrada Vercel em autoposts.vercel:app, sem importar core/main/worker, sem banco descartável e sem criação de chave local. O backend persistente continua autoposts.main:app no host CPU.
- Páginas e assets incluídos no pacote; Python 3.12; exclusão de dados, ambientes privados, pesos e caches por .vercelignore.
- Encaminhamento limitado à origem HTTPS configurada pelo operador. URLs inválidas, loop para o próprio Vercel, backend fora do ar, corpo/resposta grande e timeout retornam códigos controlados.
- Sessão/CSRF, múltiplos Set-Cookie, corpos originais de webhooks, assinatura, query string e idempotência preservados. Nenhuma repetição automática de POST. Cookies não são compartilhados entre invocações/clientes.
- IP por cliente encaminhado somente com chave específica compartilhada. O backend ignora cabeçalhos forjados sem essa chave; metadados internos não são devolvidos como cabeçalhos ao navegador.
- Fotos grandes preparadas antes do upload para respeitar a margem de 4 MB. Downloads privados grandes usam o redirecionamento R2 existente.
- Sem backend, página pública em configuração; nenhum formulário de senha/cadastro funcional, cobrança ou sessão fictícia. /health informa indisponibilidade do serviço.

## Evidências locais

**211 testes aprovados**, sendo 34 contratos de gateway. A entrada foi importada em processo separado, com APP_ENV=production, APP_SECRET vazio e escrita de diretórios bloqueada. Página, login, cadastro e assets retornaram 200; operações privadas retornaram 503; core/main/worker não foram importados.

Testes ligados ao backend real da aplicação por transporte ASGI validaram cadastro, cookies, dois usuários isolados, CSRF e uma criação repetida que manteve um único conteúdo/crédito no banco persistente de teste. Outros testes verificaram corpo/cabeçalhos, gzip, assinatura, redirects R2 sem baixar o objeto, tamanho, timeout e limites por IP autenticado.

Chromium abriu o site sem backend, encontrou a mensagem de configuração e nenhum campo de senha; mobile 390px sem overflow. Com backend demo isolado, cadastrou um usuário, preparou foto PNG maior que 4 MB em JPEG menor que o limite, enviou as fotos, solicitou narração feminina **Kokoro real em CPU** e recebeu MP4 1080×1920 com AAC pela interface do gateway. A conexão com esse backend foi em processo local via ASGI, não um teste remoto de TLS/Vercel.

O teste reproduzível de navegador é scripts/smoke_vercel_browser.py e exige servidores locais de teste/Playwright/Chromium. Artefato de vídeo em artifacts/vercel-kokoro-demo.mp4 (ignorado pelo Git); capturas públicas de teste em docs/screenshots/vercel-*.png. Nenhuma mídia de cliente real foi usada.

Python, três módulos JavaScript, catálogo compartilhado, JSON/TOML de configuração e compatibilidade das 37 dependências instaladas foram verificados. O aviso conhecido Starlette/httpx permanece como depreciação, sem falha funcional.

## Limites desta evidência

Não houve acesso aos Runtime Logs ou redeploy na conta Vercel do operador. Não foram provisionados host CPU, domínio ou credenciais. R2, Meta, Mercado Pago e SMTP não foram homologados com credenciais reais nesta correção; nenhuma publicação ou cobrança real foi feita.

O reparo não transforma o SaaS completo em aplicação inteiramente serverless nem garante hospedagem comercial 100% gratuita. Para operar de fato, é necessário configurar a URL HTTPS do backend persistente e suas integrações. A página pública em configuração não comprova que o serviço esteja pronto para clientes.

Passo a passo em [hospedagem/VERCEL.md](hospedagem/VERCEL.md).
