"""Operator-configurable prices/limits. Browser redirects never grant access."""
import os
from datetime import datetime,timezone
from fastapi import HTTPException
from . import core
from .catalog import DEFAULTS, catalog as plan_catalog, public_plan_ids

def catalog():
    return plan_catalog(core.settings.stripe_price_id)

def public_catalog():return [{k:v for k,v in p.items() if k!='stripe_price_id'} for name,p in catalog().items() if name in public_plan_ids()]

def limit_for(user,kind):
    from .edition import demo
    if demo():return catalog()['studio']['videos' if kind=='video' else 'images']
    if user['plan']=='free':return core.FREE_POSTS if kind=='video' else 2
    plan=catalog().get(user['plan'])
    if not plan:raise HTTPException(403,'Escolha um plano válido.')
    return plan['videos' if kind=='video' else 'images']

def require_entitlement(user):
    from .edition import demo
    if demo():return
    if not core.settings.production:return
    if user['plan']=='free' or user.get('subscription_status') not in {'active','trialing'}:
        raise HTTPException(403,'Escolha uma assinatura ativa para gerar ou publicar conteúdo.')
    end=user.get('subscription_until')
    if not end or end<=core.now():raise HTTPException(403,'O período da assinatura precisa ser confirmado pelo pagamento para continuar.')

def period_for(user):
    return user.get('subscription_until') if user.get('subscription_status') in {'active','trialing'} and user.get('subscription_until') else datetime.now(timezone.utc).strftime('%Y-%m')

def reserve(db,user_id,kind):
    user=dict(db.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone())
    require_entitlement(user)
    table='post_usage' if kind=='video' else 'image_usage'
    month=period_for(user)
    row=db.execute(f'SELECT count FROM {table} WHERE user_id=? AND month=?',(user_id,month)).fetchone()
    limit=limit_for(user,kind)
    if row and row['count']>=limit:raise HTTPException(403,f'Limite mensal de {limit} {"vídeos" if kind=="video" else "imagens"} atingido.')
    db.execute(f'INSERT INTO {table}(user_id,month,count) VALUES(?,?,1) ON CONFLICT(user_id,month) DO UPDATE SET count=count+1',(user_id,month))

def usage(user):
    month=period_for(user)
    videos=core.one('SELECT count FROM post_usage WHERE user_id=? AND month=?',(user['id'],month))
    images=core.one('SELECT count FROM image_usage WHERE user_id=? AND month=?',(user['id'],month))
    return {'used':videos['count'] if videos else 0,'limit':limit_for(user,'video'),'plan':user['plan'],'videos':{'used':videos['count'] if videos else 0,'limit':limit_for(user,'video')},'images':{'used':images['count'] if images else 0,'limit':limit_for(user,'image')},'status':user.get('subscription_status','inactive'),'renews_at':user.get('subscription_until')}
