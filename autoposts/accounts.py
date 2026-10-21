"""Profile, password recovery, email verification and durable account deletion."""
import hashlib
import os
import secrets
import smtplib
import ssl
import time
from datetime import datetime,timedelta,timezone
from email.message import EmailMessage
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from pydantic import BaseModel,Field,field_validator
from . import core
router=APIRouter()

def rate_limit(request,kind,maximum,window,subject=''):
    ip=request.client.host if request.client else 'unknown'
    key=hashlib.sha256((kind+':'+ip+':'+subject).encode()).hexdigest()
    stamp=time.time()
    with core.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM persistent_rate_limits WHERE expires_at<?',(stamp,))
        row=db.execute('SELECT * FROM persistent_rate_limits WHERE key=?',(key,)).fetchone()
        if row and row['count']>=maximum:raise HTTPException(429,'Muitas tentativas. Aguarde antes de tentar novamente.',headers={'Retry-After':str(window)})
        db.execute('INSERT INTO persistent_rate_limits VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1',(key,stamp+window))

def smtp_ready():return bool(os.environ.get('SMTP_HOST') and os.environ.get('SMTP_FROM'))

def send_email(recipient,subject,body):
    if not smtp_ready():raise HTTPException(503,'Configure SMTP_HOST e SMTP_FROM para envio de e-mail.')
    host=os.environ['SMTP_HOST'];mode=os.environ.get('SMTP_MODE','starttls');port=int(os.environ.get('SMTP_PORT','465' if mode=='ssl' else '587'))
    message=EmailMessage();message['To']=recipient;message['From']=os.environ['SMTP_FROM'];message['Subject']=subject;message.set_content(body)
    try:
        context=ssl.create_default_context()
        if mode=='ssl':client=smtplib.SMTP_SSL(host,port,timeout=15,context=context)
        elif mode=='starttls':
            client=smtplib.SMTP(host,port,timeout=15);client.ehlo();client.starttls(context=context);client.ehlo()
        elif mode=='plain' and not core.settings.production and host in {'127.0.0.1','localhost'}:client=smtplib.SMTP(host,port,timeout=15)
        else:raise ValueError('Unsupported SMTP mode')
        with client:
            if os.environ.get('SMTP_USERNAME'):client.login(os.environ['SMTP_USERNAME'],os.environ.get('SMTP_PASSWORD',''))
            client.send_message(message)
    except Exception:raise HTTPException(503,'Não foi possível enviar o e-mail. Verifique as configurações SMTP seguras.') from None

class EmailInput(BaseModel):
    email:str=Field(min_length=3,max_length=254)
    @field_validator('email')
    @classmethod
    def normalize(cls,v):return v.strip().lower()

class ResetInput(BaseModel):
    token:str=Field(min_length=20,max_length=128)
    password:str=Field(min_length=10,max_length=128)

class TokenInput(BaseModel):token:str=Field(min_length=20,max_length=128)
class PasswordInput(BaseModel):
    current_password:str=Field(min_length=1,max_length=128)
    password:str=Field(min_length=10,max_length=128)
class ProfileInput(BaseModel):name:str=Field(min_length=2,max_length=80)
class DeleteInput(BaseModel):
    password:str=Field(min_length=1,max_length=128)
    confirmed:bool=False

def issue_token(user,purpose):
    token=secrets.token_urlsafe(32);digest=hashlib.sha256(token.encode()).hexdigest()
    with core.connect() as db:
        db.execute('DELETE FROM recovery_tokens WHERE user_id=? AND purpose=?',(user['id'],purpose))
        db.execute('INSERT INTO recovery_tokens VALUES(?,?,?,?,?)',(digest,user['id'],purpose,(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat(),core.now()))
    return token,digest

@router.post('/api/auth/forgot-password')
def forgot(data:EmailInput,request:Request):
    rate_limit(request,'forgot',5,3600)
    if not smtp_ready():raise HTTPException(503,'O administrador precisa configurar o envio de e-mail SMTP.')
    user=core.one('SELECT * FROM users WHERE email=? AND deletion_requested=0',(data.email,))
    if user:
        token,digest=issue_token(user,'password')
        try:send_email(user['email'],'Redefinir senha AUTO POSTS',f"Use este link em até 30 minutos: {core.settings.base_url}/?reset={token}\nSe não solicitou, ignore este e-mail.")
        except HTTPException:
            core.execute('DELETE FROM recovery_tokens WHERE id=?',(digest,));raise
    return {'ok':True,'message':'Se a conta existir, você receberá um e-mail com instruções.'}

@router.post('/api/auth/reset-password')
def reset(data:ResetInput,request:Request):
    rate_limit(request,'reset',10,3600)
    digest=hashlib.sha256(data.token.encode()).hexdigest()
    hashed=core.password_hash(data.password)
    with core.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT * FROM recovery_tokens WHERE id=? AND purpose='password' AND expires_at>?",(digest,core.now())).fetchone()
        if not row:raise HTTPException(400,'O link expirou ou já foi utilizado.')
        db.execute('UPDATE users SET password_hash=? WHERE id=?',(hashed,row['user_id']))
        db.execute('DELETE FROM sessions WHERE user_id=?',(row['user_id'],))
        db.execute('DELETE FROM recovery_tokens WHERE user_id=?',(row['user_id'],))
    return {'ok':True}

@router.post('/api/account/verification')
def request_verification(request:Request,user=Depends(core.current_user)):
    rate_limit(request,'verify',3,3600,user['id'])
    if user['email_verified']:return {'ok':True}
    token,digest=issue_token(user,'email')
    try:send_email(user['email'],'Confirmar e-mail AUTO POSTS',f"Confirme seu e-mail em até 30 minutos: {core.settings.base_url}/?verify={token}")
    except HTTPException:
        core.execute('DELETE FROM recovery_tokens WHERE id=?',(digest,));raise
    return {'ok':True}

@router.post('/api/auth/verify-email')
def verify_email(data:TokenInput,request:Request):
    rate_limit(request,'verify-token',10,3600)
    digest=hashlib.sha256(data.token.encode()).hexdigest()
    with core.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT * FROM recovery_tokens WHERE id=? AND purpose='email' AND expires_at>?",(digest,core.now())).fetchone()
        if not row:raise HTTPException(400,'O link expirou ou já foi utilizado.')
        db.execute('UPDATE users SET email_verified=1 WHERE id=?',(row['user_id'],))
        db.execute('DELETE FROM recovery_tokens WHERE id=?',(digest,))
    return {'ok':True}

@router.put('/api/account/profile')
def profile(data:ProfileInput,user=Depends(core.current_user)):
    name=data.name.strip()
    if len(name)<2:raise HTTPException(422,'Informe seu nome.')
    core.execute('UPDATE users SET name=? WHERE id=?',(name,user['id']))
    return {'user':core.public_user(core.one('SELECT * FROM users WHERE id=?',(user['id'],)))}

@router.post('/api/account/password')
def change_password(data:PasswordInput,request:Request,response:Response,user=Depends(core.current_user)):
    rate_limit(request,'change-password',5,600,user['id'])
    if not core.password_matches(data.current_password,user['password_hash']):raise HTTPException(400,'Senha atual incorreta.')
    hashed=core.password_hash(data.password)
    with core.connect() as db:
        db.execute('UPDATE users SET password_hash=? WHERE id=?',(hashed,user['id']))
        db.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
        db.execute('DELETE FROM recovery_tokens WHERE user_id=?',(user['id'],))
    core.clear_session(request,response)
    return {'ok':True,'message':'Senha alterada. Entre novamente em todos os dispositivos.'}

@router.delete('/api/account',status_code=202)
def delete_account(data:DeleteInput,request:Request,response:Response,user=Depends(core.current_user)):
    rate_limit(request,'delete-account',5,3600,user['id'])
    if not data.confirmed or not core.password_matches(data.password,user['password_hash']):raise HTTPException(400,'Confirme a exclusão com sua senha atual.')
    if core.one("SELECT 1 FROM posts WHERE user_id=? AND status='publishing'",(user['id'],)) or core.one("SELECT 1 FROM media_jobs WHERE user_id=? AND status='processing' AND lease_until>?",(user['id'],core.now())):raise HTTPException(409,'Aguarde a tarefa em andamento antes de excluir sua conta.')
    if user.get('stripe_subscription_id'):
        from .integrations import _stripe_request,IntegrationError
        if not core.settings.stripe_secret_key:raise HTTPException(503,'É necessário cancelar sua assinatura antes de excluir a conta.')
        try:_stripe_request('DELETE','/subscriptions/'+user['stripe_subscription_id'])
        except IntegrationError as exc:raise HTTPException(503,str(exc)) from None
    with core.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        # Recheck after network call; a concurrent claim must not upload an orphan.
        if db.execute("SELECT 1 FROM media_jobs WHERE user_id=? AND status='processing' AND lease_until>?",(user['id'],core.now())).fetchone() or db.execute("SELECT 1 FROM posts WHERE user_id=? AND status='publishing'",(user['id'],)).fetchone():raise HTTPException(409,'Aguarde a tarefa em andamento.')
        db.execute('UPDATE users SET deletion_requested=1 WHERE id=?',(user['id'],))
        db.execute('UPDATE campaigns SET enabled=0,next_run_at=NULL WHERE user_id=?',(user['id'],))
        db.execute("UPDATE posts SET status='failed',scheduled_at=NULL WHERE user_id=? AND status IN ('scheduled','rendering')",(user['id'],))
        db.execute("UPDATE media_jobs SET status='failed' WHERE user_id=? AND status!='completed'",(user['id'],))
        db.execute("UPDATE automation_runs SET status='cancelled' WHERE user_id=? AND status NOT IN ('published','failed','rendered')",(user['id'],))
        db.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
        db.execute('INSERT OR IGNORE INTO deletion_requests VALUES(?,?,NULL)',(user['id'],core.now()))
    core.clear_session(request,response)
    return {'ok':True,'status':'deletion_pending','message':'A conta foi bloqueada. A limpeza dos arquivos será concluída pelo processador.'}

@router.get('/api/account/audit')
def audit(user=Depends(core.current_user)):
    return {'events':core.query('SELECT event,object_id,detail,created_at FROM audit_events WHERE user_id=? ORDER BY id DESC LIMIT 100',(user['id'],))}

@router.get('/api/billing/history')
def billing_history(user=Depends(core.current_user)):
    return {'events':core.query('SELECT event_type,plan,status,amount,currency,created_at FROM billing_history WHERE user_id=? ORDER BY created_at DESC LIMIT 100',(user['id'],)),'pending_checkout':core.one('SELECT plan,checkout_url,expires_at FROM billing_checkouts WHERE user_id=? AND expires_at>?',(user['id'],core.now()))}
