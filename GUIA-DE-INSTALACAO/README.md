# Comece por aqui — AUTO POSTS

Há duas edições do mesmo aplicativo: comercial por R$149,99/mês e demonstração sem cobrança. Ambas criam e publicam automaticamente após configuração inicial e autorização. A narração padrão é Kokoro em CPU: feminina brasileira (Dora), com opção masculina (Alex).

## Ordem de configuração

Se o site será publicado no Vercel, siga primeiro [a configuração da entrada e do backend](../docs/hospedagem/VERCEL.md). A interface usa uma entrada própria e depende do host CPU persistente para as funções do SaaS.

1. Leia [hospedagem e R2](../docs/hospedagem/README.md). R2 armazena arquivos, não executa o backend/FFmpeg. É necessário um processo CPU sempre disponível para cumprir horários.
2. Escolha [com assinatura](../edicoes/com-assinatura/README.md) ou [demonstração](../edicoes/demonstracao/README.md). Preserve .env, chave e volume de cada edição.
3. Instale Python/FFmpeg e dependências com scripts/install.sh; execute scripts.configure_editions para preparar configurações e segredos locais, sem exibi-los.
4. Configure [Cloudflare R2](../docs/hospedagem/R2.md). Bucket privado, Access Key ID e Secret Access Key S3. O teste real só está confirmado quando emitir R2_ROUNDTRIP_OK.
5. Ative [narração CPU gratuita](../docs/ias-gratuitas/INSTALAR.md). Instalação/modelos uma vez; não requer chave de API paga.
6. Na edição comercial, configure [Mercado Pago](../docs/mercado-pago/README.md). Na demo não existe cobrança.
7. Configure Instagram oficial e SMTP conforme docs/OPERATIONS.md: APP_ID/SECRET, callback HTTPS, conta profissional, permissões/revisão do app. Não envie chaves por chat/GitHub.
8. Cadastre uma conta individual, conecte o Instagram, envie fotos e prompt, escolha voz e ative o piloto. A primeira criação começa e as próximas seguem o horário diário. Sem intervenção para montar ou publicar cada conteúdo. Pausar/cancelar continua disponível.
9. Homologue uma publicação real autorizada de imagem e Reel, pagamentos em teste, entrega de e-mail e limpeza R2. Não venda antes de confirmar esses fluxos externos.

## O que "gratuito" significa

Código, FFmpeg e modelos padrão não exigem API paga. Isso não garante capacidade gratuita ilimitada, disponibilidade de um host grátis, nem elimina tarifas Mercado Pago ou cobranças por uso excedente do R2. A versão de demonstração não exige assinatura do cliente; os recursos usados por ela continuam sujeitos aos limites do host.

Veja [pesquisa de modelos e licenças](../docs/ias-gratuitas/README.md), [relatório da entrega](../docs/STUDIO_VALIDATION.md) e [operação](../docs/OPERATIONS.md). Não há promessa de vídeos generativos indistinguíveis da realidade: o modo padrão usa suas fotos reais com movimento, texto e voz sintetizada.

A atualização mais recente inclui recuperação de rascunho, progresso da criação e reenvio seguro após queda de conexão. Veja [as melhorias e como atualizar sem apagar dados](../docs/STUDIO_UPGRADES.md).
