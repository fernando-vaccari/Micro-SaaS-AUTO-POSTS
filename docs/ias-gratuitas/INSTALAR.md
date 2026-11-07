# Instalar narração gratuita em CPU

## Padrão Docker — sem GPU

```bash
.venv/bin/python -m scripts.configure_editions
docker compose -f compose.yaml -f compose.ai.yaml up -d --build
```

AI_VOICE_ENGINE=kokoro é o padrão. O serviço usa kokoro-onnx 0.6.1 e dependências fixadas em ai_worker/requirements-kokoro.lock.txt. Não instala Torch/CUDA para a narração padrão. Os modelos oficiais (~354 MB no total) são baixados uma vez e conferidos por SHA-256. O serviço não exige chave de API paga.

O app recebe AI_MEDIA_URL=http://ai:8005 e AI_MEDIA_TOKEN privado da configuração. Não exponha essa porta no navegador/internet; o token fica no servidor. O limite de 12 GB no compose é teto de contenção, não requisito do Kokoro: teste real do processo ficou em cerca de 565 MB. A demo usa teto de 2 GB para IA. Some consumo da API/FFmpeg ao dimensionar o host.

Se o host usa proxy/CA empresarial, monte a CA confiável como BuildKit secret build_ca em cada etapa de rede; nunca use --insecure. Exemplos no guia de operação.

## Instalação local

```bash
UV_CACHE_DIR=/tmp/autoposts-uv-cache uv venv --python python3 .venv-ai
UV_CACHE_DIR=/tmp/autoposts-uv-cache uv pip sync --python .venv-ai/bin/python ai_worker/requirements-kokoro.lock.txt
.venv-ai/bin/python -m scripts.download_voice_models
```

Configure no processo IA e no backend o mesmo AI_MEDIA_TOKEN forte, sem imprimi-lo. Configure AI_MEDIA_URL=http://127.0.0.1:8005 no backend, AI_VOICE_ENGINE=kokoro e KOKORO_MODEL_DIR com o caminho absoluto de .models/kokoro no processo IA. Inicie:

```bash
.venv-ai/bin/python -m uvicorn ai_worker.app:app --host 127.0.0.1 --port 8005 --workers 1 --no-access-log
```

O script configure_editions já prepara o token em .env/.env.demo. Use um gerenciador de processos que injete as variáveis privadas; não cole o token em comandos compartilhados ou logs. A execução principal continua em .venv, com ./scripts/start.sh ou scripts.start_demo.

No estúdio, selecione **Voz feminina natural · Kokoro** (padrão) ou **Voz masculina natural · Kokoro**. O texto é narrado automaticamente e entra na trilha AAC do Reel. Se o texto exceder 59 segundos de áudio, a tarefa falha com orientação para encurtar, sem cortar sua frase silenciosamente. A duração do vídeo acomoda a narração, até 60 segundos.

## Clonagem opcional

AI_VOICE_ENGINE=chatterbox ou qwen3 exige reconstruir o serviço com os requisitos correspondentes, mais pesados; não está no perfil CPU leve padrão. O compose passa o build arg e a variável ao serviço. Esses caminhos necessitam downloads do Hugging Face, acesso à rede e memória. O perfil Chatterbox é separado do Kokoro ONNX por incompatibilidade das versões de NumPy exigidas pelos pacotes; nesse perfil a interface oferece clonagem, sem prometer vozes Kokoro no mesmo processo. O perfil padrão recomendado continua sendo Kokoro. Não foram testados com a voz do usuário nesta entrega.

Cadastre sua própria amostra de 3–30 segundos, confirme autorização e selecione o modo clonado. A amostra é cifrada antes de salvar no disco/R2, não é pública e pode ser revogada. O modelo Chatterbox mantém o watermark Perth. A opção **gravação original** não clona: usa o áudio real enviado, independentemente do prompt.

## Variação de imagens

O serviço pode oferecer /image com Stable Diffusion 1.5, habilitado por AI_IMAGES_ENABLED=true, mas o perfil Kokoro leve não instala os pacotes de difusão. Use um ambiente separado com torch CPU, diffusers, transformers compatíveis e modelos instalados; revise a licença dos pesos. Não habilite a opção no painel antes de homologar a inferência. Fotos reais com composição são o caminho padrão já testado.
