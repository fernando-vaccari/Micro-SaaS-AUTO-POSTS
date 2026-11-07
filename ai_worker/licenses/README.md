# Atribuições dos componentes de IA

- **Kokoro 82M** — pesos Apache 2.0; https://huggingface.co/hexgrad/Kokoro-82M e https://github.com/hexgrad/kokoro. Cópia da licença em KOKORO_APACHE_2.txt.
- **kokoro-onnx** — runtime MIT, https://github.com/thewh1teagle/kokoro-onnx. Cópia em KOKORO_ONNX_MIT.txt. Os modelos convertidos são do release model-files-v1.1, com hash no manifesto. Este repositório não inclui pesos pesados no Git; a imagem Docker os baixa de origem oficial e verifica integridade.
- **Chatterbox** — opcional, MIT, https://github.com/resemble-ai/chatterbox. Preserve o watermark Perth das saídas; cópia em CHATTERBOX_MIT.txt.
- **Qwen3-TTS** — opcional, Apache 2.0, https://github.com/QwenLM/Qwen3-TTS. Cópia em QWEN3_TTS_APACHE_2.txt.
- **Stable Diffusion 1.5** — adaptação opcional, pesos não distribuídos aqui. Revise CreativeML Open RAIL-M e os termos dos pesos escolhidos antes de ativar.

As amostras de narração genérica em autoposts/static/art/voice-*.wav foram sintetizadas com Kokoro, a partir do texto demonstrativo original da entrega. Não contêm gravação pessoal do cliente. As licenças de pacotes transitivos continuam sendo as de seus respectivos autores.
