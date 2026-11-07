# AUTO POSTS Studio — relatório da entrega (7/11/2026)

## Implementado e testado

- **175 testes automatizados aprovados**, incluindo os anteriores. Um aviso de depreciação Starlette/httpx sem falha funcional. Os contratos antigos Stripe continuam testados explicitamente; as novas contratações usam Studio/Mercado Pago.
- Atualização de confiabilidade: criação atômica com reenvio idempotente, rollback de cadastro/fila/cota, rascunho temporário por usuário, progresso real e proteção contra respostas atrasadas de outra sessão. Teste Chromium simulou perda de resposta após commit, recarga e repetição sem duplicar conteúdo/crédito. [Detalhes e contrato da API](STUDIO_UPGRADES.md).
- Texto completo preservado nas cenas mesmo com uma foto, validações do estúdio corrigidas e preservação da chave local anterior da demo. Fluxo de voz Kokoro/MP4 no navegador repetido após as alterações.
- Login `/login` e cadastro `/cadastro`, conta individual, sessão/CSRF e isolamento de fotos, voz, biblioteca e campanhas entre clientes.
- Estúdio guiado com fotos, prompt, marca, narração e autorização de piloto automático. Criação inicial e rotina recorrente usam a fila persistente existente. Teste sem Meta real demonstrou campanha → geração → arquivo pronto → agendamento automático.
- **Kokoro ONNX real em CPU**, feminina PT-BR Dora e masculina PT-BR Alex. Pesos oficiais conferidos por SHA-256. Amostras reais no frontend; medição observada em docs/ias-gratuitas/. Não é voz clonada do usuário nem avaliação de indistinguibilidade humana.
- Vídeo real vertical 1080×1920, H.264, AAC; o renderer normaliza áudio para 48 kHz/stereo. Teste de sinal confirma áudio audível, além da presença de uma trilha AAC. Texto e fotos são compostos com movimento/transições; imagens estáticas em JPEG.
- Gravação/upload de voz própria (WAV/WebM/Ogg/MP3/M4A), consentimento explícito, normalização, arquivo cifrado, acesso privado, revogação e limpeza. Chromium com microfone **sintético**, sem gravar pessoa real, exercitou gravar → WebM → normalizar → salvar consentimento.
- Edição comercial por R$149,99 e demo com a mesma interface/código, dados/chave/volume separados. A demo permite publicação real autorizada e bloqueia checkout, portal e webhooks de cobrança no servidor. Parâmetros do navegador não habilitam demo na edição comercial.
- R2: configuração SigV4/auto/HTTPS, confirmação de upload, URLs assinadas e exclusão sem versionamento S3. Testes com mocks; objetos B2 legados continuam usando o provedor correto. A migração preserva pedidos de exclusão existentes e distingue a mesma chave em dois fornecedores.
- **Expiração 10h após geração**, mesmo com usuário ativo, proteção de trabalhos pendentes e outbox de exclusão. Cache e objetos remotos são tratados; metadados/cobrança/consumo permanecem. Fotos necessárias às campanhas e amostras autorizadas não somem a cada dez horas.
- Mercado Pago: preço BRL mensal, checkout hospedado, confirmação por HMAC + consulta autoritativa de assinatura/pagamento, proteção de replay, período, cancelamento de renovação e reembolso. O estado authorized da assinatura não é tratado como pagamento aprovado.
- Docker: imagens API e Kokoro construídas com TLS/CA confiável; processos sem privilégios. Teste **entre containers** demonstrou demo, cadastro/CSRF, foto, inferência Kokoro privada, geração/download de MP4 H.264/AAC e bloqueio de cobrança. Corrigidos permissões de arquivos e roteamento privado de proxy encontrados nesse teste. Não foram apagados bancos/volumes de clientes para liberar cache de build.
- Três configurações Compose validadas (comercial/public, CPU e demo), cinco workflows YAML e sintaxe Python/JavaScript verificados. Preparação de .env/.env.demo repetível, preservando segredos existentes e a chave anterior de criptografia.
- Chromium: página comercial com R$149,99, página de login, cadastro demo → foto → narração feminina Kokoro **real** → MP4 de 15s → biblioteca privada; mobile 390px sem overflow e sem pageerrors. Logout limpa rascunho antes do próximo usuário. Capturas em docs/screenshots/studio-*.png. A fachada usada no teste é ilustração demonstrativa, não foto de um cliente.

## Implementado, aguardando credenciais/configuração externa

- R2 real: Account ID, bucket privado e par S3 do operador. O novo workflow manual emite R2_ROUNDTRIP_OK somente após upload/read/delete reais; ainda não foi executado com chaves R2 do usuário.
- Meta: app, conta profissional, callback HTTPS, permissões/revisão e tokens. A implementação de publicação oficial foi preservada; nenhuma publicação real foi feita nesta entrega.
- Mercado Pago: aplicação/credenciais, assinatura de webhook e configuração de notificações. A pasta docs/mercado-pago/ reúne instruções. Nenhuma cobrança real foi feita; os testes são simulados.
- SMTP: remetente e entrega real de confirmação/recuperação, já preparado no projeto.
- Host CPU com disco persistente, domínio/HTTPS e operação sempre ativa. Não foi provisionada infraestrutura paga ou emitido certificado nesta entrega. R2 não executa a aplicação, e o notebook não é necessário quando o servidor está ativo.

## Preparado, aguardando teste real específico

- Clonagem opcional Chatterbox/Qwen3: adaptadores e requisitos separados. Sem amostra real do usuário e sem avaliação de clonagem em produção. O padrão validado é voz genérica Kokoro.
- Variação de imagem SD1.5: adaptador opcional; pesos/inferência não homologados aqui. Não ativado no perfil Kokoro leve, que não instala Torch/diffusers.
- Publicação de imagem/Reel reais, renovação/cancelamento Meta, homologação do gateway e limpeza no bucket R2 do operador.
- Restore em outro host e disponibilidade contínua; backup consistente é ferramenta existente, não um serviço externo de disaster recovery.

## Não implementado / sem promessa de funcionamento

- Vídeo generativo por Wan/LTX ou pessoa virtual com sincronização labial. Modelos pesquisados e licenças documentadas; não foram apresentados como funcionalidades prontas.
- Hospedar Python/FFmpeg/ONNX dentro do R2 ou Workers Free. Não é suportado pela arquitetura. Uma conexão antiga de Workers Builds para o repo não substitui o host CPU; desative/reconfigure esse deploy legado no painel antes de usar o destino novo.
- Provisionamento automático de conta de nuvem ou garantia de hospedagem gratuita permanente, SLA e capacidade ilimitada. Tarifas de Mercado Pago e excedentes R2 não são eliminados pelo código gratuito.

## Arquivos e preservação

Base preservada em archive/pre-studio-20261107, além das branches de arquivo anteriores. Novos módulos: creative.py, studio.py, voices.py, ai_client.py, edition.py, mercadopago.py; adaptador R2 em storage.py; migrações em schema.py. Integrações de fila/render/agenda, retenção e autenticação foram estendidas, sem recriar o banco nem usar usuário global.

Frontend: studio-ui.js, studio.css, landing/autenticação/painel atualizados e exemplos de voz/ilustração locais. Infra: Dockerfile.ai, compose.ai.yaml, compose.demo.yaml, .env.demo.example e scripts de preparação/modelos/teste R2. Documentação principal em GUIA-DE-INSTALACAO/, edicoes/, docs/mercado-pago/, docs/hospedagem/ e docs/ias-gratuitas/.

O relatório anterior docs/VALIDATION.md registra a fase B2 de outubro; o diagnóstico InvalidAccessKeyId anterior não comprova sucesso de R2. Não considerar o SaaS pronto para venda antes da homologação das integrações externas e da definição de hospedagem/política legal do operador.
