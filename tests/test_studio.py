"""Studio, voice privacy, real audio mux, unattended campaigns and expiration."""
import io
import json
import math
import struct
import subprocess
import wave
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from autoposts import core,automation,jobs,worker,maintenance,voices,ai_client


def audio(seconds=4):
    out=io.BytesIO()
    with wave.open(out,'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000)
        wav.writeframes(b''.join(struct.pack('<h',int(8000*math.sin(2*math.pi*440*i/24000))) for i in range(int(seconds*24000))))
    return out.getvalue()

@pytest.fixture
def client(logged_client,monkeypatch):
    automation.init_automation()
    monkeypatch.setenv('APP_EDITION','saas');monkeypatch.delenv('AI_MEDIA_URL',raising=False);monkeypatch.delenv('AI_MEDIA_TOKEN',raising=False)
    monkeypatch.setenv('STORAGE_BACKEND','local')
    return logged_client


def photo(client):
    stream=io.BytesIO();Image.new('RGB',(900,800),'#bfa478').save(stream,'JPEG')
    r=client.post('/api/assets',files={'file':('minha-loja.jpg',stream.getvalue(),'image/jpeg')})
    assert r.status_code==201,r.text
    return r.json()['asset']['id']


def voice(client):
    r=client.post('/api/voices',files={'file':('voz.wav',audio(),'audio/wav')},data={'name':'Minha voz','consent':'true'})
    assert r.status_code==201,r.text
    return r.json()['voice']


def payload(client,**changes):
    data={'title':'Meu estabelecimento','prompt':'Conheça nosso espaço. Venha nos visitar.','asset_ids':[photo(client)],'duration':6}
    data.update(changes);return data


def test_individual_access_pages_and_public_studio_plan(client):
    assert 'microphone=(self)' in client.get('/').headers['Permissions-Policy']
    assert client.get('/login').status_code==200 and client.get('/cadastro').status_code==200
    catalog=client.get('/api/plans').json()['plans']
    assert [(p['id'],p['price_cents']) for p in catalog]==[('studio',14999)]
    assert not client.get('/api/studio/config').json()['generative_video']


def test_voice_requires_consent_and_is_encrypted_and_private(client):
    assert client.post('/api/voices',files={'file':('a.wav',audio(),'audio/wav')},data={'name':'Minha voz'}).status_code==422
    v=voice(client);row=core.one('SELECT * FROM voice_profiles WHERE id=?',(v['id'],))
    encrypted=(core.settings.data_dir/'voices'/row['filename']).read_bytes()
    assert b'RIFF' not in encrypted[:20] and voices.cipher().decrypt(encrypted).startswith(b'RIFF')
    assert client.get(v['audio_url']).headers['content-type']=='audio/wav'
    from autoposts.main import app
    assert TestClient(app).get(v['audio_url']).status_code==401
    assert 'filename' not in v and 'storage_key' not in v
    assert core.one("SELECT 1 FROM audit_events WHERE event='voice.consent'")


@pytest.mark.parametrize('length',[1,31])
def test_audio_duration_rejected(client,length):
    r=client.post('/api/voices',files={'file':('a.wav',audio(length),'audio/wav')},data={'name':'Voz teste','consent':'true'})
    assert r.status_code==422 and not core.one('SELECT 1 FROM voice_profiles')


def test_voice_revocation_prevents_download_and_new_generations(client):
    v=voice(client);data=payload(client,voice_id=v['id'],voice_mode='original')
    assert client.delete('/api/voices/'+v['id']).status_code==200
    assert client.get(v['audio_url']).status_code==404
    assert client.post('/api/studio',json=data).status_code==400
    assert not any((core.settings.data_dir/'voices').glob('*.enc'))


def test_photo_and_voice_ids_are_tenant_scoped(client):
    v=voice(client);identity=photo(client);owner=core.one('SELECT id FROM users')['id']
    other='other-user';core.execute('INSERT INTO users(id,email,name,password_hash,created_at) VALUES(?,?,?,?,?)',(other,'other@example.com','Other','not-login',core.now()))
    core.execute('UPDATE assets SET user_id=? WHERE id=?',(other,identity))
    assert client.post('/api/studio',json={'title':'My store','prompt':'Conheça meu estabelecimento.','asset_ids':[identity]}).status_code==400
    identity=photo(client);core.execute('UPDATE voice_profiles SET user_id=? WHERE id=?',(other,v['id']))
    assert client.post('/api/studio',json={'title':'My store','prompt':'Minha loja.','asset_ids':[identity],'voice_id':v['id'],'voice_mode':'original'}).status_code==400
    assert client.get(v['audio_url']).status_code==404


def test_real_photo_video_with_recorded_audio(client):
    v=voice(client)
    r=client.post('/api/studio',json=payload(client,voice_id=v['id'],voice_mode='original'))
    assert r.status_code==201,r.text
    assert worker._render_one()
    p=core.one('SELECT * FROM posts');assert p['status']=='ready'
    result=client.get(f"/api/posts/{p['id']}/media");assert result.status_code==200
    path=core.settings.data_dir/'videos'/p['output_path']
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(path)]))
    assert any(s['codec_type']=='video' and s['width']==1080 and s['height']==1920 for s in probe['streams'])
    assert any(s['codec_name']=='aac' and s['sample_rate']=='48000' and s['channels']==2 for s in probe['streams'])
    pcm=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-vn','-t','2','-f','s16le','-ac','1','-ar','8000','-'])
    samples=struct.unpack('<'+'h'*(len(pcm)//2),pcm)
    assert sum(abs(x) for x in samples)/len(samples)>500  # Audible, not the previous silent track.
    delta=datetime.fromisoformat(p['media_expires_at'])-datetime.fromisoformat(p['generated_at'])
    assert delta==timedelta(hours=10)


def test_cloning_is_explicit_and_never_falls_back_to_original(client,monkeypatch):
    v=voice(client);data=payload(client,voice_id=v['id'],voice_mode='cloned')
    assert client.post('/api/studio',json=data).status_code==503
    monkeypatch.setenv('AI_VOICE_ENGINE','chatterbox');monkeypatch.setenv('AI_MEDIA_URL','http://127.0.0.1:8005');monkeypatch.setenv('AI_MEDIA_TOKEN','test-private-ai-token-at-least-32-characters')
    synth=Mock(return_value=audio());monkeypatch.setattr(ai_client,'synthesize',synth)
    r=client.post('/api/studio',json=data);assert r.status_code==201,r.text
    worker._render_one();assert core.one('SELECT status FROM posts')['status']=='ready'
    assert synth.call_args.args[1]==data['prompt']
    assert synth.call_args.args[0].startswith(b'RIFF')


def test_demo_allows_creation_without_payment_but_billing_is_blocked(client,monkeypatch):
    monkeypatch.setenv('APP_EDITION','demo');monkeypatch.setattr(core.settings,'production',True)
    assert client.get('/api/public/config').json()['edition']=='demo'
    assert client.get('/api/public/config').json()['publishing_enabled'] is True
    assert client.post('/api/studio',json=payload(client)).status_code==201
    assert client.post('/api/billing/checkout',json={'plan':'studio'}).status_code==403
    assert client.post('/api/billing/portal').status_code==403
    assert client.post('/api/billing/mercadopago/webhook').status_code==403


def test_demo_has_a_separate_default_database_and_no_browser_unlock(client,monkeypatch,tmp_path):
    monkeypatch.setenv('APP_EDITION','demo');monkeypatch.delenv('DEMO_DATA_DIR',raising=False)
    monkeypatch.setenv('DATA_DIR',str(tmp_path/'live'));monkeypatch.setenv('APP_ENV','development')
    assert core.load_settings().data_dir==core.ROOT/'.data-demo'
    data=payload(client)
    monkeypatch.setenv('APP_EDITION','saas');monkeypatch.setattr(core.settings,'production',True)
    assert client.post('/api/studio?edition=demo',json=data).status_code==403


def test_unattended_campaign_runs_from_one_authorization_in_demo(client,monkeypatch):
    monkeypatch.setenv('APP_EDITION','demo')
    monkeypatch.setattr(core.settings,'base_url','https://studio.example.com')
    account='instagram-owned'
    user=core.one('SELECT id FROM users')['id']
    core.execute('INSERT INTO accounts(id,user_id,provider,external_id,platform_username,access_token,created_at) VALUES(?,?,?,?,?,?,?)',(account,user,'instagram','17841401234567890','mybusiness',core.encrypt_secret('test-provider-token'),core.now()))
    r=client.post('/api/studio',json=payload(client,auto_publish=True,account_id=account,publish_time='18:00'))
    assert r.status_code==201,r.text
    campaign=r.json()['campaign'];assert campaign['enabled'] is True
    automation.tick_once();assert worker._render_one()
    automation.reconcile_runs()
    post=core.one('SELECT * FROM posts');assert post['status']=='scheduled'
    assert post['account_id']==account
    # Official publication contracts are tested separately; no real Meta request in this test.


def test_generation_ttl_cleans_active_users_outputs_but_protects_pending_posts(client):
    identity=photo(client)
    r=client.post('/api/studio',json={'title':'Expiry test','prompt':'Nossa loja.','kind':'image','asset_ids':[identity]});assert r.status_code==201
    worker._render_one();p=core.one('SELECT * FROM posts');assert p['output_path']
    core.execute('UPDATE posts SET media_expires_at=? WHERE id=?',((datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(),p['id']))
    core.execute("UPDATE posts SET status='scheduled' WHERE id=?",(p['id'],))
    user=core.one('SELECT id FROM users')['id'];maintenance.retain_media(user)
    assert core.one('SELECT output_path FROM posts')['output_path']
    core.execute("UPDATE posts SET status='published' WHERE id=?",(p['id'],))
    maintenance.retain_media(user)
    assert core.one('SELECT output_path FROM posts')['output_path'] is None
    assert core.one('SELECT media_deleted_at FROM posts')['media_deleted_at']
    assert not (core.settings.data_dir/'images'/p['output_path']).exists()
    assert core.one('SELECT 1 FROM image_usage') and core.one('SELECT 1 FROM assets')


def test_ai_service_validates_auth_and_returns_only_audio(monkeypatch):
    from ai_worker import app as engine
    monkeypatch.setenv('AI_MEDIA_TOKEN','private-test-service-token-more-than-32-chars')
    client=TestClient(engine.app);headers={'Authorization':'Bearer private-test-service-token-more-than-32-chars'}
    assert client.post('/synthesize').status_code==401
    fake=Mock(return_value=audio());monkeypatch.setattr(engine,'synthesize_bytes',fake)
    r=client.post('/synthesize',headers=headers,data={'text':'Minha loja é especial.','language':'pt'},files={'reference':('a.wav',audio(),'audio/wav')})
    assert r.status_code==200 and r.content.startswith(b'RIFF')
    fake.side_effect=ValueError('private-model-details')
    r=client.post('/synthesize',headers=headers,data={'text':'Minha loja.','language':'pt'},files={'reference':('a.wav',audio(),'audio/wav')})
    assert r.status_code==503 and 'private-model-details' not in r.text

@pytest.mark.parametrize('gender',['female','male'])
def test_synthetic_voice_uses_script_without_any_personal_recording(client,monkeypatch,gender):
    monkeypatch.setenv('AI_MEDIA_URL','http://127.0.0.1:8005');monkeypatch.setenv('AI_MEDIA_TOKEN','test-private-ai-token-at-least-32-characters')
    speak=Mock(return_value=audio());monkeypatch.setattr(ai_client,'speak',speak)
    data=payload(client,voice_mode='synthetic_'+gender)
    assert client.post('/api/studio',json=data).status_code==201
    assert worker._render_one() and core.one('SELECT status FROM posts')['status']=='ready'
    assert speak.call_args.args==(data['prompt'],gender)
    assert not core.one('SELECT 1 FROM voice_profiles')


def test_configure_editions_preserves_the_existing_encryption_key(tmp_path,monkeypatch,capsys):
    from scripts import configure_editions as setup
    monkeypatch.setattr(setup,'ROOT',tmp_path)
    (tmp_path/'.env.example').write_text('APP_SECRET=\nAI_MEDIA_TOKEN=\nDATA_DIR=.data\n')
    (tmp_path/'.env.demo.example').write_text('DEMO_APP_SECRET=\nAI_MEDIA_TOKEN=\n')
    data=tmp_path/'.data';data.mkdir();prior='prior-test-encryption-secret-at-least-32-characters';(data/'.app-secret').write_text(prior)
    setup.prepare()
    from dotenv import dotenv_values
    live=dotenv_values(tmp_path/'.env');demo=dotenv_values(tmp_path/'.env.demo')
    assert live['APP_SECRET']==prior
    assert demo['DEMO_APP_SECRET']!=live['APP_SECRET']
    assert len(demo['DEMO_APP_SECRET'])>=32 and demo['AI_MEDIA_TOKEN']==live['AI_MEDIA_TOKEN']
    setup.prepare();assert dotenv_values(tmp_path/'.env')==live and dotenv_values(tmp_path/'.env.demo')==demo
    assert prior not in capsys.readouterr().out


@pytest.mark.parametrize('changes',[
    {'prompt':'   '}, {'title':'  '}, {'timezone':'invalid/timezone'},
    {'voice_mode':'original'},
])
def test_studio_invalid_fields_return_validation_errors(client,changes):
    assert client.post('/api/studio',json=payload(client,**changes)).status_code==422
    assert not core.one('SELECT 1 FROM posts')


def test_studio_duplicate_photos_return_validation_error(client):
    data=payload(client);data['asset_ids']*=2
    assert client.post('/api/studio',json=data).status_code==422


def test_studio_retry_is_idempotent_and_rejects_a_changed_request(client):
    data=payload(client)
    headers={'Idempotency-Key':'studio-request-1234567890'}
    first=client.post('/api/studio',json=data,headers=headers)
    replay=client.post('/api/studio',json=data,headers=headers)
    assert first.status_code==201 and replay.status_code==200
    assert first.json()['post']['id']==replay.json()['post']['id']
    assert replay.headers['Idempotency-Replayed']=='true'
    assert core.one('SELECT COUNT(*) AS n FROM posts')['n']==1
    assert core.one('SELECT count FROM post_usage')['count']==1
    assert core.one('SELECT COUNT(*) AS n FROM media_jobs')['n']==1
    assert client.post('/api/studio',json={**data,'prompt':'Outro roteiro.'},headers=headers).status_code==409


def test_studio_retry_after_post_deletion_does_not_recreate_it(client):
    data=payload(client,kind='image');headers={'Idempotency-Key':'deleted-request-1234567890'}
    created=client.post('/api/studio',json=data,headers=headers).json()['post']
    core.execute("UPDATE posts SET status='ready' WHERE id=?",(created['id'],))
    assert client.delete('/api/posts/'+created['id']).status_code==200
    assert client.post('/api/studio',json=data,headers=headers).status_code==410
    assert not core.one('SELECT 1 FROM posts')
    assert core.one('SELECT count FROM image_usage')['count']==1


def test_studio_queue_failure_rolls_back_creation_and_quota(client,monkeypatch):
    data=payload(client)
    def fail(*args,**kwargs):raise RuntimeError('simulated internal queue failure')
    monkeypatch.setattr(jobs,'enqueue',fail)
    with pytest.raises(RuntimeError):client.post('/api/studio',json=data,headers={'Idempotency-Key':'rollback-request-1234567890'})
    assert not core.one('SELECT 1 FROM posts')
    assert not core.one('SELECT 1 FROM post_usage')


def test_studio_keeps_the_entire_script_with_one_photo(client):
    data=payload(client,prompt='Primeira mensagem. Segunda mensagem. Visite nossa loja hoje!')
    result=client.post('/api/studio',json=data);assert result.status_code==201
    post=core.one('SELECT * FROM posts')
    from autoposts import creative
    renderer=Mock(return_value='unused.mp4')
    creative.render(post,renderer)
    texts=' '.join(s['text'] for s in renderer.call_args.args[0]['scenes'])
    assert 'Segunda mensagem.' in texts and 'Visite nossa loja hoje!' in texts


def test_creative_reuses_photos_without_dropping_scenes(client):
    data=payload(client);assert client.post('/api/studio',json=data).status_code==201
    post=core.one('SELECT * FROM posts')
    post['scenes']=json.dumps([{'text':s} for s in ['Abertura','Mensagem','Convite final']])
    from autoposts import creative
    renderer=Mock(return_value='unused.mp4');creative.render(post,renderer)
    scenes=renderer.call_args.args[0]['scenes']
    assert [s['text'] for s in scenes]==['Abertura','Mensagem','Convite final']
    assert all(s['asset_id']==data['asset_ids'][0] for s in scenes)


def test_concurrent_studio_retries_reserve_only_one_credit(client):
    from concurrent.futures import ThreadPoolExecutor
    data=payload(client);headers={'Idempotency-Key':'parallel-request-1234567890'}
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda _:client.post('/api/studio',json=data,headers=headers),range(3)))
    assert sorted(r.status_code for r in results)==[200,200,201]
    assert len({r.json()['post']['id'] for r in results})==1
    assert core.one('SELECT count FROM post_usage')['count']==1


def test_automatic_studio_retry_with_long_title_is_atomic(client,monkeypatch):
    monkeypatch.setenv('APP_EDITION','demo');monkeypatch.setattr(core.settings,'base_url','https://studio.example.com')
    monkeypatch.setenv('PLAN_STUDIO_VIDEOS','1')
    owner=core.one('SELECT id FROM users')['id']
    core.execute('INSERT INTO accounts(id,user_id,provider,external_id,platform_username,access_token,created_at) VALUES(?,?,?,?,?,?,?)',
                 ('instagram-owned',owner,'instagram','17841401234567890','business',core.encrypt_secret('test-token'),core.now()))
    data=payload(client,title='Meu negócio '+('especial '*11),company_name='AB',auto_publish=True,account_id='instagram-owned')
    headers={'Idempotency-Key':'campaign-request-1234567890'}
    first=client.post('/api/studio',json=data,headers=headers);assert first.status_code==201,first.text
    replay=client.post('/api/studio',json=data,headers=headers);assert replay.status_code==200,replay.text
    assert replay.json()['campaign']['id']==first.json()['campaign']['id']
    assert core.one('SELECT COUNT(*) AS n FROM campaigns')['n']==1
    assert core.one('SELECT COUNT(*) AS n FROM automation_runs')['n']==1
    assert core.one('SELECT count FROM post_usage')['count']==1
    assert client.post('/api/studio',json=data,headers={'Idempotency-Key':'another-campaign-1234567890'}).status_code==429
    assert core.one('SELECT COUNT(*) AS n FROM campaigns')['n']==1
    assert core.one('SELECT COUNT(*) AS n FROM studio_requests')['n']==1


def test_idempotency_keys_are_scoped_to_the_authenticated_user(client):
    headers={'Idempotency-Key':'shared-request-1234567890'}
    first=client.post('/api/studio',json=payload(client),headers=headers).json()['post']
    assert client.post('/api/auth/logout').status_code==200
    registered=client.post('/api/auth/register',json={'name':'Outra pessoa','email':'other@example.com','password':'other-password-123'})
    assert registered.status_code==201
    second=client.post('/api/studio',json=payload(client),headers=headers)
    assert second.status_code==201 and second.json()['post']['id']!=first['id']
    assert client.get('/api/posts/'+first['id']).status_code==404


def test_configure_editions_keeps_a_preexisting_demo_encryption_key(tmp_path,monkeypatch,capsys):
    from scripts import configure_editions as setup
    from dotenv import dotenv_values
    monkeypatch.setattr(setup,'ROOT',tmp_path)
    (tmp_path/'.env.example').write_text('APP_SECRET=\nAI_MEDIA_TOKEN=\n')
    (tmp_path/'.env.demo.example').write_text('DEMO_APP_SECRET=\nDEMO_DATA_DIR=old-demo\n')
    (tmp_path/'old-demo').mkdir()
    previous='old-demo-test-encryption-key-more-than-32-chars'
    (tmp_path/'old-demo'/'.app-secret').write_text(previous)
    setup.prepare()
    assert dotenv_values(tmp_path/'.env.demo')['DEMO_APP_SECRET']==previous
    assert dotenv_values(tmp_path/'.env')['APP_SECRET']!=previous
    assert previous not in capsys.readouterr().out


@pytest.mark.parametrize('key',['short','request with spaces 1234567890','x'*129])
def test_invalid_studio_request_keys_never_reserve_quota(client,key):
    assert client.post('/api/studio',json=payload(client),headers={'Idempotency-Key':key}).status_code==400
    assert not core.one('SELECT 1 FROM posts')
    assert not core.one('SELECT 1 FROM post_usage')
