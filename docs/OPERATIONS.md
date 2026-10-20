# Operação e publicação

## Limites desta entrega

O fluxo principal é: campanha autorizada → roteiro → vídeo MP4 → fila persistente → publicação no Instagram. A versão inicial produz vídeos com texto sobre fundos ou imagens fornecidas; não gera locução nem cenas cinematográficas. O modo de textos fornecidos funciona sem IA; o modo IA envia o contexto da campanha à API OpenAI e depende de uma chave válida e de saldo.

O servidor precisa permanecer ligado para gerar e publicar nos horários. A aplicação usa SQLite e arquivos locais, com um processo de API e seus agendadores internos. Execute uma instância com `--workers 1`. Os bloqueios de processo evitam dois consumidores no mesmo diretório; não tornam a arquitetura distribuída. Escalar para múltiplos servidores exige outro desenho de armazenamento e fila.

Os planos são cotas de criação mensal: gratuito com 3 vídeos e Pro com 100. Gerações de prévia entram na cota. A ativação do plano depende de notificações verificadas do Stripe.

## Configurar a hospedagem

1. Escolha um host Linux com disco persistente e capacidade para FFmpeg. O projeto inclui `Dockerfile` e `compose.yaml`; nenhum serviço de nuvem ou conta paga é criado por esses arquivos.
2. Configure domínio e HTTPS em um proxy reverso. Encaminhe ao serviço na porta 8000, preserve o cabeçalho `Host` e permita o tráfego de `/api`, `/media` e arquivos estáticos. O proxy deve suportar uploads de pelo menos 10 MB e entrega de vídeos.
3. Configure `APP_ENV=production`, `APP_BASE_URL` com a origem HTTPS pública e `APP_SECRET` com um segredo aleatório estável de pelo menos 32 caracteres. Use o gerenciador seguro de segredos da hospedagem; não inclua valores no Git.
4. Garanta persistência de `DATA_DIR`. O Compose usa o volume `autoposts-data`; remover esse volume apaga banco, uploads e vídeos. Não execute `docker compose down --volumes` para uma atualização normal.
5. Inicie uma instância e valide `/health`, cadastro/login e uma prévia de campanha antes de conectar contas reais. Reinicie o processo e confirme que os dados permanecem.

A URL pública deve servir o vídeo em `/media/{token}.mp4` para a Meta buscar. O token nessa URL concede acesso ao arquivo, portanto trate a URL como privada e evite gravá-la em analytics ou logs externos. Não coloque todo o aplicativo atrás de uma autenticação do proxy que impeça a Meta de acessar essa rota. O painel e o download autenticado continuam exigindo a sessão do dono.

Publicar uma configuração de ambiente de desenvolvimento não implanta automaticamente o SaaS em uma hospedagem pública. O deploy externo, o domínio e os serviços pagos devem ser revisados e autorizados separadamente.

### Construção atrás de proxy com CA corporativa

Se a rede usa uma autoridade certificadora própria, o `pip` dentro da construção Docker pode rejeitar a cadeia TLS. Forneça o bundle de CAs confiável administrado pelo ambiente como segredo de construção BuildKit; não use `--trusted-host`, não desative TLS e não copie credenciais para a imagem.

```bash
docker build --secret id=build_ca,src=/etc/ssl/certs/ca-certificates.crt -t autoposts:local .
```

Esse caminho é o bundle público de confiança do host no ambiente Linux atual; em outra máquina, use o bundle indicado pelo administrador da rede. O Dockerfile passa o arquivo temporário ao `pip` por `PIP_CERT` somente quando o segredo foi fornecido. O arquivo montado não é copiado para a imagem e não inclui os arquivos `.env` do projeto. Fora dessa rede, `docker build -t autoposts:local .` continua usando a verificação TLS padrão.

Essa opção cobre o download de dependências na construção. Uma hospedagem que também exija CA própria durante a execução deve fornecer seu bundle de confiança separadamente ao processo, por montagem somente leitura e configuração de confiança suportada; não suponha que um segredo temporário de construção configure a rede de execução.

## Instagram Login e permissões Meta

Cadastre um aplicativo Meta compatível com **Instagram API with Instagram Login**. Use uma conta profissional do Instagram que tenha acesso autorizado ao aplicativo. O fluxo solicita `instagram_business_basic` e `instagram_business_content_publish`.

Configure os seguintes valores no ambiente do servidor:

- `INSTAGRAM_APP_ID` e `INSTAGRAM_APP_SECRET` do mesmo aplicativo.
- `INSTAGRAM_REDIRECT_URI` igual a `APP_BASE_URL` seguido de `/api/integrations/instagram/callback`, também cadastrado exatamente no aplicativo Meta.
- `INSTAGRAM_GRAPH_VERSION` correspondente à versão suportada pelo aplicativo; o padrão do código é `v25.0`.

Para uso além das contas de desenvolvimento/teste, a Meta pode exigir aplicativo em modo ativo, revisão das permissões, verificação empresarial, domínio, política de privacidade e instruções de exclusão de dados. Confirme os requisitos atuais no painel Meta. Ter as variáveis configuradas não garante que essas permissões foram concedidas.

Cada cliente deve conectar sua própria conta pelo botão no painel e consentir no fluxo OAuth. Não copie tokens de outras contas nem solicite senhas do Instagram. Os tokens são criptografados no banco com uma chave derivada de `APP_SECRET`. Alterar ou perder `APP_SECRET` torna os tokens anteriores ilegíveis; a recuperação exige restaurar a chave original ou reconectar as contas.

Os scripts e o contêiner desativam o log de acesso do Uvicorn para não registrar códigos OAuth, estado da autorização ou URLs de mídia. Aplique a mesma regra no proxy reverso: não registre query strings dos callbacks ou os tokens da rota de mídia. Use eventos de aplicação sem tokens, cookies, segredos e corpos sensíveis para observar as falhas.

Tokens e permissões podem expirar ou ser revogados. O código tenta renovar tokens de longa duração próximos da expiração quando já têm idade suficiente para renovação; a API pode rejeitar essa operação. Se o Instagram rejeitar uma publicação, o painel deve exibir a falha e o cliente pode precisar reconectar a conta. A operação 100% automática pressupõe autorização ainda válida, serviço ativo e disponibilidade das APIs; nenhuma integração elimina essas dependências externas.

Destinos HTTPS necessários: `www.instagram.com` para autorização no navegador, `api.instagram.com` para troca do código e `graph.instagram.com` para tokens e publicação. Instalação usa os registries oficiais de pacotes e a construção Docker usa o registry Docker e mirrors Debian.

## IA

Configure `AI_API_KEY` no ambiente seguro do servidor e, opcionalmente, `AI_MODEL` (padrão `gpt-4.1-mini`). A chamada usa `api.openai.com`. A geração pode ter custo por uso. Não coloque a chave no navegador, não faça commit e não use valores de demonstração como credenciais.

Revise assuntos, tom, chamadas para ação e direitos sobre o conteúdo antes de ativar uma campanha. Não há revisão humana obrigatória de cada vídeo após a ativação: esse é o comportamento solicitado pelo produto. Se desejar avaliar o resultado primeiro, use a prévia e mantenha a campanha desativada.

## Stripe opcional

Configure um produto e um preço recorrente no Stripe, primeiro no modo de teste. Preencha `STRIPE_SECRET_KEY` e `STRIPE_PRICE_ID` da mesma conta e modo. Registre o endpoint público `APP_BASE_URL/api/billing/webhook` e configure seu `STRIPE_WEBHOOK_SECRET`.

O aplicativo verifica a assinatura do corpo original e registra identificadores de eventos para impedir reaplicação. O retorno do navegador após checkout não promove a conta. Cadastre os eventos `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated` e `customer.subscription.deleted`; o estado de assinatura confirmado pelo servidor determina o plano. Faça um teste completo com o modo de teste do Stripe antes de cobrar clientes.

O portal de cobrança precisa estar habilitado na conta Stripe. O destino HTTPS da API é `api.stripe.com`; as páginas de checkout e portal são abertas pelo navegador em `checkout.stripe.com` e `billing.stripe.com`. O código não cria o produto, não determina preço e não executa uma compra durante a instalação. `STRIPE_WEBHOOK_SECRET` e `APP_SECRET` precisam de valores locais reais para assinatura e criptografia; um marcador de credencial substituído apenas pelo proxy de saída não atende a esse uso local.

## Pausar, recuperar e evitar duplicação

- Pausar uma campanha impede novas gerações automáticas e retira da fila os itens dela que ainda podem ser pausados. Uma publicação já enviada à Meta pode concluir; confira o painel e o Instagram antes de repetir qualquer ação.
- As filas e os identificadores dos containers Meta ficam no SQLite. Reiniciar não deve criar uma segunda campanha nem outro post para o mesmo horário.
- Uma falha ambígua durante a confirmação de publicação exige conferência no Instagram. Não apague o identificador do container nem tente forçar outra publicação para “destravar” o item.
- Uma instância desligada não publica no horário. Após reiniciar, a recuperação limita o trabalho atrasado; não se deve esperar uma avalanche de todos os horários perdidos.
- Verifique uso de disco periodicamente. MP4 e uploads são persistentes; este MVP não implementa descarte automático por prazo.

## Backup e atualização

Faça backup de `DATA_DIR` e guarde `APP_SECRET` separadamente em um cofre. O banco, os arquivos e a chave devem corresponder à mesma instalação. Os backups contêm dados de clientes e tokens criptografados; limite o acesso e teste a restauração em um ambiente isolado.

Para copiar todo o diretório sem uma cópia SQLite inconsistente, pare o serviço antes do backup. No Compose:

```bash
docker compose stop app
# Faça uma cópia verificada do volume autoposts-data usando a ferramenta de backup do host.
# Preserve também APP_SECRET no gerenciador seguro de segredos.
docker compose start app
```

Para atualizar, preserve o volume e a configuração, faça backup, reconstrua a imagem e inicie o serviço. Não execute múltiplas versões ao mesmo tempo contra o mesmo banco. A inicialização cria as tabelas necessárias, mas o projeto ainda não possui um sistema geral de migrações para alterações futuras de schema.

## Verificações

```bash
./scripts/install.sh
.venv/bin/python -m pytest -q
./scripts/start.sh
```

Em outro terminal, faça requisições locais a `/health` e ao fluxo de cadastro, campanha e prévia. Verifique que um MP4 real foi produzido e que renderizar uma prévia não publica. Depois de configurar serviços externos, valide OAuth, publicação em conta de teste, assinatura do webhook e atualização do plano com credenciais de teste. Testes com respostas simuladas não comprovam acesso real às contas desses provedores.

Cadastro aberto, recuperação de senha, confirmação de e-mail, política de privacidade, termos, exclusão/portabilidade de dados, monitoramento e atendimento precisam de uma revisão de lançamento antes de aceitar clientes em produção. O projeto não afirma que aprovações Meta, cobranças reais ou deploy externo foram concluídos apenas porque os testes locais passaram.
