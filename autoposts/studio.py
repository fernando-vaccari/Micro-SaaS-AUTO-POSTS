"""Guided creation with atomic quota/queue writes and safe request retries."""
import hashlib
import json
import re
import textwrap
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from . import core, ai_client
from .creative import CreativeOptions

router = APIRouter()


class StudioInput(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    prompt: str = Field(min_length=3, max_length=650)
    caption: str = Field(default='', max_length=2200)
    kind: Literal['video', 'image'] = 'video'
    duration: int = Field(default=30, ge=6, le=60, strict=True)
    asset_ids: list[str] = Field(min_length=1, max_length=6)
    voice_id: str | None = Field(default=None, max_length=64)
    voice_mode: Literal['none', 'original', 'cloned', 'synthetic_female', 'synthetic_male'] = 'none'
    visual_mode: Literal['photos', 'variation'] = 'photos'
    auto_publish: bool = False
    account_id: str | None = Field(default=None, max_length=64)
    publish_time: str = Field(default='09:00', pattern=r'^([01][0-9]|2[0-3]):[0-5][0-9]$')
    timezone: str = Field(default='America/Sao_Paulo', max_length=60)
    company_name: str = Field(default='', max_length=80)
    color: str = Field(default='#7cdec3', pattern='^#[A-Fa-f0-9]{6}$')

    @field_validator('title', 'prompt', 'company_name', mode='before')
    @classmethod
    def trim_required_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('Informe um fuso horário IANA válido, como America/Sao_Paulo.') from None
        return value

    def creative_options(self):
        return CreativeOptions(enabled=True, asset_ids=self.asset_ids, voice_id=self.voice_id,
                               voice_mode=self.voice_mode, speech_text=self.prompt, visual_mode=self.visual_mode)

    @model_validator(mode='after')
    def valid_creative_options(self):
        # Convert duplicate photos / missing voice selections into API validation errors.
        self.creative_options()
        return self


@router.get('/api/studio/config')
def config():
    return {**ai_client.capabilities(), 'max_photos': 6, 'max_voice_seconds': 30,
            'max_video_seconds': 60, 'max_prompt_characters': 650}


def _create_in_transaction(db, data, user):
    from . import automation, jobs, plans
    from .creative import validate_owned
    from .edition import require_publishing
    from .main import PostInput, insert_post, verify_assets

    creative = data.creative_options()
    if data.auto_publish:
        require_publishing()
        plans.require_entitlement(user)
        validate_owned(creative, user['id'], data.kind)
        if not data.account_id:
            raise HTTPException(422, 'Conecte seu Instagram profissional e escolha a conta para ativar o piloto automático.')
        campaign = automation.CampaignInput(
            name=data.title[:80], niche=data.company_name if len(data.company_name)>=3 else data.prompt[:160], topics=[data.prompt],
            company_name=data.company_name, kind=data.kind, duration=data.duration, account_id=data.account_id,
            enabled=True, times=[data.publish_time], timezone=data.timezone,
            creative_config=creative.model_dump(),
            brand_config={'company_name': data.company_name, 'primary_color': data.color, 'motion': True})
        automation.validate_input(campaign, user)
        campaign_id = automation.insert_campaign(db, campaign, user)
        run = automation.enqueue_run(db, campaign_id, preview=False, scheduled_for=core.now())
        return run['post_id'], campaign_id

    # Preserve the complete script, including long sentences and the final invitation.
    lines = textwrap.wrap(data.prompt, width=180, break_long_words=True, break_on_hyphens=False)
    scenes = [{'text': lines[i] if i < len(lines) else '', 'asset_id': data.asset_ids[i % len(data.asset_ids)]}
              for i in range(max(len(lines), len(data.asset_ids)))]
    post = PostInput(title=data.title, caption=data.caption or data.prompt, kind=data.kind,
                     duration=data.duration, scenes=scenes, theme='ocean', creative_config=creative,
                     brand_config={'company_name': data.company_name, 'primary_color': data.color, 'motion': True})
    verify_assets(post, user)
    post_id = insert_post(db, post, user)
    db.execute("UPDATE posts SET status='rendering',render_count=1 WHERE id=?", (post_id,))
    jobs.enqueue(post_id, db)
    return post_id, None


@router.post('/api/studio', status_code=201)
def create(data: StudioInput, request: Request, response: Response, user=Depends(core.current_user)):
    key = request.headers.get('Idempotency-Key')
    if key is not None and not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', key):
        raise HTTPException(400, 'Identificador de criação inválido. Reabra o estúdio e tente novamente.')
    digest = hashlib.sha256(json.dumps(data.model_dump(), sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    replayed = False
    with core.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        prior = db.execute('SELECT * FROM studio_requests WHERE user_id=? AND request_key=?',
                           (user['id'], key)).fetchone() if key else None
        if prior:
            if prior['request_hash'] != digest:
                raise HTTPException(409, 'Esta tentativa já foi usada para outra criação. Atualize o formulário antes de enviar novamente.')
            if not prior['post_id'] or (prior['campaign_id'] and not db.execute(
                    'SELECT 1 FROM campaigns WHERE id=? AND user_id=?', (prior['campaign_id'], user['id'])).fetchone()):
                raise HTTPException(410, 'Esta criação foi excluída. Inicie uma nova criação para gerar outro conteúdo.')
            post_id, campaign_id = prior['post_id'], prior['campaign_id']
            replayed = True
        else:
            post_id, campaign_id = _create_in_transaction(db, data, user)
            if key:
                db.execute('INSERT INTO studio_requests VALUES(?,?,?,?,?,?)',
                           (user['id'], key, digest, post_id, campaign_id, core.now()))
    if replayed:
        response.status_code = 200
        response.headers['Idempotency-Replayed'] = 'true'
    result = {'post': core.public_post(core.owned_post(post_id, user))}
    if campaign_id:
        from .automation import public_campaign, owned_campaign
        result.update(campaign=public_campaign(owned_campaign(campaign_id, user)), automated=True)
    return result
