from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autoposts import automation, core


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'settings', dataclasses.replace(core.settings, data_dir=tmp_path, base_url='https://app.example.com'))
    monkeypatch.delenv('AI_API_KEY', raising=False)
    core.init_db()
    automation.init_automation()
    user = {'id': 'owner', 'email': 'owner@example.com', 'name': 'Owner', 'password_hash': 'unused', 'plan': 'free', 'created_at': core.now()}
    core.execute('INSERT INTO users(id,email,name,password_hash,plan,created_at) VALUES(?,?,?,?,?,?)', tuple(user.values()))
    core.execute('''INSERT INTO accounts(id,user_id,provider,platform_username,external_id,access_token,created_at)
        VALUES('ig','owner','instagram','real_connected_user','external','encrypted-token',?)''', (core.now(),))
    app = FastAPI()
    app.include_router(automation.router)
    app.dependency_overrides[core.current_user] = lambda: user
    with TestClient(app) as client:
        yield client, user


def payload(**changes):
    value = {'name': 'Dicas de jardinagem', 'niche': 'Jardinagem em apartamentos', 'audience': 'Iniciantes',
             'tone': 'didático', 'cta': 'Salve esta dica.', 'topics': ['Observe a terra antes de regar. Solo úmido pode esperar.'],
             'mode': 'templates', 'account_id': 'ig', 'timezone': 'America/Sao_Paulo', 'times': ['09:00'], 'enabled': False}
    value.update(changes)
    return value


def create(client, **changes):
    result = client.post('/api/campaigns', json=payload(**changes))
    assert result.status_code == 201, result.text
    return result.json()['campaign']


def finish_render(post_id):
    filename = post_id + '.mp4'
    (core.settings.data_dir / 'videos' / filename).write_bytes(b'rendered-media')
    core.execute("UPDATE posts SET status='ready',output_path=? WHERE id=?", (filename, post_id))


def test_preview_never_schedules_even_when_campaign_enabled(context):
    client, _ = context
    campaign = create(client, enabled=True)
    response = client.post(f"/api/campaigns/{campaign['id']}/run")
    assert response.status_code == 202
    run = response.json()['run']
    assert run['preview'] is True
    automation.process_run(run['id'])
    post = core.one('SELECT * FROM posts WHERE id=?', (run['post_id'],))
    assert post['status'] == 'rendering'
    assert len(json.loads(post['scenes'])) == 3
    finish_render(run['post_id'])
    automation.reconcile_runs()
    assert core.one('SELECT status FROM posts WHERE id=?', (run['post_id'],))['status'] == 'ready'
    assert core.one('SELECT status FROM automation_runs WHERE id=?', (run['id'],))['status'] == 'rendered'


def test_due_campaign_creates_then_schedules_only_rendered_video(context):
    client, _ = context
    campaign = create(client, enabled=True)
    due = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
    core.execute('UPDATE campaigns SET next_run_at=? WHERE id=?', (due, campaign['id']))
    automation.tick_once()
    runs = core.query('SELECT * FROM automation_runs')
    assert len(runs) == 1
    assert runs[0]['preview'] == 0 and runs[0]['status'] == 'rendering'
    assert core.one('SELECT status FROM posts WHERE id=?', (runs[0]['post_id'],))['status'] == 'rendering'
    # Recovery skips past slots instead of creating four days of catch-up posts.
    automation.tick_once()
    assert len(core.query('SELECT * FROM automation_runs')) == 1
    assert datetime.fromisoformat(core.one('SELECT next_run_at FROM campaigns')['next_run_at']) > datetime.now(timezone.utc)
    finish_render(runs[0]['post_id'])
    automation.reconcile_runs()
    post = core.one('SELECT * FROM posts WHERE id=?', (runs[0]['post_id'],))
    assert post['status'] == 'scheduled' and post['account_id'] == 'ig'
    assert post['container_id'] is None  # Scheduler never talks directly to publication API.


def test_pause_unschedules_and_cancels_pending_automation(context):
    client, _ = context
    campaign = create(client, enabled=True)
    run = automation.enqueue(campaign['id'], preview=False, scheduled_for=core.now())
    automation.process_run(run['id'])
    finish_render(run['post_id'])
    automation.reconcile_runs()
    assert client.put(f"/api/campaigns/{campaign['id']}", json=payload(enabled=False)).status_code == 200
    post = core.one('SELECT * FROM posts WHERE id=?', (run['post_id'],))
    assert post['status'] == 'ready' and post['scheduled_at'] is None
    automation.reconcile_runs()
    assert core.one('SELECT status FROM posts WHERE id=?', (run['post_id'],))['status'] == 'ready'


def test_preview_reservation_is_atomic_and_quota_survives_post_deletion(context):
    client, user = context
    campaign = create(client)
    first = client.post(f"/api/campaigns/{campaign['id']}/run")
    assert first.status_code == 202
    assert client.post(f"/api/campaigns/{campaign['id']}/run").status_code == 409
    first_run = first.json()['run']
    core.execute("UPDATE automation_runs SET status='failed' WHERE id=?", (first_run['id'],))
    core.execute('DELETE FROM posts WHERE id=?', (first_run['post_id'],))
    for _ in range(2):
        run = client.post(f"/api/campaigns/{campaign['id']}/run").json()['run']
        core.execute("UPDATE automation_runs SET status='failed' WHERE id=?", (run['id'],))
        core.execute('DELETE FROM posts WHERE id=?', (run['post_id'],))
    assert core.usage(user)['used'] == 3
    assert client.post(f"/api/campaigns/{campaign['id']}/run").status_code == 429


def test_repeated_scheduled_slot_reserves_quota_only_once(context):
    client, user = context
    campaign = create(client, enabled=True)
    first = automation.enqueue(campaign['id'], preview=False, scheduled_for='2026-10-20T12:00:00+00:00')
    again = automation.enqueue(campaign['id'], preview=False, scheduled_for='2026-10-20T12:00:00+00:00')
    assert first['id'] == again['id']
    assert core.usage(user)['used'] == 1


def test_disabled_draft_needs_no_instagram_or_ai_credentials(context, monkeypatch):
    client, _ = context
    monkeypatch.setattr(core.settings, 'base_url', 'http://127.0.0.1:8000')
    campaign = create(client, account_id=None)
    assert campaign['enabled'] is False and campaign['next_run_at'] is None
    result = client.put(f"/api/campaigns/{campaign['id']}", json=payload(enabled=True, account_id=None))
    assert result.status_code == 503 and 'HTTPS' in result.json()['detail']
    ai = create(client, mode='ai', topics=[], account_id=None)
    result = client.post(f"/api/campaigns/{ai['id']}/run")
    assert result.status_code == 503 and 'AI_API_KEY' in result.json()['detail']


def test_tenant_isolation_and_account_ownership(context):
    client, _ = context
    campaign = create(client)
    core.execute("INSERT INTO users(id,email,name,password_hash,created_at) VALUES('other','other@example.com','Other','unused',?)", (core.now(),))
    client.app.dependency_overrides[core.current_user] = lambda: {'id': 'other', 'plan': 'free'}
    assert client.get('/api/campaigns').json()['campaigns'] == []
    for method, path in [('get', '/runs'), ('post', '/run'), ('delete', '')]:
        assert getattr(client, method)(f"/api/campaigns/{campaign['id']}" + path).status_code == 404
    assert client.post('/api/campaigns', json=payload(account_id='ig')).status_code == 404


def test_invalid_times_timezone_and_empty_topics_rejected(context):
    client, _ = context
    for changes in [{'times': ['25:00']}, {'times': ['09:00', '09:00']}, {'timezone': 'invalid/zone'}, {'topics': []}, {'name': '  '}]:
        assert client.post('/api/campaigns', json=payload(**changes)).status_code == 422


def test_timezone_dst_gap_and_fold():
    gap = automation.next_occurrence(['02:30'], 'America/New_York', datetime.fromisoformat('2025-03-09T05:00:00+00:00'))
    assert gap == '2025-03-10T06:30:00+00:00'
    fold = automation.next_occurrence(['01:30'], 'America/New_York', datetime.fromisoformat('2025-11-02T05:45:00+00:00'))
    assert fold == '2025-11-02T06:30:00+00:00'


def test_ai_generation_validates_provider_output_without_leaking_key(context, monkeypatch):
    client, _ = context
    monkeypatch.setenv('AI_API_KEY', 'secret-not-for-logs')
    campaign = create(client, mode='ai')
    run = automation.enqueue(campaign['id'], preview=True)
    captured = {}
    def respond(url, **kwargs):
        captured.update(kwargs)
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({
            'title': 'Uma dica real', 'caption': 'Aprenda a observar sua planta.',
            'scenes': ['Observe a terra.', 'Se estiver úmida, espere.', 'Salve esta dica.'],
        })}}]})
    monkeypatch.setattr(automation.httpx, 'post', respond)
    automation.process_run(run['id'])
    assert core.one('SELECT status FROM posts WHERE id=?', (run['post_id'],))['status'] == 'rendering'
    assert captured['json']['response_format']['type'] == 'json_object'
    assert captured['headers']['Authorization'] == 'Bearer secret-not-for-logs'
    # A second request with a bad provider payload fails safely and does not publish.
    core.execute("UPDATE automation_runs SET status='rendered' WHERE id=?", (run['id'],))
    bad = automation.enqueue(campaign['id'], preview=True)
    monkeypatch.setattr(automation.httpx, 'post', lambda *a, **kw: httpx.Response(401, json={'error': 'secret-not-for-logs'}))
    automation.process_run(bad['id'])
    failed = core.one('SELECT * FROM automation_runs WHERE id=?', (bad['id'],))
    assert failed['status'] == 'failed'
    assert 'secret-not-for-logs' not in failed['error']
    assert 'autorizada' in failed['error']


def test_restart_preserves_queued_jobs_and_reports_interrupted_ai(context):
    client, _ = context
    campaign = create(client)
    interrupted = automation.enqueue(campaign['id'], preview=True)
    core.execute("UPDATE automation_runs SET status='generating' WHERE id=?", (interrupted['id'],))
    second_campaign = create(client, name='Outra campanha')
    queued = automation.enqueue(second_campaign['id'], preview=True)
    automation._recover_interrupted()
    assert core.one('SELECT status FROM automation_runs WHERE id=?', (interrupted['id'],))['status'] == 'failed'
    assert core.one('SELECT status FROM automation_runs WHERE id=?', (queued['id'],))['status'] == 'queued'
    automation.tick_once()
    assert core.one('SELECT status FROM automation_runs WHERE id=?', (queued['id'],))['status'] == 'rendering'


def test_missing_account_automatically_pauses_without_posting(context):
    client, _ = context
    campaign = create(client, enabled=True)
    core.execute('DELETE FROM accounts WHERE id=?', ('ig',))
    core.execute('UPDATE campaigns SET next_run_at=? WHERE id=?', ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), campaign['id']))
    automation.tick_once()
    row = core.one('SELECT * FROM campaigns WHERE id=?', (campaign['id'],))
    assert row['enabled'] == 0 and row['next_run_at'] is None
    assert 'Conecte' in row['last_error']
    assert core.query('SELECT * FROM posts') == []
