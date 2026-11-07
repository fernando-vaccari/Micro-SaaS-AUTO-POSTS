# AUTO POSTS Studio

SaaS em português para transformar fotos do negócio e um prompt em imagens e Reels narrados, com campanhas e publicação oficial no Instagram. O estúdio foi redesenhado para desktop e celular, com login individual em `/login` e cadastro em `/cadastro`.

**Comece pela pasta [GUIA-DE-INSTALACAO](GUIA-DE-INSTALACAO/README.md).** Ela reúne os passos de hospedagem, R2, IA, Instagram e gateway. Nenhuma credencial real está no repositório.

## Duas edições, um único código

| Edição | Comportamento |
|---|---|
| [Com assinatura](edicoes/com-assinatura/README.md) | Studio R$149,99/mês; Mercado Pago preparado; acesso de produção depende de pagamento aprovado. |
| [Demonstração](edicoes/demonstracao/README.md) | Mesma interface, criação e publicação, sem exigir assinatura. Cobrança bloqueada no servidor; banco, volume e chave separados. |

Ambas permitem publicação real após conectar Instagram profissional e autorizar a campanha. Não há publicação simulada apresentada como resultado real. O plano Studio tem 20 vídeos e 40 imagens por período, com preço e cotas configuráveis. Contratos Stripe antigos foram preservados; novos clientes veem o Studio.

## Piloto automático

1. A pessoa cria sua conta, conecta o Instagram profissional, envia fotos e escreve o prompt.
2. Escolhe voz feminina (padrão recomendado), masculina ou gravação própria e autoriza o piloto.
3. O sistema reserva a tarefa, prepara roteiro/legenda, monta as cenas, sintetiza narração, gera MP4, confirma upload e publica pelo cronograma.
4. As próximas execuções seguem a campanha sem aprovação por post. É possível pausar, cancelar, mudar dias/horários e acompanhar erros/histórico.

Narração padrão: **Kokoro 82M ONNX em CPU**, PT-BR, sem API paga, com exemplo feminino e masculino incluídos. Clonagem própria Chatterbox/Qwen3 e variação SD1.5 têm adaptadores opcionais, sujeitos a instalação/modelos/homologação. [Pesquisa e licenças](docs/ias-gratuitas/README.md).

Os vídeos padrão são composições das fotos reais, com enquadramento, movimento, transições, texto e áudio. Não prometem vídeo generativo indistinguível da realidade nem sincronização labial.

## Instalar e testar

Python 3.12+, FFmpeg/libx264/ffprobe, DejaVu e tzdata:

```bash
./scripts/install.sh
.venv/bin/python -m scripts.configure_editions
./scripts/start.sh
```

Para incluir narração CPU no Docker:

```bash
docker compose -f compose.yaml -f compose.ai.yaml up -d --build
```

Demo completa com processador CPU:

```bash
docker compose --env-file .env.demo -f compose.demo.yaml up -d --build
```

Não é necessário build Node: FastAPI serve a interface. Variáveis em .env.example e .env.demo.example. O instalador de edições preserva valores existentes e reutiliza uma chave local anterior, evitando invalidar os tokens cifrados.

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q autoposts ai_worker scripts tests
node --check autoposts/static/app.js
node --check autoposts/static/studio-ui.js
```

## Cloudflare R2 e retenção

Bucket privado, credenciais S3 somente no servidor, URLs temporárias após autorização por cliente e upload confirmado por HEAD/SHA-256. O adaptador R2 usa região auto e exclusão compatível com R2, sem operações de versionamento B2. Arquivos legados B2 mantêm o provedor registrado.

**Vídeos e imagens gerados expiram após 10 horas.** Publicações pendentes ficam protegidas até o envio/cancelamento. A limpeza remove cache e objeto remoto, com fila persistente para repetir falhas. Histórico, consumo e cobranças continuam no banco. Fotos/vozes necessárias a campanhas seguem política própria. Não são apagadas publicações já realizadas no Instagram.

[Configurar R2 e teste real](docs/hospedagem/R2.md). Ainda é necessário fornecer credenciais e confirmar `R2_ROUNDTRIP_OK` na sua conta.

## Hospedar sem notebook ligado

O código inclui fila e agendadores persistentes no servidor, serviços Docker com reinício e Caddy para HTTPS. O notebook pode permanecer desligado. **R2 armazena mídia; não executa Python/FFmpeg/voz. Cloudflare Workers Free não executa este backend.** É necessário host CPU com disco persistente e serviço ativo. [Opções e limites](docs/hospedagem/README.md).

Código/modelos padrão são gratuitos, mas hospedagem gratuita não garante disponibilidade/capacidade ilimitadas. R2 tem franquias e excedentes; Mercado Pago cobra tarifas. Nenhuma infraestrutura paga foi provisionada e nenhuma cobrança real foi executada.

## Situação da entrega

Veja [STUDIO_VALIDATION](docs/STUDIO_VALIDATION.md): testes locais, evidências de voz real/MP4/navegador, arquivos modificados e integrações ainda aguardando configuração externa. Instagram, R2 e Mercado Pago devem ser homologados na conta do operador antes de vender.

[Melhorias recentes](docs/STUDIO_UPGRADES.md): tentativas repetidas não duplicam conteúdo/crédito, rascunho temporário por usuário, progresso real da criação e roteiro completo mesmo com uma única foto. A atualização preserva o banco e as integrações anteriores.

A versão anterior permanece em `archive/pre-studio-20261107`; outras versões foram preservadas nas branches de arquivo existentes. Esta entrega continua FastAPI/SQLite e o frontend existente, com migrações aditivas e isolamento entre usuários.
