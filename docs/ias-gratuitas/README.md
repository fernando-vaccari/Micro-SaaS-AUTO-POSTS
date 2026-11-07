# Pesquisa de IA gratuita e realismo — 7 de novembro de 2026

Foram consultados READMEs, licenças e exemplos oficiais dos projetos abaixo. **Não foi realizado um benchmark de qualidade entre todos eles.** Avaliações de capacidade refletem documentação dos autores; os testes reais desta entrega estão identificados separadamente.

"Modelo gratuito" não significa API gratuita ou processamento sem custo. A recomendação considera o requisito: sem GPU própria, uso comercial e assinatura de R$149,99.

## Decisão aplicada ao AUTO POSTS

**Kokoro 82M via ONNX** é a narração padrão: português brasileiro, opção feminina `pf_dora` e masculina `pm_alex`. O runtime ONNX usa CPU, sem PyTorch/CUDA. Os pesos são Apache 2.0 e o adaptador ONNX é MIT. Os dois arquivos oficiais foram baixados por HTTPS e fixados por SHA-256 em ai_worker/kokoro-models.json.

Teste real neste ambiente, texto de demonstração com 88 caracteres: feminina de aproximadamente 5,61 s gerada em 4,08 s incluindo carga inicial; masculina de aproximadamente 5,76 s em 2,24 s com modelo carregado. Pico RSS observado próximo de 565 MB com duas threads CPU. Esses números não são SLA nem avaliação subjetiva de naturalidade. Outros textos/hosts terão desempenho diferente. Amostras reais: `autoposts/static/art/voice-female.wav` e `voice-male.wav`.

Para as imagens do estabelecimento, o modo padrão preserva as fotos reais e monta vídeo com enquadramento, movimento, transições, marca e texto. Isso evita inventar detalhes do negócio. A montagem é automatizada, mas **não é vídeo gerado por difusão nem cria uma pessoa com sincronização labial**. Vídeo generativo de alto realismo sem GPU/serviço externo permanece fora da versão padrão.

## Voz

| Modelo | Português / própria voz | Licença documentada | Encaixe |
|---|---|---|---|
| [Kokoro 82M](https://github.com/hexgrad/kokoro) + [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) | PT-BR; vozes prontas, sem clonagem | Apache 2.0 / MIT | **Padrão integrado e testado realmente em CPU**, feminino e masculino. |
| [Chatterbox Multilingual](https://github.com/resemble-ai/chatterbox) | PT e clonagem de amostra própria | MIT; preserva watermark Perth | Adaptador opcional preparado. Modelo maior/lento em CPU; qualidade real de clonagem não foi testada com a voz do usuário. |
| [Qwen3-TTS 0.6B / 1.7B Base](https://github.com/QwenLM/Qwen3-TTS) | Dez idiomas, incluindo português; clonagem com amostra | Apache 2.0 | Alternativa opcional preparada com 0.6B. A API oficial oferece x_vector_only_mode sem transcrição, com possível perda de qualidade. Não avaliado realmente nesta entrega. |
| [CosyVoice](https://github.com/FunAudioLLM/CosyVoice) | README consultado lista nove idiomas, sem português | Consultar licença específica dos pesos | Não escolhido para PT-BR padrão; não presumir suporte natural só por ser multilíngue. |
| [F5-TTS](https://github.com/SWivid/F5-TTS) | Clonagem; depende dos pesos/idiomas | Código MIT, pesos oficiais CC-BY-NC | **Não incluído no SaaS comercial** com esses pesos: código aberto não elimina restrição não comercial. |

Fontes Kokoro: [exemplo oficial](https://github.com/thewh1teagle/kokoro-onnx/blob/main/examples/save.py), [vozes](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md), [arquivos oficiais fixados](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.1). O download automático verifica tamanho e hash, sem desativar TLS. Clonagem própria exige autorização explícita, guarda cifrada e permite revogação; não há clonagem silenciosa de terceiros.

## Imagens

| Modelo / abordagem | Pontos relevantes | Limite para este projeto |
|---|---|---|
| Fotos próprias + Pillow | Preserva o estabelecimento real, sem alterar arquitetura/produto | **Padrão implementado e testado**; composição gráfica, não síntese de um local novo. |
| Stable Diffusion 1.5 img2img | Ecossistema amplo, CPU possível em baixa resolução; licença dos pesos CreativeML Open RAIL-M | Adaptador opcional para variações 512px, não homologado com os pesos aqui. Pode alterar detalhes e não é a melhor opção de fidelidade. Requer instalação extra de diffusers/transformers/torch se usar o serviço Kokoro leve. |
| [FLUX.2 klein 4B](https://github.com/black-forest-labs/flux2) | Edição com uma/múltiplas referências, variante 4B com Apache 2.0 | Candidato para futura infraestrutura mais forte, não integrado nem testado aqui. Não confundir 4B com 9B/dev, cujos pesos são não comerciais na documentação consultada. |
| [Qwen-Image / Edit](https://github.com/QwenLM/Qwen-Image) | Edição de imagem e texto; Apache 2.0 | Candidato para futura infraestrutura. Offload/quantização podem reduzir VRAM, mas não tornam gratuito um serviço CPU lento nem garantem fidelidade do local. Não integrado. |
| [FLUX.1 schnell](https://github.com/black-forest-labs/flux) | Variante schnell Apache 2.0 | Modelo maior que o escolhido para CPU. Variantes dev/Kontext/Redux têm licença não comercial nos links do repositório; não foram incluídas como padrão comercial grátis. |

## Vídeo generativo

| Modelo | Realismo / hardware e licença | Decisão |
|---|---|---|
| [Wan2.2](https://github.com/Wan-Video/Wan2.2) | Geração texto/imagem para vídeo; Apache 2.0. O comando oficial TI2V-5B com offload informa pelo menos 24 GB VRAM; caminhos 14B exemplificados requerem mais. | Bom candidato aberto para futura GPU; não atende à exigência atual de hospedagem gratuita sem GPU. Não integrado/testado. |
| [LTX-2 / LTX-2.5](https://github.com/Lightricks/LTX-2) | Vídeo/áudio e workflows de produção. Código Apache 2.0, **pesos com Community License própria**. [LTX-2.x](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x) exige licença paga para entidades no patamar de receita definido, além das outras condições. | Potencial candidato futuro, sujeito a hardware e licença dos pesos. Não declarar "Apache irrestrito" com base só na licença do código. Não integrado/testado. |
| Fotos + FFmpeg | Vídeo H.264/AAC vertical, transições, enquadramento e narração real por TTS | **Implementado e testado**, inclusive MP4 com áudio audível e Kokoro. É a alternativa prática gratuita em software/CPU para esta entrega. |

Não há base para prometer que qualquer saída será indistinguível da realidade. Demonstrações de marketing dos autores não substituem teste com as fotos, língua e hardware do cliente.

## APIs e serviços com "créditos grátis"

Créditos de teste, demos públicas e contas gratuitas de geração não são um backend comercial ilimitado. Esta implementação não automatiza interfaces de consumidor para contornar login, cotas ou planos, nem depende de créditos PixVerse/Kling/Runway/Veo para funcionar. Se futuramente contratar uma API, valide licença comercial, custos e quotas da API específica.

## Próximo passo operacional

Use `INSTALAR.md` para Kokoro CPU. Para melhorar realismo visual além das fotos reais será necessário testar outro modelo com memória/aceleração suficientes. As opções GPU acima estão pesquisadas, não foram disfarçadas de funcionalidades prontas. As duas edições utilizam o mesmo pipeline; demo não transforma pesquisa em integração homologada.
