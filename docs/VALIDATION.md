# Validação da entrega — 21/10/2026

## IMPLEMENTADO E TESTADO

- Suíte: **103 testes passaram**, zero falhas na execução completa final. Um aviso de depreciação do adaptador Starlette/httpx, sem falha funcional. Uma primeira versão do teste de migração de senha usava salt em formato incorreto; a fixture foi corrigida para o formato hexadecimal legado e o teste passou. A instalação com .env revelou também que STRIPE_PRICE_PRO vazio ocultava o fallback legado; o código foi corrigido e a fixture foi isolada das variáveis do operador. Após os últimos ajustes de retenção/backup, os 20 testes SaaS passaram; a restrição de período da assinatura também foi validada novamente.
- Cobertura: cadastro/login/sessões, autorização entre clientes, uploads, campanhas/agendamento/fuso, quota, OAuth e publicação com mocks, Stripe assinado/replay/cancelamento, quatro planos, trial, checkout duplicado, JPEG, fila/leases, retry, falha B2 sem conclusão, callback com versão confirmada, retenção/exclusão e backup.
- Navegador Chromium real: landing com quatro planos; cadastro; imagem com marca → fila → JPEG → biblioteca; campanha em três dias da semana → prévia → MP4 de **45 segundos, 1080×1920**; perfil; viewport 390 px sem overflow; zero pageerrors JavaScript. Nenhuma publicação realizada.
- Docker: imagem construída com TLS verificado e CA confiável via segredo BuildKit; usuário sem privilégios, health saudável. Cadastro/CSRF, fila, JPEG e MP4 H.264 1080×1920 reais gerados e baixados privadamente no container.
- Scripts de instalação repetidos com 37 dependências compatíveis; sintaxe Python, JavaScript e shell verificada. Quatro workflows YAML parseados e estrutura jobs/on validada. Compose com perfil público validado após criar .env local sem credenciais. Caddy validate aprovou o Caddyfile com domínio/e-mail de exemplo, sem emissão de certificado.
- Screenshots em `docs/screenshots/landing.png`, `library.png` e `plans-mobile.png` mostram o teste local. Dashboard/mobile antigos foram mantidos como histórico, não como evidência nova.

## IMPLEMENTADO, AGUARDANDO CREDENCIAIS

- B2 real: SDK e fluxo integrados/testados por mocks. O teste real no GitHub **FALHOU** no upload por rejeição do Key ID, não confirmou roundtrip. Evidência: https://github.com/fernando-vaccari/Micro-SaaS-AUTO-POSTS/actions/runs/39643387400, job 119372519319. Diagnóstico sanitizado: “B2 rejeitou o Key ID. Verifique se B2_KEY_ID é o keyID da nova Application Key S3, e não o Account ID ou o nome da chave.” Confirme o par nos Secrets e execute o workflow manual na branch da entrega. Não envie chaves pelo chat.
- Instagram: implementação oficial com OAuth, state, tokens cifrados/renovação, permissões, imagem e Reels. Necessita app/roles/revisão Meta, credenciais, conta profissional e callback HTTPS.
- Stripe: checkout/portal, quatro planos, trial e webhooks implementados. Necessita quatro Prices, chaves, endpoint webhook e portal configurados. Somente contratos simulados foram testados.
- SMTP: recuperação/verificação implementadas e testadas com envio simulado. Necessita remetente, credenciais e entrega real.
- IA opcional: geração de roteiro textual necessita chave; templates sem IA funcionam.

## IMPLEMENTADO, AGUARDANDO TESTE REAL

- B2: upload/read/delete, autorização por cliente, versões e URLs assinadas com credenciais válidas no servidor.
- Meta: publicação autorizada de uma imagem e um Reel; renovação, revogação e campanha prolongada. Não foi publicado conteúdo real.
- Stripe: homologação sandbox completa (inclusive ciclo, mudança de plano e inadimplência). Nenhuma cobrança real executada.
- SMTP: entrega, expiração e revogação com remetente real.
- Deploy HTTPS: arquivos Docker/Caddy prontos; falta host/domínio, DNS, certificado e validação externa. Não há serviço SaaS público implantado por esta tarefa.
- Restore em outra máquina e recuperação de desastre: ferramenta de backup testada, procedimento documentado, operação externa ainda não exercitada.

## AINDA NÃO IMPLEMENTADO

- Backend Python/FFmpeg no Workers Free: não é suportado por esta arquitetura; o pedido mais recente optou por continuar Python e aproveitar o frontend.
- Deploy automático para host de produção: CI está configurado; sem host/credenciais definidos não foi criado um deploy remoto.
- Cluster/autoscaling, banco distribuído, HA, alertas/backup externo gerenciados e SLA.
- Síntese de vídeo/voz por modelo de IA e texto animado palavra a palavra. Vídeos usam composição real por templates, cenas, fundos, movimento e fades.

## Intervenção mínima para lançamento

Corrigir B2; configurar host HTTPS/volume/backup; validar SMTP; criar/configurar app Meta e acesso para clientes; configurar e homologar Stripe; identificar o operador e revisar política legal/tributária. O guia `OPERATIONS.md` informa onde criar e onde colocar cada chave, deploy, conexão Instagram, pagamentos e custos. Não classificar como pronto para venda antes dessas verificações.
