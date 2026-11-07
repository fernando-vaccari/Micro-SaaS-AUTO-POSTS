# Mercado Pago — passo a passo da assinatura mensal

Integração preparada no código. O preço inicial do Studio é **R$149,99/mês**, BRL, recorrência de um mês. O cliente usa checkout hospedado pelo Mercado Pago; o AUTO POSTS não recebe cartão. A conta demo bloqueia cobranças no servidor.

## 1. Criar a aplicação

No painel Mercado Pago Developers, entre em **Suas integrações**, crie uma aplicação e habilite o produto de assinaturas aplicável à sua conta. Verifique requisitos da conta, disponibilidade e termos atuais:

- https://www.mercadopago.com.br/developers/pt/docs/subscriptions/overview
- https://www.mercadopago.com.br/developers/pt/reference/preapproval/_preapproval/post
- https://www.mercadopago.com.br/developers/pt/docs/your-integrations/notifications/webhooks

Não confundir um pagamento avulso com uma assinatura recorrente. O backend cria `/preapproval` pendente, com `auto_recurring` mensal, `external_reference` do proprietário e valor de R$149,99. Não impõe Pix recorrente nem promete meios de pagamento que a conta/produto não disponibilize.

## 2. Colocar credenciais no host

Preencha somente o gerenciador seguro do host ou seu .env privado:

```dotenv
APP_EDITION=saas
APP_ENV=production
APP_BASE_URL=https://app.seudominio.com
BILLING_PROVIDER=mercadopago
PUBLIC_PLAN_IDS=studio
PLAN_STUDIO_PRICE_CENTS=14999
MP_ACCESS_TOKEN=
MP_WEBHOOK_SECRET=
MP_COLLECTOR_ID=
```

MP_ACCESS_TOKEN é o Access Token da aplicação correta. MP_WEBHOOK_SECRET é a assinatura secreta das notificações, não o mesmo Access Token. MP_COLLECTOR_ID é opcional, para conferir a conta recebedora. Não é necessário uma Public Key no frontend, pois o checkout é hospedado. Não envie credenciais por chat, nem as coloque em GitHub/frontend.

O servidor precisa de APP_SECRET estável, R2 e SMTP para verificação de e-mail. A pessoa confirma seu e-mail antes do checkout. Ajuste os limites `PLAN_STUDIO_VIDEOS` e `PLAN_STUDIO_IMAGES` conforme sua capacidade de CPU.

## 3. Cadastrar o webhook

Na configuração da aplicação, informe a URL pública HTTPS:

`https://app.seudominio.com/api/billing/mercadopago/webhook`

Habilite os eventos de assinatura autorizada/atualizada (`subscription_preapproval`), cobrança recorrente (`subscription_authorized_payment`) e pagamento (`payment`), conforme os nomes apresentados no painel atual. Configure o segredo correspondente no host. O código exige `x-signature`, `x-request-id` e `data.id`, valida HMAC SHA-256 e janela de cinco minutos. Notificações antigas/IPN sem assinatura não liberam acesso.

## 4. Homologar antes de cobrar

Use o fluxo e contas de teste oficiais disponíveis ao produto/conta; vendedor e comprador de teste devem ser distintos, conforme instruções Mercado Pago. Alguns produtos de assinatura impõem restrições de sandbox e precisam de configuração específica; valide isso na sua conta, sem iniciar cobranças reais automaticamente.

Verifique:

- Cliente novo não tem acesso comercial só por abrir a página de retorno.
- Checkout mostra R$149,99 BRL por mês e pertence à aplicação correta.
- `authorized` na assinatura confirma autorização de cobrança, não pagamento. O código só libera após consultar uma cobrança e seu pagamento `approved` na API, verificando proprietário, valor, moeda e período.
- Webhook inválido/expirado é recusado; replay não repete a liberação nem cria uma cobrança.
- Pagamento aprovado libera Studio; o período é um mês civil a partir da aprovação.
- Cancelar renovação usa a API do provedor e preserva um período já pago. Reembolso integral/chargeback atualiza o período correspondente; outras parcelas pagas válidas permanecem consideradas.
- Inadimplência não cria um novo período pago; após o vencimento a criação/publicação comercial é bloqueada.
- Excluir a conta cancela a recorrência antes de concluir a limpeza.

Os contratos acima têm testes automatizados com mocks, não homologação real na conta Mercado Pago. Nenhuma cobrança real foi executada nesta entrega. Não anunciar o gateway como homologado antes deste checklist.

## 5. Ativar a produção

Quando a conta estiver habilitada e os testes concluídos, configure o conjunto correto de credenciais de produção e webhook no host. Faça uma validação real somente com autorização consciente. Confira relatórios e tarifas no painel Mercado Pago.

O código é gratuito, mas **Mercado Pago cobra tarifas** conforme o produto, recebimento e sua conta. Sem preços ilimitados ou promessa de margem; a cobrança de R$149,99 não elimina custos de processamento, hospedagem ou armazenamento.

## Operação

O histórico aparece em Conexões e planos. A ação Gerenciar assinatura permite cancelar a renovação Mercado Pago. A aplicação guarda identificadores e estados de cobrança, não cartões. O Stripe anterior permanece para contratos legados; novas contratações usam o gateway selecionado.

Se houver falha, a resposta ao usuário é sanitizada. Confira disponibilidade do host, relógio UTC, rota HTTPS, assinatura configurada, permissões da aplicação e recursos na própria conta. Não publique payloads com dados financeiros ou tokens em issues.
