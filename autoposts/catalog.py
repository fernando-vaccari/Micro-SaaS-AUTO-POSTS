"""Public plan settings without importing the database or creating local files."""
import os

DEFAULTS={'studio':(14999,20,40),'starter':(2999,10,5),'pro':(6999,20,10),'business':(10999,50,25),'premium':(15999,80,40)}


def catalog(legacy_stripe_price_id=''):
    result={}
    for name,(price,videos,images) in DEFAULTS.items():
        def value(suffix,default):
            try:val=int(os.environ.get(f'PLAN_{name.upper()}_{suffix}',default))
            except ValueError:raise RuntimeError('Configuração de plano inválida.') from None
            if not 1<=val<=1_000_000:raise RuntimeError('Configuração de plano inválida.')
            return val
        result[name]={'id':name,'name':name.title(),'price_cents':value('PRICE_CENTS',price),'currency':'BRL',
                      'videos':value('VIDEOS',videos),'images':value('IMAGES',images),'trial_days':7 if name=='starter' else 0,
                      'stripe_price_id':os.environ.get(f'STRIPE_PRICE_{name.upper()}') or (legacy_stripe_price_id if name=='pro' else '')}
    return result


def public_plan_ids():
    return [p.strip() for p in os.environ.get('PUBLIC_PLAN_IDS','studio').split(',') if p.strip()]


def public_catalog():
    return [{k:v for k,v in plan.items() if k!='stripe_price_id'}
            for name,plan in catalog().items() if name in public_plan_ids()]
