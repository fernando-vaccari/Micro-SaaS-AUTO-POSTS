# Configuração, deploy e operação

## Backblaze B2 — prioridade de configuração

No painel Backblaze, abra Buckets e confirme o bucket **privado** `autoposts-media-fernando`, região `us-east-005`. Em Application Keys crie/consulte uma chave S3 para esse bucket, com permissões `listFiles`, `readFiles`, `writeFiles` e `deleteFiles`. O teste usa `diagnostics/`; a aplicação usa `users/`. Uma chave limitada a outro prefixo impedirá operações. Não use a master key, Account ID, nome da chave ou chave de outro bucket.

No GitHub, Settings → Secrets and variables → Actions:

| Tipo | Nome | Configuração |
|---|---|---|
| Secret | B2_KEY_ID | `keyID` da Application Key |
| Secret | B2_APPLICATION_KEY | `applicationKey` do mesmo par |
| Variable | B2_BUCKET_NAME | autoposts-media-fernando |
| Variable | B2_ENDPOINT | s3.us-east-005.backblazeb2.com |

Não adicione aspas, rótulos ou quebras de linha. Não envie chaves pelo chat. O SDK assina S3 localmente: precisa dos valores reais do par no processo seguro; um placeholder de proxy HTTP não é uma chave S3 utilizável.

Resultado real observado em 21/10/2026: [run 39643387400](https://github.com/fernando-vaccari/Micro-SaaS-AUTO-POSTS/actions/runs/39643387400), job 119372519319, falhou no upload com diagnóstico sanitizado de rejeição do Key ID. Não foi demonstrado um roundtrip bem sucedido. Os logs completos autenticados da execução anterior não estavam acessíveis neste ambiente; o novo workflow expôs a anotação segura do erro observado.

Diagnóstico atualizado, commit `2e29921`: [run 39655817439](https://github.com/fernando-vaccari/Micro-SaaS-AUTO-POSTS/actions/runs/39655817439). Ambos os Secrets chegaram definidos; o Key ID recebido tinha **26 caracteres**. Todos os indicadores de espaços, quebras, aspas, rótulos, caracteres não ASCII/invisíveis eram falsos; bucket, endpoint e região correspondiam aos esperados. O upload ainda retornou **InvalidAccessKeyId**. Não houve roundtrip confirmado e nenhum Secret foi alterado. O comprimento recebido deve ser comparado privadamente com o keyID original; o script não presume uma extensão fixa nem revela trechos da chave. A suíte local passou com 124 testes, incluindo 34 específicos de storage/diagnóstico.

Para executar novamente, abra Actions → Testar armazenamento Backblaze B2 → Run workflow → selecione **feat/saas-b2-finish**. No passo “Diagnosticar configuração segura e testar objeto privado”, procure `B2_ENV_DIAGNOSTICS` e a anotação “B2 configuração segura”. O diagnóstico inspeciona exatamente as variáveis recebidas pelo teste antes de criar o cliente, sem imprimir chaves completas, trechos ou hashes.

- `B2_KEY_ID.defined` e `B2_APPLICATION_KEY.defined` devem ser `true`. Se forem `false`, o Secret não foi disponibilizado a esse job. O workflow não seleciona um GitHub Environment: usa Secrets do repositório/organização. Atualizar um Secret de Environment não altera o Secret de repositório usado aqui.
- `B2_KEY_ID.character_count` é o comprimento recebido, não uma impressão parcial. Compare-o privadamente com o keyID exibido no Backblaze; o script não impõe um comprimento arbitrário.
- Todos os campos `has_*` devem ser `false`: detectam espaços, quebras de linha, aspas, rótulos de variável, caracteres não ASCII e caracteres invisíveis. Valores malformados são rejeitados antes de enviar a requisição, sem normalização silenciosa.
- `endpoint.valid`, `endpoint.matches_expected`, `endpoint.region_matches_endpoint` e `bucket.matches_expected` devem ser `true`. O endpoint esperado é `https://s3.us-east-005.backblazeb2.com`; a região do workflow é `us-east-005`. O endpoint recebido não é impresso, pois uma URL malformada poderia conter credenciais.
- Com os indicadores corretos, `InvalidAccessKeyId` significa que o endpoint S3 não reconheceu o identificador efetivamente enviado. Isso não identifica sozinho se existe divergência entre o Secret usado pelo job e o par vigente no provedor. Os testes confirmam que credenciais, token e endpoint AWS do ambiente não substituem os parâmetros B2 explícitos.
- `SignatureDoesNotMatch` indica recusa da assinatura; `AccessDenied` indica restrição de bucket/prefixo/permissões. `stage=configuration` indica falha local antes do upload. `cleanup_status=failed` significa que a limpeza não pôde ser confirmada, mesmo se o erro principal ocorreu antes.

Sucesso exige upload pequeno, HEAD com tamanho/SHA-256, GET e comparação exata, purga de versões e confirmação de exclusão. **Somente `B2_ROUNDTRIP_OK` confirma esse teste completo.** Presença e formato corretos não comprovam autenticação. O teste não altera Secrets.

No servidor, configure as mesmas quatro variáveis B2 e `STORAGE_BACKEND=b2`. `B2_REGION` opcional deve coincidir com o endpoint. `InvalidAccessKeyId` é identificação; `SignatureDoesNotMatch` pede conferir par/região; `AccessDenied` pede bucket/prefixo/permissões. Para erros de transporte, verifique CA/proxy e endpoint HTTPS. Não desative TLS. A configuração usa boto3/botocore fixados, SigV4/path, conteúdo com tamanho/MD5 e checksums when_required.

## Servidor e HTTPS

Requer CPU para FFmpeg e disco persistente. Comece com um único serviço/volume. Para desenvolvimento: `.env.example` → `.env`, `./scripts/install.sh`, `./scripts/start.sh`. Sem SMTP/B2/Meta/Stripe é possível validar a interface e mídia local, mas não as operações externas.

Para um host público:

1. Instale Docker Engine e Compose plugin; permita entrada 80/443.
2. Crie DNS A/AAAA para o host. Cloudflare pode gerenciar DNS; comece com DNS only para emitir certificado e, se ativar proxy, use Full (strict). Não use Flexible.
3. Configure `.env`: `APP_ENV=production`, `APP_BASE_URL=https://seu-dominio`, `AUTOPOSTS_DOMAIN=seu-dominio`, `ACME_EMAIL` válido, `STORAGE_BACKEND=b2` e as integrações abaixo. Gere `APP_SECRET` aleatório de pelo menos 32 caracteres em um gerenciador de senhas e mantenha-o estável. Não cole saídas secretas em tickets/logs.
4. Execute `docker compose --profile public up -d --build`. O Caddy provisiona TLS nesse host real; não foi emitido certificado nesta entrega. Não exponha a porta 8000 na internet.
5. Confirme `docker compose ps`, logs sanitizados e GET HTTPS `/health`. O health verifica banco/FFmpeg, não credenciais externas. Execute os testes reais de B2/SMTP/Stripe/Meta antes de abrir vendas.

`docker compose up -d --build` inicia apenas o app em loopback. O volume `autoposts-data` contém banco e cache; não execute `down -v` em produção. Imagem roda com usuário sem privilégios. Encerramento aguarda trabalho em andamento; não use vários workers Uvicorn ou réplicas no mesmo volume.

Em ambientes com CA empresarial no build, use um bundle confiável via BuildKit: `docker build --secret id=build_ca,src=/caminho/ca-certificates.crt -t autoposts .`. Não desative validação de certificados.

## SMTP

Crie um remetente verificado num serviço SMTP de sua escolha. Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_MODE=starttls` (587) ou `ssl` (465), `SMTP_FROM`, `SMTP_USERNAME` e `SMTP_PASSWORD` no host. Verifique SPF/DKIM/DMARC conforme o fornecedor. Recuperação e confirmação exigem entrega real; tokens expiram em 30 minutos, uso único, hash no banco, sem exposição em logs. Trocar senha invalida sessões. Sem SMTP, o painel mostra erro de configuração.

## Instagram oficial

No Meta for Developers crie um app elegível com **Instagram API with Instagram Login**, usando conta profissional. Consulte a documentação vigente: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/ e seus requisitos de publicação/revisão.

Configure `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET`, `INSTAGRAM_GRAPH_VERSION` (v25.0 por padrão) e `INSTAGRAM_REDIRECT_URI=https://seu-dominio/api/integrations/instagram/callback`. Cadastre exatamente o redirect no painel Meta, HTTPS sem divergências. Publique `/privacy`, `/terms` e `/data-deletion`, preenchendo a identificação do operador e revisando os documentos antes da revisão do app.

O código solicita `instagram_business_basic` e `instagram_business_content_publish`; verifique permissões disponibilizadas ao seu app, teste com contas/roles elegíveis e solicite Advanced Access/revisão para atender terceiros. No painel AUTO POSTS, abra Instagram → Conectar → autorize na Meta → confirme conta e permissões. Nunca peça a senha Instagram.

Faça primeiro uma prévia, depois autorize explicitamente um conteúdo de teste. Confirme publicação e ID na conta real. Só depois ative campanha: essa ativação autoriza publicações futuras sem aprovar cada post. Imagem/Reels usam contêineres e consulta de processamento antes do publish. Erro ambíguo exige conferir a conta, para evitar duplicação. Desconectar revoga o vínculo local; a revogação também pode ser feita nas configurações Meta.

## Stripe e quatro planos

No Stripe Dashboard, comece em sandbox. Crie quatro produtos/Prices **recorrentes mensais em BRL**: 2999, 6999, 10999 e 15999 centavos. Defina `STRIPE_PRICE_STARTER`, `STRIPE_PRICE_PRO`, `STRIPE_PRICE_BUSINESS`, `STRIPE_PRICE_PREMIUM`, além de `STRIPE_SECRET_KEY`. Se mudar valores PLAN_*, crie Prices correspondentes; produção confere valor/moeda/período antes do checkout.

Cadastre webhook HTTPS `/api/billing/webhook`; configure seu signing secret `STRIPE_WEBHOOK_SECRET`. Habilite `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid` e `invoice.payment_failed`. Ative Customer Portal com cancelamento, atualização de pagamento e mudanças entre os quatro Prices. Nunca armazene cartões no app.

Starter exige e-mail confirmado; o checkout coleta cartão, concede sete dias se o e-mail ainda não usou teste e a assinatura é liberada por webhook. Repetição do checkout reutiliza sessão pendente; a tela permite cancelar essa sessão. A página de sucesso não libera plano. Status de falha/expiração bloqueia uso de produção; cancelamento ao fim do período acompanha o status confirmado pelo Stripe.

Valide em sandbox: compra dos quatro planos, webhook/replay, ciclo, troca, cancelamento, inadimplência e teste Starter. Depois configure chaves/Prices/webhook de produção conscientemente. Nenhuma cobrança real foi executada nesta entrega. Impostos, reembolso e faturamento fiscal precisam de definição do operador.

## IA e renderizador remoto opcionais

`AI_API_KEY` habilita roteiro textual no endpoint OpenAI; `AI_MODEL` padrão gpt-4.1-mini. Sem chave, templates funcionam e são identificados como templates. O recurso pago opcional não sintetiza vídeo ou voz por IA.

O servidor já processa a fila. Para worker externo confiável, configure `AUTOPOSTS_API_SECRET` forte no host e Secret de mesmo nome em Actions, junto da Variable `AUTOPOSTS_API_URL` apontando ao domínio base, credenciais B2 e variables do bucket/endpoint. Execute o workflow Renderizar próxima tarefa manualmente. O protocolo reserva tarefa, valida proprietário e confirma o upload antes do callback. Não exponha esse segredo ao cliente e não use Actions como processamento comercial ilimitado.

## Backup, restauração e retenção

Backup consistente, com a aplicação em funcionamento:

```bash
docker compose exec app python -m scripts.backup_db /app/.data/backup-20261021.db
docker compose cp app:/app/.data/backup-20261021.db .backups/backup-20261021.db
```

Crie `.backups` com acesso privado antes de copiar e mova o backup para armazenamento seguro externo ao host. Guarde APP_SECRET separadamente: sem ele os tokens cifrados não serão recuperáveis. Não sobrescreva backups. Para restaurar, pare o serviço, preserve cópia do estado atual, restaure o SQLite com permissões UID10001, remova WAL/SHM antigos somente com o serviço parado, recoloque a mesma chave e valide integridade/contas antes de retomar campanhas.

`MEDIA_RETENTION_DAYS=10` regula inatividade. Login/uso autenticado atualiza atividade; rotina de minuto limpa mídia elegível e preserva publicações pendentes/logos ativos. Histórico, campanhas e cobrança permanecem. B2 versionado exige purgar versões; apagar apenas uma delete marker não economizaria o armazenamento antigo. Exclusões falhas ficam no outbox, com erro sanitizado, para repetir. Exclusão de conta bloqueia sessões imediatamente e só termina após a remoção B2 confirmada. A aplicação não exclui posts publicados na Meta.

Monitorar: `/health`, jobs failed/atrasados, publicação ambígua, `storage_deletions` pendente, SMTP, uso de disco/CPU e gastos/cotas de fornecedores. Configure backups agendados e alertas no host; o repositório fornece a ferramenta de backup, não um serviço externo gerenciado de recuperação de desastre.

## GitHub e ambiente Codex

CI executa testes/mídia no push e PR. Não faz deploy automático de produção ou cobranças. O branch de implementação deve passar por revisão antes de merge. Configure o host para atualizar a partir da branch aprovada usando seus mecanismos seguros; sem credenciais/host definido, nenhum deploy remoto foi realizado.

O draft de onboarding registra instalação/start locais. Salvar draft, publicar ambiente de desenvolvimento e implantar o SaaS são operações distintas. Restrições de rede da instância podem impedir `api.github.com` mesmo quando Git push funciona; isso não significa que seja necessário enviar um PAT pelo chat.
