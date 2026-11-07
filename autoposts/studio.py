"""A guided creation entry point using the existing durable post queue."""
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from typing import Literal
from . import core,ai_client
from .creative import CreativeOptions
router=APIRouter()

class StudioInput(BaseModel):
    title:str=Field(min_length=2,max_length=120)
    prompt:str=Field(min_length=3,max_length=650)
    caption:str=Field(default='',max_length=2200)
    kind:Literal['video','image']='video'
    duration:int=Field(default=30,ge=6,le=60,strict=True)
    asset_ids:list[str]=Field(min_length=1,max_length=6)
    voice_id:str|None=Field(default=None,max_length=64)
    voice_mode:Literal['none','original','cloned','synthetic_female','synthetic_male']='none'
    visual_mode:Literal['photos','variation']='photos'
    auto_publish:bool=False
    account_id:str|None=Field(default=None,max_length=64)
    publish_time:str=Field(default='09:00',pattern=r'^([01][0-9]|2[0-3]):[0-5][0-9]$')
    timezone:str=Field(default='America/Sao_Paulo',max_length=60)
    company_name:str=Field(default='',max_length=80)
    color:str=Field(default='#7cdec3',pattern='^#[A-Fa-f0-9]{6}$')

@router.get('/api/studio/config')
def config():return {**ai_client.capabilities(),'max_photos':6,'max_voice_seconds':30,'max_video_seconds':60,'max_prompt_characters':650}

@router.post('/api/studio',status_code=201)
def create(data:StudioInput,user=Depends(core.current_user)):
    from .main import PostInput,create_post
    from . import jobs
    creative=CreativeOptions(enabled=True,asset_ids=data.asset_ids,voice_id=data.voice_id,voice_mode=data.voice_mode,speech_text=data.prompt,visual_mode=data.visual_mode)
    # Scene text is the visual caption, not a claim that the original recording reads the prompt.
    sentences=[s.strip() for s in data.prompt.replace('\n','. ').split('. ') if s.strip()]
    scenes=[{'text':sentences[min(i,len(sentences)-1)][:180],'asset_id':identity} for i,identity in enumerate(data.asset_ids)]
    if data.auto_publish:
        from . import automation,plans
        from .creative import validate_owned
        from .edition import require_publishing
        require_publishing();plans.require_entitlement(user);validate_owned(creative,user['id'],data.kind)
        if not data.account_id:raise HTTPException(422,'Conecte seu Instagram profissional e escolha a conta para ativar o piloto automático.')
        campaign=automation.create_campaign(automation.CampaignInput(name=data.title,niche=data.company_name or data.prompt[:160],topics=[data.prompt],company_name=data.company_name,kind=data.kind,duration=data.duration,account_id=data.account_id,enabled=True,times=[data.publish_time],timezone=data.timezone,creative_config=creative.model_dump(),brand_config={'company_name':data.company_name,'primary_color':data.color,'motion':True}),user)['campaign']
        try:run=automation.enqueue(campaign['id'],preview=False,scheduled_for=core.now())
        except HTTPException:
            core.execute('DELETE FROM campaigns WHERE id=? AND user_id=?',(campaign['id'],user['id']));raise
        return {'campaign':campaign,'post':core.public_post(core.owned_post(run['post_id'],user)),'automated':True}
    post=create_post(PostInput(title=data.title,caption=data.caption or data.prompt,kind=data.kind,duration=data.duration,scenes=scenes,
        theme='ocean',brand_config={'company_name':data.company_name,'primary_color':data.color,'motion':True},creative_config=creative),user)['post']
    with core.connect() as db:
        db.execute("UPDATE posts SET status='rendering',render_count=1 WHERE id=? AND user_id=?",(post['id'],user['id']))
        jobs.enqueue(post['id'],db)
    return {'post':core.public_post(core.owned_post(post['id'],user))}
