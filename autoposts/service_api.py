"""Trusted renderer protocol; users only see their own job status."""
import hashlib
import hmac
import os
from pathlib import Path
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,Field
from . import core,jobs,storage,plans
router=APIRouter()

def is_service_request(request:Request):
    if not request.url.path.startswith('/api/jobs/'):return False
    secret=os.environ.get('AUTOPOSTS_API_SECRET','')
    supplied=request.headers.get('authorization','')
    return len(secret)>=32 and hmac.compare_digest(supplied.encode(),('Bearer '+secret).encode())

def service_auth(request:Request):
    if not is_service_request(request):raise HTTPException(401,'Autorização do processador inválida.')

@router.get('/api/jobs')
def list_jobs(user=Depends(core.current_user)):
    return {'jobs':[jobs.public_job(j) for j in core.query('SELECT * FROM media_jobs WHERE user_id=? ORDER BY created_at DESC LIMIT 100',(user['id'],))]}

@router.get('/api/jobs/next',dependencies=[Depends(service_auth)])
def next_job():
    row=core.one("SELECT id FROM media_jobs WHERE status='pending' AND (next_attempt_at IS NULL OR next_attempt_at<=?) ORDER BY created_at LIMIT 1",(core.now(),))
    return {'available':bool(row)}

@router.post('/api/jobs/claim',dependencies=[Depends(service_auth)])
def claim_job():
    for row in core.query("SELECT id FROM posts WHERE status='rendering' AND NOT EXISTS(SELECT 1 FROM media_jobs WHERE post_id=posts.id) LIMIT 20"):jobs.enqueue(row['id'])
    job=jobs.claim()
    if not job:return {'job':None}
    post=core.one('SELECT * FROM posts WHERE id=? AND user_id=?',(job['post_id'],job['user_id']))
    assets=[]
    import json
    ids={s.get('asset_id') for s in json.loads(post['scenes'])}
    ids.add(json.loads(post['brand_config'] or '{}').get('logo_asset_id'))
    for asset_id in ids:
        if asset_id:
            a=core.one('SELECT id,user_id,filename,storage_key,size FROM assets WHERE id=? AND user_id=? AND deleted_at IS NULL',(asset_id,post['user_id']))
            if not a or not a['storage_key']:
                jobs.fail(job,'O processador remoto precisa de todas as imagens no B2.');raise HTTPException(409,'Envie as imagens ao B2 antes de usar o processador remoto.')
            assets.append(a)
    return {'job':{'id':job['id'],'post_id':post['id'],'user_id':post['user_id'],'lease_token':job['lease_token'],'lease_until':job['lease_until'],'post':post,'assets':assets}}

class JobResult(BaseModel):
    lease_token:str=Field(min_length=20,max_length=128)
    status:str=Field(pattern='^(completed|failed)$')
    error:str=Field(default='',max_length=500)
    size:int=Field(default=0,ge=0,le=100*1024*1024)
    sha256:str=Field(default='',max_length=64)
    version_id:str|None=Field(default=None,max_length=256)

@router.post('/api/jobs/{job_id}/result',dependencies=[Depends(service_auth)])
def job_result(job_id:str,data:JobResult):
    job=core.one("SELECT * FROM media_jobs WHERE id=? AND status='processing' AND lease_until>?",(job_id,core.now()))
    if not job or not hmac.compare_digest(job['lease_token'],data.lease_token):raise HTTPException(409,'Reserva expirada ou inválida.')
    if data.status=='failed':jobs.fail(job,'O processador remoto não concluiu a tarefa. Confira os logs sem credenciais.',True);return {'ok':True,'status':'failed'}
    post=core.one('SELECT * FROM posts WHERE id=?',(job['post_id'],))
    key=storage.object_key(post['user_id'],post['id']+'-'+post['public_token'][:12],post['kind'])
    try:
        confirmed=storage.B2Store()._confirm(key,data.size,data.sha256)
        if data.size<=0 or not data.sha256 or confirmed.get('VersionId')!=data.version_id:
            raise storage.StorageError('A versão do objeto não foi confirmada.',code='verification',retryable=True)
    except storage.StorageError as exc:raise HTTPException(503,str(exc)) from None
    except Exception:raise HTTPException(503,'Não foi possível confirmar o upload no B2.') from None
    filename=post['id']+('.jpg' if post['kind']=='image' else '.mp4')
    if not jobs.complete(job,filename,{'key':key,'size':data.size,'sha256':data.sha256,'version_id':data.version_id}):raise HTTPException(409,'Reserva expirada.')
    return {'ok':True,'status':'completed'}

@router.get('/api/plans')
def plan_list():return {'plans':plans.public_catalog()}

@router.get('/api/library')
def library(user=Depends(core.current_user)):
    posts=core.query('SELECT * FROM posts WHERE user_id=? ORDER BY created_at DESC LIMIT 500',(user['id'],))
    assets=core.query('SELECT id,original_name,size,deleted_at,created_at FROM assets WHERE user_id=? ORDER BY created_at DESC',(user['id'],))
    return {'posts':[core.public_post(p) for p in posts],'assets':[{**a,'url':f"/api/assets/{a['id']}/file"} for a in assets],'retention_days':max(1,int(os.environ.get('MEDIA_RETENTION_DAYS','10')))}

@router.delete('/api/assets/{asset_id}')
def delete_asset(asset_id:str,user=Depends(core.current_user)):
    import json
    with core.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        a=db.execute('SELECT * FROM assets WHERE id=? AND user_id=?',(asset_id,user['id'])).fetchone()
        if not a:raise HTTPException(404,'Imagem não encontrada.')
        for p in db.execute('SELECT scenes,brand_config FROM posts WHERE user_id=?',(user['id'],)):
            if asset_id in {x.get('asset_id') for x in json.loads(p['scenes'])} or json.loads(p['brand_config'] or '{}').get('logo_asset_id')==asset_id:raise HTTPException(409,'A imagem está em uso por uma publicação.')
        for c in db.execute('SELECT brand_config FROM campaigns WHERE user_id=?',(user['id'],)):
            if json.loads(c['brand_config'] or '{}').get('logo_asset_id')==asset_id:raise HTTPException(409,'O logo está em uso por uma campanha.')
        from .maintenance import queue_delete
        queue_delete(db,dict(a),'user_delete')
        db.execute('DELETE FROM assets WHERE id=?',(asset_id,))
    try:core.safe_file('uploads',a['filename']).unlink(missing_ok=True)
    except HTTPException:pass
    return {'ok':True}

@router.get('/api/public/config')
def public_config():
    return {'operator':os.environ.get('LEGAL_OPERATOR_NAME',''),'contact':os.environ.get('LEGAL_CONTACT_EMAIL',''),'legal_updated':os.environ.get('LEGAL_UPDATED_AT',''),'retention_days':max(1,int(os.environ.get('MEDIA_RETENTION_DAYS','10'))),'production':core.settings.production}

@router.get('/api/jobs/{job_id}')
def job_detail(job_id:str,user=Depends(core.current_user)):
    row=core.one('SELECT * FROM media_jobs WHERE id=? AND user_id=?',(job_id,user['id']))
    if not row:raise HTTPException(404,'Tarefa não encontrada.')
    return {'job':jobs.public_job(row)}
