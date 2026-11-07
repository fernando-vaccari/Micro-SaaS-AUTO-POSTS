"""Private CPU service for Chatterbox multilingual and optional SD 1.5 img2img.
No demo credentials or generated responses: missing models cause an explicit failure.
"""
import hmac
import io
import os
from pathlib import Path
import tempfile
import threading
import wave
from fastapi import FastAPI,Depends,File,Form,HTTPException,Request,UploadFile
from fastapi.responses import Response
from PIL import Image

app=FastAPI(docs_url=None,redoc_url=None)
_slot=threading.BoundedSemaphore(1)
_voice=None
_image=None
_kokoro=None

@app.middleware('http')
async def limit_body(request,call_next):
    if request.method=='POST':
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>10*1024*1024: return Response('Arquivo excede o limite.',status_code=413)
        request._body=bytes(raw)
    response=await call_next(request)
    response.headers['Cache-Control']='no-store'
    return response


def authenticate(request:Request):
    secret=os.environ.get('AI_MEDIA_TOKEN','')
    if len(secret)<32 or not hmac.compare_digest(request.headers.get('authorization','').encode(),('Bearer '+secret).encode()):
        raise HTTPException(401,'Processador privado.')

@app.get('/health',dependencies=[Depends(authenticate)])
def health():return {'status':'ok','device':'cpu','voice_engine':os.environ.get('AI_VOICE_ENGINE','kokoro'),'voice_model_loaded':_voice is not None,'image_model_loaded':_image is not None,'images_enabled':os.environ.get('AI_IMAGES_ENABLED')=='true'}


def synthesize_bytes(reference,text):
    global _voice
    import torch
    import soundfile as sf
    torch.set_num_threads(max(1,min(int(os.environ.get('AI_CPU_THREADS','2')),8)))
    engine=os.environ.get('AI_VOICE_ENGINE','chatterbox')
    if engine not in {'chatterbox','qwen3'}:raise ValueError('engine')
    if _voice is None:
        if engine=='qwen3':
            from qwen_tts import Qwen3TTSModel
            _voice=Qwen3TTSModel.from_pretrained('Qwen/Qwen3-TTS-12Hz-0.6B-Base',device_map='cpu',dtype=torch.float32,attn_implementation='eager')
        else:
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS
            _voice=ChatterboxMultilingualTTS.from_pretrained(device='cpu')
    with tempfile.TemporaryDirectory(prefix='voice-inference-') as directory:
        path=Path(directory)/'reference.wav';path.write_bytes(reference)
        output=io.BytesIO()
        try:
            with torch.inference_mode():
                if engine=='qwen3':
                    clips,sample_rate=_voice.generate_voice_clone(text=text,language='Portuguese',ref_audio=str(path),x_vector_only_mode=True)
                    samples=clips[0]
                else:
                    waveform=_voice.generate(text,language_id='pt',audio_prompt_path=str(path),exaggeration=0.35,cfg_weight=0.5)
                    samples=waveform.squeeze(0).detach().cpu().numpy();sample_rate=_voice.sr
            if len(samples)/sample_rate>59:raise ValueError('Narração longa')
            # Preserve the watermark supplied by Chatterbox; no voice is trained/stored here.
            sf.write(output,samples,sample_rate,format='WAV',subtype='PCM_16')
            return output.getvalue()
        finally:
            if engine=='chatterbox':_voice.conds=None


@app.post('/synthesize',dependencies=[Depends(authenticate)])
def synthesize(reference:UploadFile=File(...),text:str=Form(...,min_length=3,max_length=650),language:str=Form('pt')):
    if language!='pt':raise HTTPException(422,'Esta instalação usa português.')
    if not _slot.acquire(blocking=False):raise HTTPException(429,'Processador ocupado.')
    try:
        data=reference.file.read(2*1024*1024+1)
        if len(data)>2*1024*1024:raise ValueError('size')
        with wave.open(io.BytesIO(data)) as sample:
            if not 3<=sample.getnframes()/sample.getframerate()<=30:raise ValueError('duration')
        return Response(synthesize_bytes(data,text),media_type='audio/wav')
    except Exception:raise HTTPException(503,'Falha de inferência. Verifique dependências, modelos e memória; detalhes privados foram omitidos.') from None
    finally:
        reference.file.close();_slot.release()


def image_bytes(reference,prompt):
    global _image
    import torch
    from diffusers import StableDiffusionImg2ImgPipeline
    torch.set_num_threads(max(1,min(int(os.environ.get('AI_CPU_THREADS','2')),8)))
    if _image is None:
        _image=StableDiffusionImg2ImgPipeline.from_pretrained('stable-diffusion-v1-5/stable-diffusion-v1-5',torch_dtype=torch.float32)
        _image.to('cpu');_image.enable_attention_slicing()
    with Image.open(io.BytesIO(reference)) as source:
        if source.width*source.height>20_000_000:raise ValueError('size')
        source=source.convert('RGB');source.thumbnail((512,512))
        width=max(64,source.width//8*8);height=max(64,source.height//8*8)
        source=source.resize((width,height))
        with torch.inference_mode():result=_image(prompt=prompt,image=source,strength=0.30,num_inference_steps=25,guidance_scale=7.0)
        if result.nsfw_content_detected and any(result.nsfw_content_detected):raise ValueError('filtered')
        output=io.BytesIO();result.images[0].save(output,'JPEG',quality=95)
        return output.getvalue()


@app.post('/image',dependencies=[Depends(authenticate)])
def image(reference:UploadFile=File(...),prompt:str=Form(...,min_length=3,max_length=2200)):
    if os.environ.get('AI_IMAGES_ENABLED')!='true':raise HTTPException(503,'Variação de imagens não habilitada.')
    if not _slot.acquire(blocking=False):raise HTTPException(429,'Processador ocupado.')
    try:
        data=reference.file.read(8*1024*1024+1)
        if len(data)>8*1024*1024:raise ValueError('size')
        return Response(image_bytes(data,prompt),media_type='image/jpeg')
    except Exception:raise HTTPException(503,'Falha ao gerar a variação. Verifique modelos e memória; dados privados não foram registrados.') from None
    finally:reference.file.close();_slot.release()


def speak_bytes(text,voice):
    global _kokoro
    import soundfile as sf
    from kokoro_onnx import Kokoro
    from kokoro_onnx.log import log
    import logging
    log.setLevel(logging.WARNING)
    directory=Path(os.environ.get('KOKORO_MODEL_DIR','/models/kokoro'))
    if _kokoro is None:
        import onnxruntime as rt
        rt.disable_telemetry_events()
        from scripts.download_voice_models import download
        download(directory)
        settings=rt.SessionOptions();settings.intra_op_num_threads=max(1,min(int(os.environ.get('AI_CPU_THREADS','2')),8));settings.inter_op_num_threads=1
        session=rt.InferenceSession(str(directory/'kokoro-v1.0.onnx'),sess_options=settings,providers=['CPUExecutionProvider'])
        _kokoro=Kokoro.from_session(session,str(directory/'voices-v1.0.bin'))
    samples,sample_rate=_kokoro.create(text,voice='pf_dora' if voice=='female' else 'pm_alex',speed=1.0,lang='pt-br')
    if len(samples)/sample_rate>59:raise ValueError('Narração longa')
    output=io.BytesIO();sf.write(output,samples,sample_rate,format='WAV',subtype='PCM_16')
    return output.getvalue()


@app.post('/speak',dependencies=[Depends(authenticate)])
def speak(text:str=Form(...,min_length=3,max_length=650),voice:str=Form('female')):
    if voice not in {'female','male'}:raise HTTPException(422,'Escolha feminina ou masculina.')
    if not _slot.acquire(blocking=False):raise HTTPException(429,'Processador ocupado.')
    try:return Response(speak_bytes(text,voice),media_type='audio/wav')
    except Exception:raise HTTPException(503,'A voz de IA ainda não está disponível. Verifique modelos e memória do processador.') from None
    finally:_slot.release()
