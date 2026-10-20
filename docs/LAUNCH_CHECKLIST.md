# Checklist de lançamento

Esta lista separa o aplicativo implementado das autorizações e capacidades que precisam existir para operar um SaaS público. Os documentos em `docs/legal/` são rascunhos; não são páginas públicas nem substituem a identificação do operador.

## Hospedagem e operação

- [ ] Escolher e autorizar hospedagem, domínio e custos recorrentes.
- [ ] Configurar HTTPS público, proxy reverso e `APP_BASE_URL` com a origem final.
- [ ] Guardar `APP_SECRET` estável no cofre da hospedagem, sem versionar ou compartilhar em chat.
- [ ] Configurar volume persistente, limites de recursos, alerta de disco e uma única instância do agendador.
- [ ] Testar backup e restauração do banco, dos vídeos e da chave em ambiente isolado.
- [ ] Configurar monitoramento de saúde, falhas de geração/publicação e um canal de atendimento.
- [ ] Definir retenção dos uploads, vídeos, históricos e backups e como aplicar exclusões.

## Meta e Instagram

- [ ] Criar/configurar o aplicativo Meta e cadastrar o callback HTTPS exato.
- [ ] Conectar uma conta profissional de teste e verificar OAuth e publicação real autorizada.
- [ ] Publicar URLs acessíveis de privacidade, termos e instruções de exclusão com dados reais do operador.
- [ ] Concluir as revisões de permissões, verificações e modo ativo que a Meta exigir para contas de clientes.
- [ ] Testar revogação/expiração de acesso e confirmar que a falha fica visível sem duplicar posts.

## IA e automação

- [ ] Autorizar provedor/modelo, orçamento e limites da chave `AI_API_KEY`.
- [ ] Gerar prévias representativas e validar legibilidade, conteúdo e duração antes de ativar campanhas.
- [ ] Confirmar no produto que o cliente entende que ativar autoriza geração e publicação sem aprovação por post.
- [ ] Testar pausa, reinicialização e recuperação de fila na instalação final.

## Cobrança, quando habilitada

- [ ] Definir produto, preço, condições comerciais e impostos da operação.
- [ ] Configurar Stripe em modo de teste e validar checkout, assinatura de webhook, plano e cancelamento.
- [ ] Habilitar e testar o portal de cobrança.
- [ ] Autorizar a troca para chaves/preço de produção somente após o teste completo.

## Clientes e documentos

- [ ] Identificar razão social/nome do operador, registro aplicável, contato e jurisdição.
- [ ] Revisar e preencher os rascunhos de privacidade, termos e exclusão de dados.
- [ ] Implementar confirmação de e-mail e recuperação de senha antes de abrir cadastro público.
- [ ] Definir e testar o atendimento de exclusão, portabilidade e desconexão de integrações.
- [ ] Revisar cadastro aberto, proteção contra abuso e limites para o volume esperado de clientes.

O código não provisiona essas contas nem fornece aprovação Meta. Uma configuração de desenvolvimento salva ou uma imagem Docker construída não comprova publicação externa, credenciais válidas, cobranças ou aprovação para uso por clientes.
