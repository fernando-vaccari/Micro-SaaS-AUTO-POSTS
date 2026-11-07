"""Mercado Pago hosted subscriptions. Access follows verified approved payments."""
import calendar
import hashlib
import hmac
import os
import re
import time
from datetime import datetime,timezone,timedelta
from decimal import Decimal,InvalidOperation
from urllib.parse import urlsplit
import httpx
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel
from . import core,plans
router=APIRouter()
API='https://api.mercadopago.com'


def configured():return bool(os.environ.get('MP_ACCESS_TOKEN') and os.environ.get('MP_WEBHOOK_SECRET'))
def selected():return os.environ.get('BILLING_PROVIDER','mercadopago')=='mercadopago'


def request_api(method,path,payload=None,nonce=None):
    if not configured():raise HTTPException(503,'Configure o Access Token e o segredo de webhook do Mercado Pago no servidor.')
    headers={'Authorization':'Bearer '+os.environ['MP_ACCESS_TOKEN'],'Content-Type':'application/json'}
    if nonce:headers['X-Idempotency-Key']=nonce
    try:
        with httpx.Client(timeout=25,follow_redirects=False) as client:
            response=client.request(method,API+path,json=payload,headers=headers)
        if response.status_code>=300:raise HTTPException(502,'O Mercado Pago recusou a operação. Verifique conta, credenciais, dados de teste e configuração da assinatura.')
        data=response.json()
        if not isinstance(data,dict):raise ValueError('response')
        return data
    except (httpx.HTTPError,ValueError):raise HTTPException(502,'Não foi possível confirmar a operação no Mercado Pago. Nenhuma assinatura foi liberada por esse retorno.') from None


def identifier(value):
    if not isinstance(value,(int,str)) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}',str(value)):
        raise HTTPException(400,'Identificador do provedor inválido.')
    return str(value)


def checkout(user):
    from .edition import require_billing
    require_billing()
    if not core.is_public_https(core.settings.base_url):raise HTTPException(503,'Configure APP_BASE_URL com HTTPS público para a assinatura.')
    if not configured():raise HTTPException(503,'O operador ainda precisa configurar o Mercado Pago. Consulte docs/mercado-pago/.')
    if not user.get('email_verified'):raise HTTPException(403,'Confirme seu e-mail antes de iniciar uma assinatura.')
    if user.get('subscription_status') in {'active','trialing'} and user.get('subscription_until', '') and user['subscription_until']>core.now():
        raise HTTPException(409,'Você já possui uma assinatura vigente. Gerencie-a antes de contratar outra.')
    with core.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        pending=db.execute('SELECT * FROM mp_checkouts WHERE user_id=?',(user['id'],)).fetchone()
        if pending:
            if pending['checkout_url']:return {'url':pending['checkout_url'],'provider':'mercadopago'}
            if pending['created_at']>(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat():raise HTTPException(409,'Checkout em processamento. Aguarde alguns instantes.')
        nonce=core.uid();db.execute('INSERT OR REPLACE INTO mp_checkouts VALUES(?,?,NULL,NULL,?)',(user['id'],nonce,core.now()))
    price=plans.catalog()['studio']['price_cents']
    try:
        result=request_api('POST','/preapproval',{'reason':'AUTO POSTS Studio — assinatura mensal','external_reference':user['id'],'payer_email':user['email'],
            'auto_recurring':{'frequency':1,'frequency_type':'months','transaction_amount':float(Decimal(price)/100),'currency_id':'BRL'},
            'back_url':core.settings.base_url+'/?billing=return#settings','status':'pending'},nonce)
        identity=identifier(result.get('id'));url=result.get('init_point','');parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.hostname not in {'www.mercadopago.com.br','www.mercadopago.com'} or parsed.username or parsed.password:
            raise HTTPException(502,'O Mercado Pago não retornou um checkout hospedado válido.')
        with core.connect() as db:
            db.execute('UPDATE mp_checkouts SET preapproval_id=?,checkout_url=? WHERE user_id=? AND nonce=?',(identity,url,user['id'],nonce))
            db.execute("UPDATE users SET mp_preapproval_id=?,billing_provider='mercadopago',mp_status='pending' WHERE id=?",(identity,user['id']))
    except Exception:
        core.execute('DELETE FROM mp_checkouts WHERE user_id=? AND nonce=?',(user['id'],nonce));raise
    return {'url':url,'provider':'mercadopago'}


def cancel(user):
    from .edition import require_billing
    require_billing()
    identity=user.get('mp_preapproval_id')
    if identity:
        result=request_api('PUT','/preapproval/'+identifier(identity),{'status':'cancelled'})
        if result.get('status')!='cancelled':raise HTTPException(502,'O cancelamento ainda não foi confirmado pelo Mercado Pago.')
    with core.connect() as db:
        db.execute("UPDATE users SET mp_status='cancelled' WHERE id=?",(user['id'],))
        db.execute('DELETE FROM mp_checkouts WHERE user_id=?',(user['id'],))
    return {'ok':True,'message':'Renovação cancelada. Um período já pago permanece disponível até o vencimento.'}

class Confirmation(BaseModel):confirmed:bool=False
@router.post('/api/billing/mercadopago/cancel')
def cancel_subscription(data:Confirmation,user=Depends(core.current_user)):
    if not data.confirmed:raise HTTPException(422,'Confirme o cancelamento da renovação.')
    return cancel(user)

@router.get('/api/billing/status')
def billing_status(user=Depends(core.current_user)):
    return {'provider':user.get('billing_provider') if user.get('stripe_subscription_id') or user.get('mp_preapproval_id') else os.environ.get('BILLING_PROVIDER','mercadopago'),
            'plan':user['plan'],'status':user.get('subscription_status'),'until':user.get('subscription_until'),'renewal_status':user.get('mp_status')}


def verify_signature(request):
    secret=os.environ.get('MP_WEBHOOK_SECRET','')
    resource=request.query_params.get('data.id','')
    request_id=request.headers.get('x-request-id','')
    fields={}
    for part in request.headers.get('x-signature','').split(','):
        key,sep,value=part.strip().partition('=')
        if sep and key in {'ts','v1'}:
            if key in fields:raise HTTPException(400,'Assinatura duplicada.')
            fields[key]=value
    ts=fields.get('ts','');signature=fields.get('v1','')
    if not secret or not re.fullmatch(r'[0-9]{10,13}',ts) or not re.fullmatch(r'[0-9a-fA-F]{64}',signature) or not request_id or len(request_id)>200:
        raise HTTPException(400,'Assinatura do Mercado Pago ausente ou inválida.')
    identifier(resource)
    timestamp=int(ts)/(1000 if len(ts)==13 else 1)
    if abs(time.time()-timestamp)>300:raise HTTPException(400,'Notificação expirada.')
    manifest=f'id:{resource.lower()};request-id:{request_id};ts:{ts};'
    expected=hmac.new(secret.encode(),manifest.encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,signature.lower()):raise HTTPException(400,'Assinatura do Mercado Pago inválida.')
    return resource,hashlib.sha256((manifest+signature).encode()).hexdigest()


def cents(value):
    try:
        amount=Decimal(str(value))*100
        if not amount.is_finite() or amount!=amount.to_integral_value():raise ValueError('amount')
        return int(amount)
    except (ValueError,InvalidOperation):raise HTTPException(502,'Valor de cobrança inválido no provedor.') from None


def verified_agreement(identity):
    agreement=request_api('GET','/preapproval/'+identifier(identity))
    if str(agreement.get('id'))!=identity:raise HTTPException(502,'Identificador de assinatura divergente.')
    user=core.one("SELECT * FROM users WHERE mp_preapproval_id=? AND id=? AND deletion_requested=0",(identity,agreement.get('external_reference','')))
    if not user:return None,None
    recurring=agreement.get('auto_recurring') or {}
    if recurring.get('frequency')!=1 or recurring.get('frequency_type')!='months' or recurring.get('currency_id')!='BRL' or cents(recurring.get('transaction_amount'))!=plans.catalog()['studio']['price_cents']:
        raise HTTPException(502,'Preço, moeda ou periodicidade da assinatura não corresponde ao plano Studio.')
    collector=os.environ.get('MP_COLLECTOR_ID')
    if collector and str(agreement.get('collector_id'))!=collector:raise HTTPException(502,'Conta recebedora divergente.')
    return agreement,user


def sync_payment(payment,user,event_id):
    identity=identifier(payment.get('id'));status=payment.get('status','unknown');price=plans.catalog()['studio']['price_cents']
    if status=='approved':
        if cents(payment.get('transaction_amount'))!=price or payment.get('currency_id')!='BRL':raise HTTPException(502,'O pagamento não corresponde ao valor do plano Studio.')
        try:
            start=datetime.fromisoformat(payment['date_approved'].replace('Z','+00:00')).astimezone(timezone.utc)
            month=start.month%12+1;year=start.year+(start.month==12)
            end=start.replace(year=year,month=month,day=min(start.day,calendar.monthrange(year,month)[1])).isoformat()
        except (ValueError,KeyError,TypeError):raise HTTPException(502,'O provedor não confirmou o período pago.') from None
    else:
        old=core.one('SELECT period_end FROM mp_payments WHERE id=? AND user_id=?',(identity,user['id']))
        if not old:return
        end=old['period_end']
    with core.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM mp_events WHERE id=?',(event_id,)).fetchone():return
        db.execute('INSERT INTO mp_payments VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status',(identity,user['id'],status,end,price,core.now()))
        latest=db.execute("SELECT MAX(period_end) AS until FROM mp_payments WHERE user_id=? AND status='approved'",(user['id'],)).fetchone()['until']
        active=bool(latest and latest>core.now())
        db.execute("UPDATE users SET plan=?,subscription_status=?,subscription_until=?,billing_provider='mercadopago' WHERE id=?",('studio' if active else 'free','active' if active else 'inactive',latest,user['id']))
        db.execute('INSERT OR IGNORE INTO billing_history VALUES(?,?,?,?,?,?,?,?)',('mp-'+event_id,user['id'],'mercadopago.payment','studio',status,price,'BRL',core.now()))
        db.execute('INSERT INTO mp_events VALUES(?,?)',(event_id,core.now()))
        db.execute('DELETE FROM mp_checkouts WHERE user_id=?',(user['id'],))


@router.post('/api/billing/mercadopago/webhook')
async def webhook(request:Request):
    from .edition import require_billing
    require_billing()
    if not configured():raise HTTPException(503,'Webhook do Mercado Pago não configurado.')
    resource,event_id=verify_signature(request)
    if core.one('SELECT 1 FROM mp_events WHERE id=?',(event_id,)):return {'ok':True,'duplicate':True}
    try:body=await request.json()
    except ValueError:raise HTTPException(400,'Notificação inválida.') from None
    if not isinstance(body,dict) or not isinstance(body.get('data'),dict) or str(body['data'].get('id','')).lower()!=resource.lower():raise HTTPException(400,'Recurso da notificação divergente da assinatura.')
    topic=body.get('type')
    if topic=='subscription_preapproval':
        agreement,user=verified_agreement(resource)
        if user:
            # "authorized" means consent to billing, not proof of an approved payment.
            with core.connect() as db:
                db.execute('UPDATE users SET mp_status=? WHERE id=?',(agreement.get('status','pending'),user['id']))
                db.execute('INSERT OR IGNORE INTO mp_events VALUES(?,?)',(event_id,core.now()))
    elif topic=='subscription_authorized_payment':
        charge=request_api('GET','/authorized_payments/'+identifier(resource))
        if str(charge.get('id'))!=resource:raise HTTPException(502,'Cobrança divergente.')
        agreement,user=verified_agreement(identifier(charge.get('preapproval_id')))
        payment_ref=charge.get('payment') or {}
        if user and payment_ref.get('id'):
            payment=request_api('GET','/v1/payments/'+identifier(payment_ref['id']))
            if str(payment.get('id'))!=str(payment_ref['id']):raise HTTPException(502,'Pagamento divergente.')
            if agreement.get('status') in {'authorized','paused','cancelled'}:sync_payment(payment,user,event_id)
    elif topic=='payment':
        old=core.one('SELECT user_id FROM mp_payments WHERE id=?',(resource,))
        if old:
            user=core.one('SELECT * FROM users WHERE id=? AND deletion_requested=0',(old['user_id'],))
            payment=request_api('GET','/v1/payments/'+identifier(resource))
            if str(payment.get('id'))!=resource:raise HTTPException(502,'Pagamento divergente.')
            if user:sync_payment(payment,user,event_id)
    return {'ok':True}
