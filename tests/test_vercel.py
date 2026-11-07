"""Serverless startup, proxy contracts and real backend state through the gateway."""
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from autoposts import vercel as gateway


@pytest.fixture
def web(monkeypatch):
    monkeypatch.delenv('AUTOPOSTS_BACKEND_URL', raising=False)
    for name in ('VERCEL_URL','VERCEL_PROJECT_PRODUCTION_URL','VERCEL_BRANCH_URL'):
        monkeypatch.delenv(name, raising=False)
    with TestClient(gateway.app, base_url='https://web.example.com') as client:
        yield client


def test_entrypoint_import_and_pages_work_without_writes_or_secrets(tmp_path):
    script='''
import sys,json
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
with patch('pathlib.Path.mkdir',side_effect=AssertionError('read-only filesystem')):
 from autoposts.vercel import app
 with TestClient(app) as client:
  for path in ('/','/login','/cadastro','/app.js','/studio-ui.js','/uploads.js','/art/voice-female.wav','/api/session','/api/plans','/api/public/config'):
   response=client.get(path)
   assert response.status_code==200,(path,response.status_code)
  assert client.post('/api/auth/register',json={'email':'never-created@example.com'}).status_code==503
assert 'autoposts.core' not in sys.modules
assert 'autoposts.main' not in sys.modules
assert 'autoposts.worker' not in sys.modules
assert json.loads(Path('vercel.json').read_text())['framework'] is None
print('READ_ONLY_GATEWAY_OK')
'''
    env={**os.environ,'APP_ENV':'production','APP_SECRET':'','DATA_DIR':str(tmp_path/'not-created'),
         'AUTOPOSTS_BACKEND_URL':'','PYTHONDONTWRITEBYTECODE':'1'}
    result=subprocess.run([sys.executable,'-c',script],env=env,capture_output=True,text=True,timeout=25)
    assert result.returncode==0,result.stderr
    assert 'READ_ONLY_GATEWAY_OK' in result.stdout
    assert not (tmp_path/'not-created').exists()


def test_missing_backend_opens_public_site_but_never_creates_accounts(web):
    assert web.get('/').status_code==200
    session=web.get('/api/session')
    assert session.json()['user'] is None and session.json()['csrf_token'] is None
    assert not session.headers.get_list('set-cookie')
    config=web.get('/api/public/config').json()
    assert config['backend_connected'] is False and config['publishing_enabled'] is False
    assert web.get('/api/plans').json()['plans'][0]['price_cents']==14999
    for path in ('/api/auth/register','/api/billing/checkout','/api/studio'):
        response=web.post(path,json={})
        assert response.status_code==503 and response.json()['code']=='BACKEND_NOT_CONFIGURED'
    assert web.get('/health').status_code==503


@pytest.mark.parametrize('origin',[
    'http://backend.example.com','https://localhost','https://127.0.0.1','https://127.1',
    'https://10.0.0.1','https://[::1]','https://user:private-value@backend.example.com',
    'https://backend.example.com/api','https://backend.example.com?token=private-value',
    'https://backend.example.com:9000','https://bad%host.example.com','not-a-url',
])
def test_invalid_backend_configuration_does_not_crash_or_disclose_values(web,monkeypatch,origin):
    monkeypatch.setenv('AUTOPOSTS_BACKEND_URL',origin)
    response=web.get('/api/public/config')
    assert response.status_code==200
    assert response.json()['deployment_status']=='BACKEND_CONFIGURATION_INVALID'
    response=web.post('/api/auth/login',json={})
    assert response.status_code==503 and 'private-value' not in response.text


@pytest.mark.parametrize('variable',['request','VERCEL_URL','VERCEL_PROJECT_PRODUCTION_URL','VERCEL_BRANCH_URL'])
def test_proxy_rejects_self_loops(web,monkeypatch,variable):
    host='web.example.com' if variable=='request' else 'project.vercel.app'
    monkeypatch.setenv('AUTOPOSTS_BACKEND_URL','https://'+host)
    if variable!='request':monkeypatch.setenv(variable,host)
    assert web.get('/health').json()['code']=='BACKEND_PROXY_LOOP'


def set_transport(monkeypatch,handler):
    monkeypatch.setenv('AUTOPOSTS_BACKEND_URL','https://backend.example.com')
    monkeypatch.setattr(gateway,'client',lambda:httpx.AsyncClient(transport=httpx.MockTransport(handler),follow_redirects=False))


def test_proxy_preserves_raw_webhook_body_query_and_headers_once(web,monkeypatch):
    body=b'{ "data": { "id": "123" }, "type":"payment" }'
    def remote(request):
        assert str(request.url)=='https://backend.example.com/api/billing/mercadopago/webhook?data.id=123&x=a%2Bb'
        assert request.method=='POST' and request.content==body
        assert request.headers['x-signature']=='test-signature' and request.headers['x-request-id']=='test-request'
        assert request.headers['idempotency-key']=='request-1234567890'
        assert request.headers['cookie']=='test-cookie=value'
        return httpx.Response(200,json={'ok':True})
    handler=Mock(side_effect=remote);set_transport(monkeypatch,handler)
    response=web.post('/api/billing/mercadopago/webhook?data.id=123&x=a%2Bb',content=body,
                      headers={'x-signature':'test-signature','x-request-id':'test-request',
                               'idempotency-key':'request-1234567890','cookie':'test-cookie=value'})
    assert response.status_code==200 and handler.call_count==1


def test_proxy_preserves_separate_secure_cookies(web,monkeypatch):
    set_transport(monkeypatch,lambda request:httpx.Response(200,json={'ok':True},headers=[
        ('set-cookie','autoposts_session=one; Path=/; Secure; HttpOnly; SameSite=Lax'),
        ('set-cookie','autoposts_csrf=two; Path=/; Secure; HttpOnly; SameSite=Lax')]))
    response=web.get('/api/session')
    assert len(response.headers.get_list('set-cookie'))==2
    assert web.cookies.get('autoposts_session')=='one' and web.cookies.get('autoposts_csrf')=='two'


def test_encoded_request_body_and_its_encoding_header_stay_together(web,monkeypatch):
    import gzip
    body=gzip.compress(b'{"message":"test"}')
    def remote(request):
        assert request.headers['content-encoding']=='gzip' and request.content==body
        return httpx.Response(200,json={'ok':True})
    set_transport(monkeypatch,remote)
    assert web.post('/api/test',content=body,headers={'content-encoding':'gzip'}).status_code==200


def test_gateway_uses_its_own_trusted_client_identity_headers(web,monkeypatch):
    secret='test-gateway-only-secret-at-least-32-characters'
    monkeypatch.setenv('AUTOPOSTS_GATEWAY_SECRET',secret);monkeypatch.setenv('VERCEL','1')
    def remote(request):
        assert request.headers['x-autoposts-gateway-token']==secret
        assert request.headers['x-autoposts-client-ip']=='203.0.113.10'
        return httpx.Response(200,json={'ok':True},headers={'x-autoposts-gateway-token':secret})
    set_transport(monkeypatch,remote)
    response=web.get('/api/session',headers={'x-vercel-forwarded-for':'203.0.113.10',
        'x-autoposts-client-ip':'198.51.100.20','x-autoposts-gateway-token':'forged'})
    assert response.status_code==200 and 'x-autoposts-gateway-token' not in response.headers


@pytest.mark.parametrize('authenticated',[False,True])
def test_backend_rate_limits_trust_only_an_authenticated_gateway(isolated_db,monkeypatch,authenticated):
    from fastapi import HTTPException,Request
    from autoposts.accounts import rate_limit
    secret='test-gateway-only-secret-at-least-32-characters'
    monkeypatch.setenv('AUTOPOSTS_GATEWAY_SECRET',secret)
    def request(ip):return Request({'type':'http','method':'GET','path':'/','client':('proxy-peer',123),
        'headers':[(b'x-autoposts-client-ip',ip.encode()),
                   (b'x-autoposts-gateway-token',(secret if authenticated else 'forged').encode())]})
    rate_limit(request('203.0.113.10'),'gateway-test',1,3600)
    if authenticated:rate_limit(request('203.0.113.11'),'gateway-test',1,3600)
    else:
        with pytest.raises(HTTPException) as error:rate_limit(request('203.0.113.11'),'gateway-test',1,3600)
        assert error.value.status_code==429


def test_media_redirect_is_not_followed_or_buffered(web,monkeypatch):
    handler=Mock(return_value=httpx.Response(307,headers={'Location':'https://bucket.r2.cloudflarestorage.com/private.mp4?signature=test'}))
    set_transport(monkeypatch,handler)
    response=web.get('/api/posts/post/media',follow_redirects=False)
    assert response.status_code==307 and 'r2.cloudflarestorage.com' in response.headers['location']
    assert handler.call_count==1


@pytest.mark.parametrize('failure',['timeout','upstream500','invalidconfig','oversized'])
def test_upstream_failures_are_controlled_without_retry_or_private_error_details(web,monkeypatch,failure):
    def remote(request):
        if failure=='timeout':raise httpx.ReadTimeout('private-url-or-key')
        if failure=='upstream500':return httpx.Response(500,text='private-url-or-key')
        if failure=='invalidconfig':return httpx.Response(200,text='not json')
        return httpx.Response(200,content=b'x'*(gateway.MAX_RESPONSE+1))
    handler=Mock(side_effect=remote);set_transport(monkeypatch,handler)
    response=web.get('/api/public/config')
    assert response.status_code in (502,503) and 'private-url-or-key' not in response.text
    assert handler.call_count==1


def test_gateway_bounds_uploads_before_forwarding(web,monkeypatch):
    handler=Mock(return_value=httpx.Response(200,json={}))
    set_transport(monkeypatch,handler);monkeypatch.setattr(gateway,'MAX_BODY',100)
    response=web.post('/api/assets',content=b'x'*101)
    assert response.status_code==413 and not handler.called


def test_slow_backend_is_stopped_before_platform_function_timeout(web,monkeypatch):
    import asyncio
    async def remote(request):
        await asyncio.sleep(0.1)
        return httpx.Response(200,json={'ok':True})
    set_transport(monkeypatch,remote)
    monkeypatch.setattr(gateway,'PROXY_DEADLINE',0.01)
    response=web.get('/api/session')
    assert response.status_code==503 and response.json()['code']=='BACKEND_TIMEOUT'


def test_security_headers_private_routes_and_files(web):
    response=web.get('/api/session')
    assert response.headers['cache-control']=='no-store'
    assert response.headers['x-content-type-options']=='nosniff'
    assert 'microphone=(self)' in response.headers['permissions-policy']
    assert web.get('/.env').status_code==404 and web.get('/core.py').status_code==404
    assert web.get('/privacy').status_code==200


@pytest.fixture
def connected(web,isolated_db,monkeypatch):
    from autoposts import core,automation
    from autoposts.main import app
    automation.init_automation()
    monkeypatch.setattr(core.settings,'base_url','https://web.example.com')
    monkeypatch.setattr(core.settings,'secure_cookies',True)
    monkeypatch.setenv('AUTOPOSTS_BACKEND_URL','https://backend.example.com')
    monkeypatch.setattr(gateway,'client',lambda:httpx.AsyncClient(transport=httpx.ASGITransport(app=app),follow_redirects=False))
    return web


def register_connected(client,email='person@example.com'):
    session=client.get('/api/session').json();client.headers['X-CSRF-Token']=session['csrf_token']
    result=client.post('/api/auth/register',json={'name':'Pessoa de teste','email':email,'password':'test-password-123'})
    assert result.status_code==201,result.text
    return result.json()['user']


def test_real_backend_registration_login_csrf_and_cookie_isolation(connected):
    user=register_connected(connected)
    assert connected.get('/api/dashboard').json()['user']['id']==user['id']
    assert connected.get('/api/public/config').json()['backend_connected'] is True
    assert connected.get('/api/studio/config').json()['max_photo_upload_bytes']==gateway.MAX_UPLOAD
    with TestClient(gateway.app,base_url='https://web.example.com') as other:
        assert other.get('/api/session').json()['user'] is None
        assert other.get('/api/dashboard').status_code==401
        second=register_connected(other,'another@example.com')
        assert second['id']!=user['id']
        assert connected.get('/api/session').json()['user']['id']==user['id']
    connected.headers.pop('X-CSRF-Token')
    assert connected.post('/api/auth/logout').status_code==403


def test_real_backend_studio_idempotency_and_private_media_are_preserved(connected):
    import io
    from PIL import Image
    from autoposts import core
    register_connected(connected)
    image=io.BytesIO();Image.new('RGB',(900,800),'#bfa478').save(image,'JPEG')
    result=connected.post('/api/assets',files={'file':('loja.jpg',image.getvalue(),'image/jpeg')})
    assert result.status_code==201,result.text
    photo=result.json()['asset'];data={'title':'Minha loja','prompt':'Conheça nosso espaço.','kind':'image','asset_ids':[photo['id']]}
    headers={'Idempotency-Key':'gateway-creation-1234567890'}
    first=connected.post('/api/studio',json=data,headers=headers)
    again=connected.post('/api/studio',json=data,headers=headers)
    assert first.status_code==201 and again.status_code==200
    assert first.json()['post']['id']==again.json()['post']['id']
    assert core.one('SELECT count FROM image_usage')['count']==1
    with TestClient(gateway.app,base_url='https://web.example.com') as other:
        assert other.get(photo['url']).status_code==401
