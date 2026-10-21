import hashlib
import json
import re
from datetime import datetime,timedelta,timezone
from unittest.mock import Mock
import pytest
from PIL import Image
from autoposts import core,automation,jobs,maintenance,storage,plans,worker,accounts

@pytest.fixture
def client(logged_client):
    automation.init_automation()
    return logged_client

def payload(kind='image'):
    return {'title':'Sua marca presente','caption':'Conteúdo autoral de teste','kind':kind,'scenes':[{'text':'Organize seu dia com três prioridades.'},{'text':'Reserve um tempo para focar.'},{'text':'Salve esta dica.'}],'duration':6,'theme':'ocean','brand_config':{'company_name':'Estúdio Teste','primary_color':'#45cfa0','cta':'Siga para mais dicas.'}}

def create(client,kind='image'):
    r=client.post('/api/posts',json=payload(kind));assert r.status_code==201,r.text
    return r.json()['post']

def test_image_real_generation_queue_and_private_download(client):
    p=create(client)
    assert client.post(f"/api/posts/{p['id']}/render").status_code==200
    assert worker._render_one()
    row=core.one('SELECT * FROM posts WHERE id=?',(p['id'],))
    assert row['status']=='ready'
    assert core.one('SELECT status FROM media_jobs')['status']=='completed'
    with Image.open(core.settings.data_dir/'images'/row['output_path']) as image:
        assert image.format=='JPEG' and image.size==(1080,1350)
    assert client.get(f"/api/posts/{p['id']}/media").headers['content-type']=='image/jpeg'
    from fastapi.testclient import TestClient
    from autoposts.main import app
    assert TestClient(app).get(f"/api/posts/{p['id']}/media").status_code==401

def test_failed_b2_upload_never_completes_job(client,monkeypatch):
    p=create(client);client.post(f"/api/posts/{p['id']}/render")
    store=Mock();store.put_file.side_effect=storage.StorageError('Upload não confirmado.',code='verification',retryable=True)
    monkeypatch.setattr(storage,'backend',lambda:'b2');monkeypatch.setattr(storage,'B2Store',lambda:store)
    worker._render_one()
    row=core.one('SELECT * FROM media_jobs');post=core.one('SELECT * FROM posts')
    assert row['status']=='pending' and row['attempts']==1
    assert post['status']=='rendering' and post['output_path'] is None and post['storage_key'] is None
    assert row['local_filename'] and row['next_attempt_at']
    # Retry reuses the rendered file, but can only complete after confirmed storage.
    store.put_file.side_effect=None;store.put_file.return_value={'key':'users/test/images/file.jpg','size':100,'sha256':'a'*64,'version_id':'v1'}
    core.execute('UPDATE media_jobs SET next_attempt_at=NULL')
    worker._render_one()
    assert core.one('SELECT status FROM media_jobs')['status']=='completed'
    assert core.one('SELECT storage_version FROM posts')['storage_version']=='v1'

def test_job_claims_are_exclusive_and_stale_leases_cannot_complete(client):
    p=create(client);client.post(f"/api/posts/{p['id']}/render")
    first=jobs.claim();assert first
    assert jobs.claim() is None
    core.execute('UPDATE media_jobs SET lease_until=?',((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),))
    second=jobs.claim();assert second['attempts']==2 and second['lease_token']!=first['lease_token']
    assert not jobs.complete(first,'old.jpg')
    assert jobs.complete(second,'new.jpg')

def test_plans_and_separate_media_quotas(client,monkeypatch):
    catalog=client.get('/api/plans').json()['plans']
    assert [(p['id'],p['price_cents'],p['videos'],p['images']) for p in catalog]==[('starter',2999,10,5),('pro',6999,20,10),('business',10999,50,25),('premium',15999,80,40)]
    assert all('stripe_price_id' not in p for p in catalog)
    create(client,'image');create(client,'image')
    assert client.post('/api/posts',json=payload()).status_code==403
    assert client.post('/api/posts',json=payload('video')).status_code==201
    monkeypatch.setenv('PLAN_STARTER_VIDEOS','12');assert plans.catalog()['starter']['videos']==12

def test_production_requires_verified_subscription(client,monkeypatch):
    monkeypatch.setattr(core.settings,'production',True)
    assert client.post('/api/posts',json=payload()).status_code==403
    core.execute("UPDATE users SET plan='starter',subscription_status='active'")
    assert client.post('/api/posts',json=payload()).status_code==403
    core.execute("UPDATE users SET plan='starter',subscription_status='active',subscription_until=?",((datetime.now(timezone.utc)+timedelta(days=30)).isoformat(),))
    assert client.post('/api/posts',json=payload()).status_code==201

def test_weekly_schedule_can_find_slot_six_days_later():
    next_date=automation.next_occurrence(['18:00'],'America/Sao_Paulo',datetime.fromisoformat('2026-10-20T21:00:00+00:00'),weekdays=[0])
    assert next_date=='2026-10-26T21:00:00+00:00'

def test_campaign_preserves_brand_frequency_and_image_kind(client):
    r=client.post('/api/campaigns',json={'name':'Academia Fitness','niche':'Academia','topics':['Movimente seu corpo todos os dias.'],'kind':'image','company_name':'Minha Academia','objective':'Conseguir novos alunos','duration':45,'weekdays':[0,2,4],'times':['18:00'],'brand_config':{'primary_color':'#00aaee'}})
    assert r.status_code==201,r.text
    c=r.json()['campaign'];assert c['weekdays']==[0,2,4] and c['kind']=='image' and c['company_name']=='Minha Academia'
    assert client.post(f"/api/campaigns/{c['id']}/run").status_code==202
    automation.tick_once()
    p=core.one('SELECT * FROM posts');assert p['kind']=='image' and json.loads(p['brand_config'])['company_name']=='Minha Academia'

def test_reset_tokens_are_hashed_single_use_and_revoke_sessions(client,monkeypatch):
    monkeypatch.setattr(accounts,'smtp_ready',lambda:True)
    mail=[];monkeypatch.setattr(accounts,'send_email',lambda *args:mail.append(args))
    email=core.one('SELECT email FROM users')['email']
    assert client.post('/api/auth/forgot-password',json={'email':email}).status_code==200
    token=re.search(r'reset=([\w-]+)',mail[0][2])[1]
    assert core.one('SELECT id FROM recovery_tokens')['id']==hashlib.sha256(token.encode()).hexdigest()
    assert client.post('/api/auth/reset-password',json={'token':token,'password':'replacement-pass-123'}).status_code==200
    assert client.get('/api/posts').status_code==401
    assert client.post('/api/auth/reset-password',json={'token':token,'password':'replacement-pass-123'}).status_code==400
    assert client.post('/api/auth/login',json={'email':email,'password':'replacement-pass-123'}).status_code==200

def test_password_change_rejects_wrong_password_and_revokes(client):
    assert client.post('/api/account/password',json={'current_password':'wrong','password':'replacement-pass-123'}).status_code==400
    assert client.post('/api/account/password',json={'current_password':'password-test-123','password':'replacement-pass-123'}).status_code==200
    assert client.get('/api/posts').status_code==401

def test_email_verification_single_use(client,monkeypatch):
    mail=[];monkeypatch.setattr(accounts,'send_email',lambda *args:mail.append(args))
    assert client.post('/api/account/verification').status_code==200
    token=re.search(r'verify=([\w-]+)',mail[0][2])[1]
    assert client.post('/api/auth/verify-email',json={'token':token}).status_code==200
    assert core.one('SELECT email_verified FROM users')['email_verified']==1
    assert client.post('/api/auth/verify-email',json={'token':token}).status_code==400

def test_account_deletion_revokes_and_cleans_up(client):
    create(client)
    assert client.request('DELETE','/api/account',json={'password':'password-test-123','confirmed':True}).status_code==202
    assert client.get('/api/posts').status_code==401
    maintenance.run_once(force=True)
    assert core.one('SELECT COUNT(*) AS n FROM users')['n']==0

def test_retention_deletes_old_media_but_keeps_pending_campaign_and_billing(client):
    a=create(client,'image');b=create(client,'video')
    for p,status in [(a,'published'),(b,'scheduled')]:
        directory=core.settings.data_dir/('images' if p['kind']=='image' else 'videos');directory.mkdir(exist_ok=True)
        name=p['id']+('.jpg' if p['kind']=='image' else '.mp4');(directory/name).write_bytes(b'media')
        core.execute('UPDATE posts SET status=?,output_path=? WHERE id=?',(status,name,p['id']))
    user=core.one('SELECT * FROM users');core.execute('UPDATE users SET last_active_at=?',((datetime.now(timezone.utc)-timedelta(days=11)).isoformat(),))
    maintenance.retain_media(user['id'])
    assert core.one('SELECT output_path FROM posts WHERE id=?',(a['id'],))['output_path'] is None
    assert core.one('SELECT output_path FROM posts WHERE id=?',(b['id'],))['output_path'] is not None
    assert core.one('SELECT COUNT(*) AS n FROM users')['n']==1
    assert core.one("SELECT 1 FROM audit_events WHERE event='media.retention'")

def test_library_and_job_details_are_tenant_scoped(client):
    p=create(client);client.post(f"/api/posts/{p['id']}/render")
    assert len(client.get('/api/jobs').json()['jobs'])==1
    assert len(client.get('/api/library').json()['posts'])==1
    assert client.post('/api/jobs/claim').status_code in (401,403)

def test_regeneration_consumes_credit_and_cannot_bypass_limit(client):
    p=create(client);url=f"/api/posts/{p['id']}/render"
    assert client.post(url).status_code==200
    assert worker._render_one()
    assert client.post(url).status_code==200
    assert worker._render_one()
    assert client.post(url).status_code==403
    assert core.one('SELECT count FROM image_usage')['count']==2

def test_retry_backoff_does_not_block_other_due_job(client):
    a=create(client);b=create(client)
    for p in (a,b):client.post(f"/api/posts/{p['id']}/render")
    core.execute('UPDATE media_jobs SET next_attempt_at=? WHERE post_id=?',((datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),a['id']))
    assert worker._render_one()
    assert core.one('SELECT status FROM posts WHERE id=?',(b['id'],))['status']=='ready'
    assert core.one('SELECT status FROM posts WHERE id=?',(a['id'],))['status']=='rendering'

def test_remote_completion_requires_confirmed_matching_b2_version(client,monkeypatch):
    monkeypatch.setenv('AUTOPOSTS_API_SECRET','test-service-secret-32-characters-minimum')
    p=create(client);client.post(f"/api/posts/{p['id']}/render")
    headers={'Authorization':'Bearer test-service-secret-32-characters-minimum'}
    job=client.post('/api/jobs/claim',headers=headers).json()['job'];assert job
    data={'status':'completed','lease_token':job['lease_token'],'size':10,'sha256':'a'*64,'version_id':'version1'}
    store=Mock();store._confirm.side_effect=storage.StorageError('Upload não confirmado.',code='verification')
    monkeypatch.setattr(storage,'B2Store',lambda:store)
    endpoint=f"/api/jobs/{job['id']}/result"
    assert client.post(endpoint,json=data,headers=headers).status_code==503
    assert core.one('SELECT status FROM media_jobs')['status']=='processing'
    store._confirm.side_effect=None;store._confirm.return_value={'VersionId':'wrong'}
    assert client.post(endpoint,json=data,headers=headers).status_code==503
    store._confirm.return_value={'VersionId':'version1'}
    assert client.post(endpoint,json=data,headers=headers).status_code==200
    assert client.post(endpoint,json=data,headers=headers).status_code==409

def test_failed_remote_delete_preserves_account_until_confirmed(client,monkeypatch):
    p=create(client)
    core.execute("UPDATE posts SET status='ready',output_path='media.jpg',storage_key='users/owner/images/media.jpg',storage_version='v1' WHERE id=?",(p['id'],))
    assert client.request('DELETE','/api/account',json={'password':'password-test-123','confirmed':True}).status_code==202
    store=Mock();store.delete.side_effect=storage.StorageError('Falha temporária',retryable=True)
    monkeypatch.setattr(storage,'B2Store',lambda:store)
    maintenance.run_once(force=True)
    assert core.one('SELECT 1 FROM users')
    assert core.one('SELECT status FROM storage_deletions')['status']=='pending'
    store.delete.side_effect=None;maintenance.run_once(force=True)
    assert core.one('SELECT 1 FROM users') is None

def test_backup_is_consistent_and_cannot_overwrite(client,tmp_path):
    import sqlite3
    from scripts.backup_db import backup
    dest=backup(tmp_path/'backup.db')
    with sqlite3.connect(dest) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0]==1
    assert dest.stat().st_mode&0o777==0o600
    with pytest.raises(FileExistsError):backup(dest)

def test_legal_pages_are_public_and_server_rendered(client):
    for route in ('/terms','/privacy','/data-deletion'):
        r=client.get(route);assert r.status_code==200
        assert '<main' in r.text and 'text/html' in r.headers['content-type']

def test_legacy_password_hash_is_upgraded_on_login(client):
    salt='00112233445566778899aabbccddeeff'
    digest=hashlib.scrypt(b'password-test-123',salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
    core.execute('UPDATE users SET password_hash=?',('scrypt$'+salt+'$'+digest,))
    assert client.post('/api/auth/login',json={'email':'pessoa@example.com','password':'password-test-123'}).status_code==200
    encoded=core.one('SELECT password_hash FROM users')['password_hash']
    assert encoded.startswith('scrypt-v2$') and core.password_matches('password-test-123',encoded)
