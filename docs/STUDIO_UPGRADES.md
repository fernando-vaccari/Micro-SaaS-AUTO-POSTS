# Melhorias do estúdio e da automação

Estas melhorias continuam na branch `feat/voice-photo-studio`, sem substituir o projeto ou apagar contas, campanhas e arquivos existentes.

## Reenvio seguro após falha de conexão

Se a internet cair depois que o servidor aceitar a criação, recarregue e envie novamente na mesma aba. O estúdio recupera a tentativa e devolve o conteúdo já criado, sem cadastrar outra campanha, renderização ou consumo de crédito para a mesma solicitação.

A publicação, a reserva de consumo e a entrada na fila são gravadas na mesma transação. Uma falha durante esse cadastro desfaz essas alterações. Falhas posteriores de renderização continuam com as regras de tentativa da fila; isso não promete restituição automática de créditos após processamento.

Para integração com a API, `POST /api/studio` aceita `Idempotency-Key` de 16–128 caracteres ASCII, usando letras, números, `_` e `-`. Gere uma chave nova para cada criação deliberadamente nova e reutilize-a apenas nas tentativas da mesma criação. A proteção também cobre solicitações simultâneas e reinício do servidor, com isolamento por usuário.

| Resultado | Resposta |
|---|---|
| Primeira criação aceita | 201 |
| Repetição da mesma tentativa e conteúdo | 200, `Idempotency-Replayed: true`, mesmo identificador |
| Mesma chave com conteúdo diferente | 409 |
| Criação/campanha excluída | 410, sem recriação automática |
| Chave malformada | 400, sem consumir crédito |

Clientes antigos sem esse cabeçalho continuam funcionando, mas não recebem a proteção de reenvio. A aplicação oficial já o envia. O registro guarda o hash do pedido e identificadores; não duplica fotos, vídeos ou credenciais.

## Rascunho temporário e troca de contas

Fotos selecionadas, texto, voz escolhida e tentativa pendente ficam na sessão da aba do navegador, separados por usuário. Recarregar a página preserva o trabalho. O botão **Limpar rascunho** começa outra configuração sem excluir conteúdos/campanhas já criados.

Sair, expirar a sessão ou excluir a conta limpa o rascunho e os dados privados da interface. Respostas atrasadas de uma sessão anterior não repovoam o painel da conta seguinte. Áudio ainda não salvo não é persistido pelo rascunho; nenhuma credencial de nuvem ou de pagamento vai para esse armazenamento.

## Conteúdo e progresso

- O texto completo é distribuído entre as cenas; uma única foto pode reaparecer em cenas diferentes, sem descartar a mensagem final. Todas as fotos escolhidas continuam participando da composição.
- Campos em branco, fotos duplicadas, voz sem gravação selecionada e fuso inválido recebem erro de validação, em vez de erro interno.
- Títulos de até 120 caracteres funcionam com o piloto; o nome da campanha respeita seu limite de 80 caracteres.
- O painel **Sua última criação** mostra fila, produção, repetição automática, biblioteca e publicação a partir dos estados reais. Não inventa porcentagem ou tempo de conclusão. Ele atualiza sem apagar o texto em edição.
- A preparação das edições preserva também uma chave local anterior da demo, evitando invalidar gravações e tokens cifrados existentes.

## Verificação

177 testes Python aprovados, incluindo concorrência, consumo único, isolamento por cliente, rollback e preservação das cenas. Sintaxe Python/JavaScript verificada.

O teste local `scripts/smoke_studio_reliability.py` usou Chromium e banco demo isolado. Ele aceitou uma criação no servidor, derrubou a confirmação no navegador, recarregou e reenviou: o mesmo pedido retornou 200, mantendo um conteúdo e um crédito. Também verificou rascunho, progresso, mobile sem overflow, logout e resposta atrasada de outra conta.

O fluxo de `scripts/smoke_studio_browser.py` foi repetido com Kokoro real: cadastro, foto, narração feminina, MP4 1080×1920 com AAC e biblioteca. Capturas novas em `docs/screenshots/studio-progress-*.png`. Os scripts de navegador são opcionais e exigem Playwright/Chromium; não são dependências de produção.

Nenhuma publicação Meta, cobrança Mercado Pago ou operação R2 real foi feita nesta atualização. Configuração de credenciais, HTTPS e host CPU persistente continua necessária. O processamento ocorre no servidor; o notebook pode permanecer desligado enquanto esse servidor estiver ativo.

## Atualizar a instalação

Faça um backup consistente do banco, mídias e chave conforme `OPERATIONS.md`. Atualize a branch no host, reconstrua/reinicie a edição instalada e preserve o arquivo `.env` e seu volume. As migrações são aditivas e executadas na inicialização; a tabela de tentativas não exige zerar banco ou recriar clientes. Não execute `docker compose down -v` ao atualizar.

Consulte [instalação](../GUIA-DE-INSTALACAO/README.md), [hospedagem](hospedagem/README.md) e [situação completa](STUDIO_VALIDATION.md).
