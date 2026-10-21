# Arquitetura e auditoria da entrega

## Base preservada

A base `0a457db` continha FastAPI, interface JavaScript, autenticação, SQLite, renderização FFmpeg, campanhas, OAuth Instagram, Stripe Pro e testes. Os scripts B2 e de render remoto haviam sido adicionados ao main. Foram mantidos os fluxos existentes, acrescidos de migrações aditivas. Não se apagou a versão anterior nem se substituiu o frontend por uma segunda aplicação.

## Problemas tratados

- Configuração S3 implícita: agora endpoint/região explícitos, SigV4, path addressing, corpo com tamanho e MD5, checksums compatíveis, sem handshake Expect opcional e TLS verificado. Dependências estão fixadas.
- Upload não integrado ao fluxo principal: agora o job só conclui após confirmação do objeto; falha temporária preserva cache e agenda retry.
- Processadores de exemplo: render remoto recebe o proprietário da tarefa reservada; não atribui clientes a `admin`. Demo isolada só executa em main.
- Estado de geração só em posts: fila SQL com lease aleatório, exclusividade transacional, fencing, limite de tentativas e recuperação de interrupção.
- Somente vídeos/Pro: imagens reais, quatro planos, limites separados, período de cobrança, checkout pendente e histórico.
- Conta sem recuperação: tokens de uso único armazenados por hash, SMTP, revogação de sessões, troca de senha e exclusão assíncrona.
- Senhas legadas: verificação compatível e atualização no login para scrypt N32768/r8/p3; concorrência limitada.
- Arquivos sem retenção remota: outbox de exclusão, purga das versões do objeto e confirmação; nunca remover publicações já feitas no Instagram.
- Regeneração sem débito: resultado já gerado exige novo crédito; exclusão não reduz o ledger.

## Fonte de verdade e execução

`DATA_DIR/autoposts.db` em volume persistente é o único banco. `schema.py` adiciona campos/tabelas sem recriar dados. B2 contém apenas mídia, não uma segunda base de usuários. API e worker compartilham o SQLite. Um processo Uvicorn e um worker por volume, com lock de processo; não escale horizontalmente esta instalação.

A fila usa estados pending, processing, completed e failed. O claim usa BEGIN IMMEDIATE e lease de 900 segundos. Tentativas temporárias usam backoff e cache; após três, falha explícita. Um callback remoto precisa de segredo de serviço, lease vigente e confirmação de tamanho, SHA-256 e versão no B2. A chave de mídia inclui proprietário e versão de geração, para a limpeza anterior não apagar uma regeneração.

O scheduler persiste horários UTC e fuso IANA. As campanhas geram no horário configurado e publicam após render/upload; podem atrasar com carga, rede ou processamento da Meta. Não há garantia de publicação no segundo exato. Pausar cancela pendências que ainda não começaram; operação já entregue à Meta pode terminar. Se houver crash durante publicação ambígua, o serviço sinaliza falha e pede conferência, sem reenviar cegamente.

## Segurança e limites operacionais

Sessões em cookies HttpOnly/SameSite, Secure em HTTPS, CSRF em mutações, conteúdo escapado/CSP, autorização por proprietário, uploads normalizados e limitados. Tokens Instagram criptografados com chave derivada do APP_SECRET estável. URLs B2 são capacidades temporárias: quem receber uma URL poderá usá-la até expirar; o bucket continua privado. Chaves S3 brutas só no servidor/Actions, nunca no frontend.

SMTP usa TLS em produção. Webhooks Stripe verificam assinatura, timestamp e replay; assinatura é consultada no provedor, não concedida pelo retorno do checkout. Starter exige e-mail verificado e cartão; hash de e-mail usado no teste persiste após exclusão, sujeito à política legal do operador.

Retenção protege mídia pendente e logos de campanhas ativas, registra eventos e deixa exclusões B2 com falha em fila. Até a confirmação pode haver armazenamento remoto pendente de remoção. Backups e registros financeiros exigem política final do operador.

## Limites restantes

Não há cluster, autoscaling, recuperação automática de desastre, SLA ou migração para Postgres/D1. Texto animado por palavra, narração e geração de vídeo por modelo de IA não foram implementados; os vídeos usam imagens/textos com movimento e transições. IA opcional gera roteiro textual. O deploy real e validações de fornecedores dependem de contas/configurações externas. Cloudflare Workers Free não hospeda este processo Python/FFmpeg.
