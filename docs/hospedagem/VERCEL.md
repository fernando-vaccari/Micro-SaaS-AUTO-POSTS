# Vercel: entrada FastAPI e limites desta arquitetura

O erro FASTAPI_ENTRYPOINT_NOT_FOUND é resolvido por pyproject.toml, na raiz:

```toml
[tool.vercel]
entrypoint = "autoposts.main:app"
```

Não use ai_worker.app:app como entrada do site. Esse aplicativo é somente o processador privado de voz, sem o painel e as rotas do SaaS. Mantenha Root Directory na raiz do repositório e o framework FastAPI. As dependências continuam em requirements.txt. Refaça o deploy do commit que contém esta configuração.

Isso corrige a descoberta da entrada, não converte o backend em aplicação serverless pronta para produção. Esta versão inicializa SQLite e threads de renderização/agendamento, usa FFmpeg e depende de arquivos persistentes. Disco temporário de função não preserva banco, sessões e fila entre instâncias; processos em segundo plano não têm garantia de continuar depois da requisição. Apontar DATA_DIR para /tmp não resolve essa arquitetura. R2 guarda mídia, mas não substitui o banco e o processamento.

Para funcionar com o notebook desligado, hospede esta versão em um servidor CPU persistente, seguindo [o guia de hospedagem](README.md). O site e a API podem ser servidos pelo próprio backend com HTTPS. Não foi provisionado um servidor nem validado um deploy real na conta Vercel nesta correção.

Uma implantação inteiramente serverless exigiria migrar banco, execução de tarefas, agendamento e processamento de vídeo/voz. A configuração de entrada isolada não entrega isso e não garante hospedagem gratuita permanente.

Documentação oficial: https://vercel.com/docs/frameworks/backend/fastapi#exporting-the-fastapi-application
