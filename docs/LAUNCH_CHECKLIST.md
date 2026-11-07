# Antes de comercializar

## Código validável sem contas externas

- [x] Conta, autenticação, isolamento, CSRF e recuperação com transporte SMTP simulado.
- [x] Campanhas, frequência semanal, prévia, pausas e estados persistentes.
- [x] JPEG e MP4 reais; preview e download privados.
- [x] Fila atômica, retries, leases, quotas e falha de upload sem conclusão.
- [x] Contratos Meta e Stripe com mocks, não equivalentes a homologação real.
- [x] Retenção, exclusão pendente e ferramenta de backup consistente.
- [x] Deploy Docker/Caddy preparado, sem recursos pagos provisionados.

## Configuração externa obrigatória

- [ ] Corrigir par B2_KEY_ID/B2_APPLICATION_KEY nos Secrets; obter B2_ROUNDTRIP_OK no workflow manual e testar aplicação no bucket privado.
- [ ] Host sempre ligado, DNS, HTTPS, volume, firewall, backups fora do host e alertas de falha/custo.
- [ ] APP_SECRET estável/seguro; B2 e outras chaves no gerenciador seguro do host.
- [ ] SMTP: remetente autenticado e entrega real de verificação/recuperação.
- [ ] Meta: app com Instagram Login, redirects, URLs legais, conta profissional, roles, permissões e Advanced Access/revisão quando exigida.
- [ ] Autorizar e conferir uma imagem e um Reel reais; validar renovação/revogação e campanha ao longo do tempo.
- [ ] Stripe sandbox: quatro planos/Prices BRL mensais, portal, webhook assinado, renovação, cancelamento, inadimplência, trial e mudança de plano.
- [ ] Stripe produção: conta habilitada, preços/chaves/webhook corretos e decisão do operador antes de cobrança real.
- [ ] Preencher LEGAL_OPERATOR_NAME/LEGAL_CONTACT_EMAIL; revisar documentos, LGPD, retenção financeira/backups, suporte, impostos e reembolsos.
- [ ] Definir capacidade por cliente e margem de CPU, armazenamento, egress, IA opcional e tarifas de pagamento.

Não anunciar o SaaS como pronto para venda antes de completar as validações externas essenciais.
