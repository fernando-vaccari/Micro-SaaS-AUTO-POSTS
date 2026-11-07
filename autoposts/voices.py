"""Private voice recordings with explicit consent, encryption and revocation."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import wave
from cryptography.fernet import Fernet
from fastapi import APIRouter,Depends,File,Form,HTTPException,Request,UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from . import core,storage
router=APIRouter()
MAX_AUDIO=8*1024*1024


def cipher():return Fernet(base64.urlsafe_b64encode(hashlib.sha256(core.settings.app_secret.encode()).digest()))


def normalize(data):
    if data.startswith(b'RIFF') and data[8:12]==b'WAVE':fmt='wav'
    elif data.startswith(b'\x1aE\xdf\xa3'):fmt='matroska'
    elif data.startswith(b'OggS'):fmt='ogg'
    elif data.startswith(b'ID3') or data[:2] in (b'\xff\xfb',b'\xff\xf3',b'\xff\xf2'):fmt='mp3'
    elif data[4:8]==b'ftyp':fmt='mov'
    else:raise HTTPException(400,'Envie áudio WAV, WebM, Ogg, MP3 ou M4A válido.')
    with tempfile.TemporaryDirectory(dir=core.settings.data_dir/'tmp',prefix='voice-') as directory:
        source=Path(directory)/'input';destination=Path(directory)/'clean.wav';source.write_bytes(data)
        try:
            subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-protocol_whitelist','file,pipe','-f',fmt,'-i',str(source),'-map','0:a:0','-vn','-t','31','-ac','1','-ar','24000','-c:a','pcm_s16le',str(destination)],check=True,capture_output=True,timeout=30)
            result=destination.read_bytes()
            with wave.open(io.BytesIO(result)) as wav:seconds=wav.getnframes()/wav.getframerate()
        except (subprocess.SubprocessError,OSError,wave.Error,EOFError):raise HTTPException(400,'Não foi possível ler a gravação. Tente gravar novamente.') from None
    if not 3<=seconds<=30:raise HTTPException(422,'A gravação deve ter de 3 a 30 segundos, com sua voz clara e sem música.')
    return result,seconds


def public(row):return {**{k:row[k] for k in ('id','name','duration','consented_at','revoked_at','created_at')},'audio_url':f"/api/voices/{row['id']}/audio" if not row['revoked_at'] else None}


def audio_bytes(row):
    from .media import RenderError
    if row['revoked_at']:raise RenderError('A autorização da voz foi revogada.')
    path=core.safe_file('voices',row['filename']) if (core.settings.data_dir/'voices'/row['filename']).is_file() else None
    try:
        encrypted=path.read_bytes() if path else storage.get_store(row.get('storage_provider','b2')).get_bytes(row['storage_key'],2*1024*1024)
        return cipher().decrypt(encrypted)
    except Exception:raise RenderError('A gravação privada não está disponível. Confira armazenamento e APP_SECRET ou grave novamente.') from None


@router.get('/api/voices')
def list_voices(user=Depends(core.current_user)):
    return {'voices':[public(r) for r in core.query('SELECT * FROM voice_profiles WHERE user_id=? AND revoked_at IS NULL ORDER BY created_at DESC',(user['id'],))]}


@router.post('/api/voices',status_code=201)
async def upload_voice(request:Request,user=Depends(core.current_user),file:UploadFile=File(...),name:str=Form(...,min_length=2,max_length=60),consent:bool=Form(False)):
    from .accounts import rate_limit
    rate_limit(request,'voice-upload',10,3600,user['id'])
    if not consent:raise HTTPException(422,'Confirme que esta é sua própria voz e autorize a síntese para seus conteúdos.')
    if core.one('SELECT COUNT(*) AS n FROM voice_profiles WHERE user_id=? AND revoked_at IS NULL',(user['id'],))['n']>=3:
        raise HTTPException(403,'Você pode manter até três gravações. Exclua uma antes de adicionar outra.')
    raw=bytearray()
    try:
        while chunk:=await file.read(65536):
            raw.extend(chunk)
            if len(raw)>MAX_AUDIO:raise HTTPException(413,'O áudio deve ter no máximo 8 MB.')
    finally:await file.close()
    data,seconds=await run_in_threadpool(normalize,bytes(raw))
    identity=core.uid();filename=identity+'.enc';encrypted=cipher().encrypt(data);remote=None
    if storage.backend() in {'b2','r2'}:
        try:remote=await run_in_threadpool(storage.get_store().put_bytes,f'users/{user["id"]}/voices/{identity}.wav.enc',encrypted,'application/octet-stream')
        except storage.StorageError as exc:raise HTTPException(503,str(exc)) from None
    directory=core.settings.data_dir/'voices';directory.mkdir(exist_ok=True)
    path=directory/filename
    try:
        with core.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT COUNT(*) FROM voice_profiles WHERE user_id=? AND revoked_at IS NULL',(user['id'],)).fetchone()[0]>=3:raise HTTPException(403,'Limite de três gravações atingido.')
            with open(path,'xb',opener=lambda p,f:os.open(p,f,0o600)) as stream:stream.write(encrypted)
            stamp=core.now()
            db.execute('INSERT INTO voice_profiles(id,user_id,name,filename,duration,size,storage_key,storage_version,consented_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(identity,user['id'],name.strip(),filename,seconds,len(encrypted),remote['key'] if remote else None,remote.get('version_id') if remote else None,stamp,stamp))
            if remote:db.execute('UPDATE voice_profiles SET storage_provider=? WHERE id=?',(remote.get('provider') or storage.backend(),identity))
            db.execute('INSERT INTO audit_events(user_id,event,object_id,created_at) VALUES(?,?,?,?)',(user['id'],'voice.consent',identity,stamp))
    except Exception:
        path.unlink(missing_ok=True)
        if remote:
            with core.connect() as db:
                from .maintenance import queue_delete
                queue_delete(db,{'user_id':user['id'],'storage_key':remote['key'],'storage_version':remote.get('version_id'),'storage_provider':remote.get('provider') or storage.backend()},'voice_upload_rollback')
        raise
    return {'voice':public(core.one('SELECT * FROM voice_profiles WHERE id=?',(identity,)))}


@router.get('/api/voices/{voice_id}/audio')
def download_voice(voice_id:str,user=Depends(core.current_user)):
    row=core.one('SELECT * FROM voice_profiles WHERE id=? AND user_id=? AND revoked_at IS NULL',(voice_id,user['id']))
    if not row:raise HTTPException(404,'Gravação não encontrada.')
    from .media import RenderError
    try:data=audio_bytes(row)
    except RenderError as exc:raise HTTPException(503,str(exc)) from None
    return Response(data,media_type='audio/wav',headers={'Content-Disposition':'inline; filename="minha-voz.wav"','Cache-Control':'no-store'})


@router.delete('/api/voices/{voice_id}')
def revoke_voice(voice_id:str,user=Depends(core.current_user)):
    with core.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM voice_profiles WHERE id=? AND user_id=?',(voice_id,user['id'])).fetchone()
        if not row:raise HTTPException(404,'Gravação não encontrada.')
        from .maintenance import queue_delete
        queue_delete(db,dict(row),'voice_revoked')
        db.execute('UPDATE voice_profiles SET revoked_at=? WHERE id=?',(core.now(),voice_id))
        db.execute('INSERT INTO audit_events(user_id,event,object_id,created_at) VALUES(?,?,?,?)',(user['id'],'voice.revoked',voice_id,core.now()))
    (core.settings.data_dir/'voices'/row['filename']).unlink(missing_ok=True)
    return {'ok':True,'message':'Autorização revogada. Novas gerações com esta voz serão bloqueadas.'}
