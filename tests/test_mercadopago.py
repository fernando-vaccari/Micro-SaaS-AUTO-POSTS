"""Signed Mercado Pago contracts; never charge or authorize a real subscription."""
import hashlib
import hmac
import json
import time
from datetime import datetime,timezone
from unittest.mock import Mock
import pytest
from autoposts import core,mercadopago as mp

@pytest.fixture
def client(logged_client,monkeypatch):
    monkeypatch.setenv('APP_EDITION','saas');monkeypatch.setenv('BILLING_PROVIDER','mercadopago')
    monkeypatch.setenv('PUBLIC_PLAN_IDS','studio');monkeypatch.setenv('MP_ACCESS_TOKEN','test-not-a-real-access-token')
    monkeypatch.setenv('MP_WEBHOOK_SECRET','test-webhook-signing-secret')
    monkeypatch.setattr(core.settings,'base_url','https://studio.example.com')
    core.execute('UPDATE users SET email_verified=1')
    return logged_client


def owner():return core.one('SELECT * FROM users')

def checkout_response():return {'id':'sub_test_owned','init_point':'https://www.mercadopago.com.br/subscriptions/checkout?preapproval_id=sub_test_owned','status':'pending'}

def agreement():return {'id':'sub_test_owned','external_reference':owner()['id'],'status':'authorized','auto_recurring':{'frequency':1,'frequency_type':'months','transaction_amount':149.99,'currency_id':'BRL'}}

def payment(status='approved'):
    return {'id':12345,'status':status,'transaction_amount':149.99,'currency_id':'BRL','date_approved':datetime.now(timezone.utc).isoformat()}

def send(client,topic,identity,request_id='request-test-1',timestamp=None,bad=False):
    timestamp=str(timestamp if timestamp is not None else int(time.time()))
    manifest=f'id:{str(identity).lower()};request-id:{request_id};ts:{timestamp};'
    signature=hmac.new(b'test-webhook-signing-secret',manifest.encode(),hashlib.sha256).hexdigest()
    if bad:signature='0'*64
    return client.post('/api/billing/mercadopago/webhook',params={'data.id':identity},json={'type':topic,'data':{'id':identity}},headers={'X-Request-Id':request_id,'X-Signature':f'ts={timestamp},v1={signature}'})


def test_hosted_checkout_14999_does_not_grant_access_and_is_deduplicated(client,monkeypatch):
    gateway=Mock(return_value=checkout_response());monkeypatch.setattr(mp,'request_api',gateway)
    first=client.post('/api/billing/checkout',json={'plan':'studio'});assert first.status_code==200,first.text
    assert client.post('/api/billing/checkout',json={'plan':'studio'}).status_code==200
    assert gateway.call_count==1
    body=gateway.call_args.args[2]
    assert body['auto_recurring']=={'frequency':1,'frequency_type':'months','transaction_amount':149.99,'currency_id':'BRL'}
    assert body['status']=='pending' and body['external_reference']==owner()['id']
    assert 'card_token_id' not in body
    assert owner()['plan']=='free'
    assert client.get('/?billing=return').status_code==200 and owner()['plan']=='free'


def test_webhook_requires_signature_timestamp_and_matching_id(client,monkeypatch):
    gateway=Mock();monkeypatch.setattr(mp,'request_api',gateway)
    assert send(client,'subscription_preapproval','sub_test_owned',bad=True).status_code==400
    assert send(client,'subscription_preapproval','sub_test_owned',timestamp=int(time.time())-601).status_code==400
    assert client.post('/api/billing/mercadopago/webhook',json={'type':'subscription_preapproval','data':{'id':'sub_test_owned'}}).status_code==400
    gateway.assert_not_called()


def test_authorized_agreement_is_not_a_payment(client,monkeypatch):
    core.execute("UPDATE users SET mp_preapproval_id='sub_test_owned'")
    monkeypatch.setattr(mp,'request_api',Mock(return_value=agreement()))
    assert send(client,'subscription_preapproval','sub_test_owned').status_code==200
    assert owner()['plan']=='free' and owner()['mp_status']=='authorized'


def test_approved_payment_grants_studio_and_replay_does_not_double_charge(client,monkeypatch):
    core.execute("UPDATE users SET mp_preapproval_id='sub_test_owned'")
    def gateway(method,path,*args):
        if path.startswith('/authorized_payments/'):return {'id':6789,'preapproval_id':'sub_test_owned','payment':{'id':12345}}
        if path.startswith('/preapproval/'):return agreement()
        if path.startswith('/v1/payments/'):return payment()
        raise AssertionError(path)
    mock=Mock(side_effect=gateway);monkeypatch.setattr(mp,'request_api',mock)
    assert send(client,'subscription_authorized_payment','6789').status_code==200
    user=owner();assert user['plan']=='studio' and user['subscription_status']=='active'
    assert user['billing_provider']=='mercadopago' and user['subscription_until']>core.now()
    assert send(client,'subscription_authorized_payment','6789').json()['duplicate'] is True
    assert mock.call_count==3
    assert core.one('SELECT COUNT(*) AS n FROM mp_payments')['n']==1


def test_wrong_amount_cannot_grant_subscription(client,monkeypatch):
    core.execute("UPDATE users SET mp_preapproval_id='sub_test_owned'")
    def gateway(method,path,*args):
        if path.startswith('/authorized_payments/'):return {'id':6789,'preapproval_id':'sub_test_owned','payment':{'id':12345}}
        if path.startswith('/preapproval/'):return agreement()
        return {**payment(),'transaction_amount':1}
    monkeypatch.setattr(mp,'request_api',gateway)
    assert send(client,'subscription_authorized_payment','6789').status_code==502
    assert owner()['plan']=='free'


def test_refund_revokes_the_refunded_period(client,monkeypatch):
    user=owner();mp.sync_payment(payment(),user,'initial-payment')
    assert owner()['plan']=='studio'
    monkeypatch.setattr(mp,'request_api',Mock(return_value=payment('refunded')))
    assert send(client,'payment','12345').status_code==200
    assert owner()['plan']=='free' and owner()['subscription_status']=='inactive'


def test_cancellation_keeps_paid_period_and_is_confirmed(client,monkeypatch):
    core.execute("UPDATE users SET mp_preapproval_id='sub_test_owned'")
    mp.sync_payment(payment(),owner(),'initial-payment')
    gateway=Mock(return_value={'status':'cancelled'});monkeypatch.setattr(mp,'request_api',gateway)
    assert client.post('/api/billing/mercadopago/cancel',json={}).status_code==422
    assert client.post('/api/billing/mercadopago/cancel',json={'confirmed':True}).status_code==200
    assert owner()['mp_status']=='cancelled' and owner()['plan']=='studio'
    assert gateway.call_args.args==('PUT','/preapproval/sub_test_owned',{'status':'cancelled'})


def test_foreign_subscription_is_ignored(client,monkeypatch):
    core.execute("UPDATE users SET mp_preapproval_id='sub_test_owned'")
    monkeypatch.setattr(mp,'request_api',Mock(return_value={**agreement(),'external_reference':'another-tenant'}))
    assert send(client,'subscription_preapproval','sub_test_owned').status_code==200
    assert owner()['plan']=='free' and owner()['mp_status'] is None
