"""Owned photographs and narration, with optional self-hosted CPU inference."""
import json
import math
import tempfile
import wave
from pathlib import Path
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from . import core

class CreativeOptions(BaseModel):
    enabled: bool = False
    asset_ids: list[str] = Field(default_factory=list, max_length=6)
    voice_id: str | None = Field(default=None, max_length=64)
    voice_mode: Literal['none', 'original', 'cloned', 'synthetic_female', 'synthetic_male'] = 'none'
    speech_text: str = Field(default='', max_length=650)
    visual_mode: Literal['photos', 'variation'] = 'photos'

    @model_validator(mode='after')
    def valid_options(self):
        if self.enabled and (not self.asset_ids or len(set(self.asset_ids)) != len(self.asset_ids)):
            raise ValueError('Selecione de uma a seis fotos diferentes da sua biblioteca.')
        if self.enabled and self.voice_mode in {'original','cloned'} and not self.voice_id:
            raise ValueError('Escolha uma gravação da sua voz.')
        return self


def options(post):
    data=post.get('creative_config') or {}
    if isinstance(data,str):data=json.loads(data)
    return CreativeOptions.model_validate(data)


def validate_owned(config, user_id, kind='video'):
    if not config.enabled:return
    for asset_id in config.asset_ids:
        if not core.one('SELECT 1 FROM assets WHERE id=? AND user_id=? AND deleted_at IS NULL',(asset_id,user_id)):
            raise HTTPException(400,'Escolha somente fotos disponíveis na sua biblioteca.')
    if kind=='video' and config.visual_mode!='photos':raise HTTPException(422,'Vídeos usam as fotos reais. Variação por IA está disponível para imagens.')
    if kind=='image' and config.voice_mode!='none':raise HTTPException(422,'Narração está disponível em vídeos.')
    if config.voice_mode in {'original','cloned'} and not core.one('SELECT 1 FROM voice_profiles WHERE id=? AND user_id=? AND revoked_at IS NULL',(config.voice_id,user_id)):
        raise HTTPException(400,'A gravação não está disponível ou sua autorização foi revogada.')
    from .ai_client import capabilities
    caps=capabilities()
    if config.voice_mode.startswith('synthetic_') and not caps['voice_tts']:
        raise HTTPException(503,'O operador precisa ativar a narração Kokoro em CPU. O projeto inclui o processador gratuito, mas os modelos devem estar instalados.')
    if config.voice_mode=='cloned' and not caps['voice_cloning']:
        raise HTTPException(503,'A clonagem precisa do processador de voz configurado pelo operador. Você pode usar sua gravação original.')
    if config.visual_mode=='variation' and not caps['image_variation']:
        raise HTTPException(503,'O processador local de variação de imagens ainda não foi configurado.')


def render(post, renderer):
    from . import media, voices, ai_client
    config=options(post)
    if not config.enabled:return renderer(post)
    try:validate_owned(config,post['user_id'],post.get('kind','video'))
    except HTTPException as exc:raise media.RenderError(str(exc.detail)) from None
    prepared=dict(post)
    scenes=json.loads(post['scenes']) if isinstance(post['scenes'],str) else post['scenes']
    prepared['scenes']=[{'text':scenes[i].get('text','') if i<len(scenes) else '',
                        'asset_id':config.asset_ids[i%len(config.asset_ids)]}
                       for i in range(max(len(scenes),len(config.asset_ids)))]
    with tempfile.TemporaryDirectory(dir=core.settings.data_dir/'tmp',prefix='studio-') as directory:
        directory=Path(directory)
        if config.voice_mode!='none':
            script=config.speech_text or ' '.join(s.get('text','') for s in scenes)
            if not script.strip() or len(script)>650:raise media.RenderError('Use um roteiro de narração de até 650 caracteres.')
            if config.voice_mode.startswith('synthetic_'):
                audio=ai_client.speak(script,'female' if config.voice_mode=='synthetic_female' else 'male')
            else:
                profile=core.one('SELECT * FROM voice_profiles WHERE id=? AND user_id=? AND revoked_at IS NULL',(config.voice_id,post['user_id']))
                if not profile:raise media.RenderError('A autorização da voz foi revogada.')
                audio=voices.audio_bytes(profile)
                if config.voice_mode=='cloned':audio=ai_client.synthesize(audio,script)
            path=directory/'narration.wav';path.write_bytes(audio)
            try:
                with wave.open(str(path),'rb') as wav:
                    seconds=wav.getnframes()/wav.getframerate()
                    if not 0.5<=seconds<=59 or wav.getnchannels() not in (1,2):raise ValueError('duration')
            except (wave.Error,ValueError,EOFError):raise media.RenderError('A narração deve ser um WAV válido e ter até 59 segundos. Reduza o texto.') from None
            prepared['duration']=max(post['duration'],math.ceil(seconds))
            prepared['_narration_path']=path
            # Recheck consent after inference, before producing a result.
            if config.voice_mode in {'original','cloned'} and not core.one('SELECT 1 FROM voice_profiles WHERE id=? AND user_id=? AND revoked_at IS NULL',(config.voice_id,post['user_id'])):
                raise media.RenderError('A autorização da voz foi revogada durante a geração.')
        if config.visual_mode=='variation':
            image=media._owned_image(post,config.asset_ids[0])
            generated=ai_client.vary_image(image.read_bytes(),post['caption'] or post['title'])
            destination=directory/'variation.jpg';destination.write_bytes(generated)
            prepared['_generated_image']=destination
        return renderer(prepared)
