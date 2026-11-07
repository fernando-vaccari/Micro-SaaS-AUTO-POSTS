"""Private, operator-configured CPU inference service. Never accepts user URLs."""
import os
from urllib.parse import urlsplit
import httpx
from .media import RenderError


class InferenceError(RenderError):
    retryable=True


def capabilities():
    configured=bool(os.environ.get('AI_MEDIA_URL') and len(os.environ.get('AI_MEDIA_TOKEN',''))>=32)
    return {'voice_tts':configured and os.environ.get('AI_VOICE_ENGINE','kokoro') in {'kokoro','qwen3'},'voice_cloning':configured and os.environ.get('AI_VOICE_ENGINE','kokoro') in {'chatterbox','qwen3'},'image_variation':configured and os.environ.get('AI_IMAGES_ENABLED')=='true',
            'generative_video':False,'provider':os.environ.get('AI_VOICE_ENGINE','kokoro')+'-local-cpu' if configured else None,
            'note':'Vídeos são composições das fotos reais. IA de voz/imagem exige modelos instalados e processamento; não há promessa de realismo ou hospedagem ilimitada.'}


def _request(path, files, data, maximum):
    base=os.environ.get('AI_MEDIA_URL','').rstrip('/')
    parsed=urlsplit(base)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise RenderError('Endereço do processador de IA inválido.')
    if parsed.scheme!='https' and not(parsed.scheme=='http' and parsed.hostname in {'127.0.0.1','localhost','ai'}):
        raise RenderError('Use HTTPS para o processador de IA remoto.')
    token=os.environ.get('AI_MEDIA_TOKEN','')
    if len(token)<32:raise RenderError('O operador precisa configurar o processador privado de IA.')
    try:
        timeout=min(420,max(10,int(os.environ.get('AI_MEDIA_TIMEOUT','360'))))
        # Private in-machine/container traffic must never send voice/text to an HTTP proxy.
        local=parsed.hostname in {'127.0.0.1','localhost','ai'}
        with httpx.Client(timeout=timeout,follow_redirects=False,trust_env=not local) as client:
            with client.stream('POST',base+path,files=files,data=data,headers={'Authorization':'Bearer '+token}) as response:
                if response.status_code in {429,502,503,504}:raise InferenceError('O processador está ocupado ou indisponível. O sistema tentará novamente dentro do limite da fila.')
                if response.status_code!=200:raise RenderError('O processador de IA não concluiu a geração. Confira instalação, memória e disponibilidade do serviço.')
                body=bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body)>maximum:raise RenderError('O resultado da IA excedeu o limite permitido.')
                return bytes(body)
    except (httpx.HTTPError,ValueError):raise InferenceError('O processador de IA está indisponível ou excedeu o tempo. Em CPU a geração pode ser lenta.') from None


def synthesize(reference,text):
    return _request('/synthesize',{'reference':('reference.wav',reference,'audio/wav')},{'text':text,'language':'pt'},6*1024*1024)


def vary_image(reference,prompt):
    from PIL import Image
    import io
    data=_request('/image',{'reference':('reference.jpg',reference,'image/jpeg')},{'prompt':prompt},10*1024*1024)
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width*image.height>20_000_000:raise ValueError('size')
            image.load();output=io.BytesIO();image.convert('RGB').save(output,'JPEG',quality=95)
            return output.getvalue()
    except Exception:raise RenderError('O processador não devolveu uma imagem válida.') from None


def speak(text,voice='female'):
    if voice not in {'female','male'}:raise RenderError('Escolha uma voz feminina ou masculina.')
    return _request('/speak',None,{'text':text,'voice':voice},6*1024*1024)
