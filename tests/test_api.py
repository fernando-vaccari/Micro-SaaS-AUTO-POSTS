from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from PIL import Image

from autoposts import core


def payload(**overrides):
    return {'title': 'Primeiro vídeo', 'caption': 'Teste de legenda',
            'scenes': [{'text': 'Olá mundo'}, {'text': 'Comece hoje'}],
            'duration': 6, 'theme': 'violet', **overrides}


def test_registration_session_logout_and_revocation(api_client):
    client = api_client
    assert client.get('/api/dashboard').status_code == 401
    response = client.post('/api/auth/register', json={'name': 'Maria', 'email': 'MARIA@example.com', 'password': 'a-valid-password'})
    assert response.status_code == 201
    user = response.json()['user']
    assert user['email'] == 'maria@example.com'
    assert 'password_hash' not in user
    cookie = client.cookies.get(core.SESSION_COOKIE)
    assert client.get('/api/session').json()['user']['id'] == user['id']
    assert client.post('/api/auth/logout').status_code == 200
    assert client.get('/api/dashboard').status_code == 401
    # A copied cookie must become invalid after logout, not just disappear client-side.
    client.cookies.set(core.SESSION_COOKIE, cookie)
    assert client.get('/api/dashboard').status_code == 401
    assert client.post('/api/auth/login', json={'email': user['email'], 'password': 'wrong-but-long-password'}).status_code == 401
    assert client.post('/api/auth/login', json={'email': user['email'], 'password': 'a-valid-password'}).status_code == 200
    row = core.one('SELECT password_hash FROM users WHERE id=?', (user['id'],))
    assert row['password_hash'].startswith('scrypt-v2$32768$8$3$')
    assert core.password_matches('a-valid-password',row['password_hash'])
    assert 'a-valid-password' not in row['password_hash']


def test_csrf_and_cross_origin_are_rejected(logged_client):
    client = logged_client
    assert client.post('/api/posts', json=payload(), headers={'X-CSRF-Token': ''}).status_code == 403
    assert client.post('/api/posts', json=payload(), headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.post('/api/posts', json=payload(), headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert client.post('/api/posts', json=payload(), headers={'Origin': core.settings.base_url}).status_code == 201


def test_post_ownership_all_operations(logged_client):
    client = logged_client
    post_id = client.post('/api/posts', json=payload()).json()['post']['id']
    from autoposts.main import app
    other = TestClient(app)
    other.headers['X-CSRF-Token'] = other.get('/api/session').json()['csrf_token']
    other.post('/api/auth/register', json={'name': 'Outro', 'email': 'outro@example.com', 'password': 'another-valid-password'})
    assert other.get('/api/posts').json()['posts'] == []
    for method, path, body in [('get', f'/api/posts/{post_id}', None), ('put', f'/api/posts/{post_id}', payload()),
                                ('delete', f'/api/posts/{post_id}', None), ('post', f'/api/posts/{post_id}/render', None)]:
        kwargs = {'json': body} if body else {}
        assert getattr(other, method)(path, **kwargs).status_code == 404
    assert other.get(f'/api/posts/{post_id}/video').status_code == 404
    assert client.get(f'/api/posts/{post_id}').status_code == 200
    other.close()


def test_monthly_quota_cannot_be_bypassed_by_deleting(logged_client):
    client = logged_client
    for _ in range(3):
        response = client.post('/api/posts', json=payload())
        assert response.status_code == 201
        assert client.delete('/api/posts/' + response.json()['post']['id']).status_code == 200
    assert client.post('/api/posts', json=payload()).status_code == 403
    assert client.get('/api/dashboard').json()['usage']['used'] == 3


def test_post_validation_and_state_transitions(logged_client):
    client = logged_client
    for data in [payload(duration=5), payload(duration=61), payload(scenes=[]), payload(scenes=[{'text': 'a'}] * 7),
                 payload(scenes=[{'text': 'x' * 421}]), payload(title=' '), payload(theme='evil')]:
        assert client.post('/api/posts', json=data).status_code == 422
    assert client.post('/api/posts', json=payload(scenes=[{'text': 'Teste', 'asset_id': 'other-owner'}])).status_code == 400
    post_id = client.post('/api/posts', json=payload(scenes=[{'text': 'x' * 420}])).json()['post']['id']
    assert client.put(f'/api/posts/{post_id}', json=payload(scenes=[{'text': 'y' * 420}])).status_code == 200
    core.execute("UPDATE posts SET status='rendering' WHERE id=?", (post_id,))
    assert client.put(f'/api/posts/{post_id}', json=payload()).status_code == 409
    assert client.delete(f'/api/posts/{post_id}').status_code == 409
    assert client.post(f'/api/posts/{post_id}/render').status_code == 409


def test_upload_decodes_image_strips_metadata_and_checks_owner(logged_client):
    client = logged_client
    image = io.BytesIO()
    Image.new('RGB', (120, 160), 'purple').save(image, format='PNG')
    response = client.post('/api/assets', files={'file': ('../../test.png', image.getvalue(), 'image/png')})
    assert response.status_code == 201, response.text
    asset = response.json()['asset']
    assert asset['original_name'] == 'test.png'
    assert asset['media_type'] == 'image/jpeg'
    assert client.get(asset['url']).content.startswith(b'\xff\xd8')
    assert client.post('/api/assets', files={'file': ('payload.svg', b'<svg onload="alert(1)"></svg>', 'image/svg+xml')}).status_code == 400
    from autoposts.main import app
    assert TestClient(app).get(asset['url']).status_code == 401
    stranger_id = core.uid()
    core.execute('INSERT INTO users(id,email,name,password_hash,created_at) VALUES(?,?,?,?,?)', (stranger_id, 'stranger@example.com', 'Outra', 'not-used', core.now()))
    core.execute('UPDATE assets SET user_id=? WHERE id=?', (stranger_id, asset['id']))
    assert client.get(asset['url']).status_code == 404
    assert client.post('/api/posts', json=payload(scenes=[{'text': 'Teste', 'asset_id': asset['id']}])).status_code == 400


def test_schedule_requires_public_url_and_owner_account(logged_client, monkeypatch):
    client = logged_client
    post_id = client.post('/api/posts', json=payload()).json()['post']['id']
    body = {'scheduled_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), 'account_id': 'missing'}
    assert client.post(f'/api/posts/{post_id}/schedule', json=body).status_code == 503
    monkeypatch.setattr(core.settings, 'base_url', 'https://app.example.com')
    assert client.post(f'/api/posts/{post_id}/schedule', json=body).status_code == 409
    path = core.settings.data_dir / 'videos' / f'{post_id}.mp4'
    path.write_bytes(b'test-media')
    core.execute("UPDATE posts SET status='ready',output_path=? WHERE id=?", (path.name, post_id))
    assert client.post(f'/api/posts/{post_id}/schedule', json=body).status_code == 400
    user_id = core.one('SELECT user_id FROM posts WHERE id=?', (post_id,))['user_id']
    account_id = core.uid()
    core.execute('INSERT INTO accounts(id,user_id,provider,platform_username,external_id,access_token,created_at) VALUES(?,?,?,?,?,?,?)',
                 (account_id, user_id, 'instagram', 'test', '123', core.encrypt_secret('fake-test-token'), core.now()))
    body['account_id'] = account_id
    assert client.post(f'/api/posts/{post_id}/schedule', json=body).status_code == 200
    assert client.delete(f'/api/posts/{post_id}').status_code == 409
    assert client.post(f'/api/posts/{post_id}/unschedule').json()['post']['status'] == 'ready'
    assert client.get(f'/api/posts/{post_id}/video').status_code == 200
    token = core.one('SELECT public_token FROM posts WHERE id=?', (post_id,))['public_token']
    from autoposts.main import app
    anonymous = TestClient(app)
    assert anonymous.get(f'/media/{token}.mp4').content == b'test-media'
    assert anonymous.get('/media/incorrect-token.mp4').status_code == 404


def test_secrets_round_trip_and_no_value_exposure(isolated_db):
    ciphertext = core.encrypt_secret('a-super-secret-test-value')
    assert 'a-super-secret-test-value' not in ciphertext
    assert core.decrypt_secret(ciphertext) == 'a-super-secret-test-value'


def test_image_upload_body_size_is_bounded(logged_client):
    response = logged_client.post('/api/assets', content=b'x' * (10 * 1024 * 1024 + 65537), headers={'Content-Type': 'application/octet-stream'})
    assert response.status_code == 413
