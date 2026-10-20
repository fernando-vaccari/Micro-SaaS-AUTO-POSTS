"""A campaign alone drives the real script -> MP4 -> scheduled publication pipeline."""
from datetime import datetime, timedelta, timezone
import json
import subprocess

from autoposts import automation, core, integrations, worker


def test_enabled_campaign_creates_renders_and_publishes_without_manual_post_actions(logged_client, monkeypatch):
    automation.init_automation()
    monkeypatch.setattr(core.settings, 'base_url', 'https://autoposts.example.com')
    user = core.one('SELECT * FROM users')
    core.execute('''INSERT INTO accounts
        (id,user_id,provider,platform_username,external_id,access_token,created_at)
        VALUES(?,?,'instagram',?,?,?,?)''',
        ('instagram-test', user['id'], 'example_creator', '12345678',
         core.encrypt_secret('test-only-not-a-provider-credential'), core.now()))
    payload = {
        'name': 'Ideias para empreender', 'niche': 'produtividade',
        'topics': ['Defina três prioridades por dia. Reserve um horário para se concentrar.'],
        'mode': 'templates', 'account_id': 'instagram-test', 'timezone': 'America/Sao_Paulo',
        'times': ['09:00'], 'enabled': True,
    }
    created = logged_client.post('/api/campaigns', json=payload)
    assert created.status_code == 201, created.text
    campaign_id = created.json()['campaign']['id']
    past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    core.execute('UPDATE campaigns SET next_run_at=? WHERE id=?', (past, campaign_id))
    calls = []

    def provider_step(account, video_url, caption, container_id=None):
        calls.append(container_id)
        assert account['user_id'] == user['id']
        assert video_url.startswith('https://autoposts.example.com/media/')
        assert caption
        if container_id is None:
            return {'status': 'processing', 'container_id': '987654'}
        assert core.one('SELECT container_id FROM posts')['container_id'] == '987654'
        return {'status': 'published', 'container_id': container_id, 'media_id': '987655'}

    monkeypatch.setattr(integrations, 'instagram_publish_step', provider_step)
    automation.tick_once()
    post = core.one('SELECT * FROM posts')
    assert post['status'] == 'rendering'
    assert core.one('SELECT count FROM post_usage')['count'] == 1
    worker._render_one()  # real FFmpeg, no mocked renderer
    post = core.one('SELECT * FROM posts')
    assert post['status'] == 'ready' and post['output_path']
    video = core.settings.data_dir / 'videos' / post['output_path']
    probe = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(video)
    ]))
    stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    assert (stream['width'], stream['height'], stream['codec_name']) == (1080, 1920, 'h264')
    automation.reconcile_runs()
    assert core.one('SELECT status FROM posts')['status'] == 'scheduled'
    worker._publish_one()
    assert core.one('SELECT status FROM posts')['status'] == 'publishing'
    core.execute('UPDATE posts SET next_attempt_at=?', (past,))
    worker._publish_one()
    automation.reconcile_runs()
    assert core.one('SELECT status FROM posts')['status'] == 'published'
    assert core.one('SELECT status FROM automation_runs')['status'] == 'published'
    automation.tick_once()
    worker._publish_one()
    assert len(core.query('SELECT id FROM posts')) == 1
    assert calls == [None, '987654']
