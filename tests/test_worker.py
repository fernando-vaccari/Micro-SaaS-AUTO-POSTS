from datetime import datetime, timedelta, timezone

import pytest

from autoposts import core, integrations, worker


@pytest.fixture
def job_db(tmp_path, monkeypatch):
    monkeypatch.setattr(core.settings, 'data_dir', tmp_path)
    monkeypatch.setattr(core.settings, 'base_url', 'https://autoposts.example.com')
    core.init_db()
    worker._stop.clear()
    core.execute('INSERT INTO users(id,email,name,password_hash,created_at) VALUES(?,?,?,?,?)',
                 ('owner', 'worker@example.com', 'Pessoa', 'unused', core.now()))
    core.execute('INSERT INTO accounts(id,user_id,provider,platform_username,external_id,access_token,created_at) VALUES(?,?,?,?,?,?,?)',
                 ('account', 'owner', 'instagram', 'creator', 'meta-id', 'unused', core.now()))
    yield tmp_path
    worker._stop.set()


def add_post(status='draft', **updates):
    data = dict(id='post', user_id='owner', title='Ideia', caption='Legenda', scenes='[{"text":"Conteúdo"}]',
                duration=6, theme='violet', status=status, scheduled_at=None, account_id='account', output_path=None,
                public_token='capability-token', container_id=None, media_id=None, last_error=None, retry_count=0,
                next_attempt_at=None, created_at=core.now(), updated_at=core.now())
    data.update(updates)
    fields = ','.join(data)
    placeholders = ','.join('?' for _ in data)
    core.execute(f'INSERT INTO posts({fields}) VALUES({placeholders})', tuple(data.values()))
    return data


def due():
    return (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()


def output_file(job_db):
    (job_db / 'videos' / 'post.mp4').write_bytes(b'placeholder-for-mocked-integration')
    return 'post.mp4'


def test_render_becomes_ready_without_scheduling_or_publishing(job_db, monkeypatch):
    add_post('rendering')
    monkeypatch.setattr(worker, 'render_post', lambda post: 'post.mp4')
    monkeypatch.setattr(integrations, 'instagram_publish_step', lambda *args: pytest.fail('Rendering must not publish'))
    worker.run_once()
    result = core.one('SELECT * FROM posts WHERE id=?', ('post',))
    assert result['status'] == 'ready'
    assert result['scheduled_at'] is None
    assert result['output_path'] == 'post.mp4'


def test_render_error_is_visible_and_not_scheduled(job_db, monkeypatch):
    add_post('rendering')
    def fail(_):
        raise worker.RenderError('Imagem indisponível.')
    monkeypatch.setattr(worker, 'render_post', fail)
    worker._render_one()
    result = core.one('SELECT * FROM posts WHERE id=?', ('post',))
    assert result['status'] == 'failed'
    assert result['last_error'] == 'Imagem indisponível.'


def test_container_is_committed_before_subsequent_publish_step(job_db, monkeypatch):
    add_post('scheduled', scheduled_at=due(), output_path=output_file(job_db))
    calls = []
    def step(account, video_url, caption, container_id):
        calls.append(container_id)
        assert video_url == 'https://autoposts.example.com/media/capability-token.mp4'
        if container_id is None:
            return {'status': 'processing', 'container_id': 'container'}
        stored = core.one('SELECT * FROM posts WHERE id=?', ('post',))
        assert stored['container_id'] == 'container'
        return {'status': 'published', 'container_id': 'container', 'media_id': 'published-media'}
    monkeypatch.setattr(integrations, 'instagram_publish_step', step)
    worker._publish_one()
    first = core.one('SELECT * FROM posts WHERE id=?', ('post',))
    assert first['status'] == 'publishing' and first['container_id'] == 'container'
    core.execute('UPDATE posts SET next_attempt_at=? WHERE id=?', (due(), 'post'))
    worker._publish_one()
    result = core.one('SELECT * FROM posts WHERE id=?', ('post',))
    assert calls == [None, 'container']
    assert result['status'] == 'published' and result['media_id'] == 'published-media'
    worker._publish_one()
    assert len(calls) == 2


def test_ambiguous_publication_is_not_retried(job_db, monkeypatch):
    add_post('scheduled', scheduled_at=due(), output_path=output_file(job_db))
    calls = []
    def fail(*args):
        calls.append(args)
        raise integrations.IntegrationError('Confira seu Instagram antes de repetir.', retryable=False)
    monkeypatch.setattr(integrations, 'instagram_publish_step', fail)
    worker._publish_one()
    worker._publish_one()
    result = core.one('SELECT * FROM posts WHERE id=?', ('post',))
    assert result['status'] == 'failed'
    assert 'Confira' in result['last_error']
    assert len(calls) == 1


def test_safe_container_poll_failure_can_retry(job_db, monkeypatch):
    add_post('publishing', scheduled_at=due(), output_path=output_file(job_db), container_id='saved')
    def fail(*args):
        raise integrations.IntegrationError('Consulta temporariamente indisponível.', retryable=True)
    monkeypatch.setattr(integrations, 'instagram_publish_step', fail)
    worker._publish_one()
    result = core.one('SELECT * FROM posts WHERE id=?', ('post',))
    assert result['status'] == 'publishing'
    assert result['retry_count'] == 1
    assert result['container_id'] == 'saved'
    assert result['next_attempt_at'] > core.now()


def test_restart_does_not_replay_a_possible_remote_publish(job_db):
    add_post('publishing', scheduled_at=due(), container_id='possibly-published')
    worker._recover_interrupted_publications()
    result = core.one('SELECT * FROM posts WHERE id=?', ('post',))
    assert result['status'] == 'failed'
    assert 'duplicação' in result['last_error']
    assert result['container_id'] == 'possibly-published'


def test_unrelated_or_future_posts_are_not_published(job_db, monkeypatch):
    add_post('ready', output_path=output_file(job_db))
    monkeypatch.setattr(integrations, 'instagram_publish_step', lambda *args: pytest.fail('Not explicitly scheduled'))
    assert worker._publish_one() is False
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    core.execute("UPDATE posts SET status='scheduled', scheduled_at=? WHERE id='post'", (future,))
    assert worker._publish_one() is False


def test_post_cannot_publish_through_another_tenants_account(job_db, monkeypatch):
    add_post('scheduled', scheduled_at=due(), output_path=output_file(job_db))
    core.execute('INSERT INTO users(id,email,name,password_hash,created_at) VALUES(?,?,?,?,?)',
                 ('other', 'other@example.com', 'Other', 'unused', core.now()))
    core.execute("UPDATE accounts SET user_id='other' WHERE id='account'")
    monkeypatch.setattr(integrations, 'instagram_publish_step', lambda *args: pytest.fail('Cross-tenant account'))
    worker._publish_one()
    result = core.one('SELECT * FROM posts WHERE id=?', ('post',))
    assert result['status'] == 'failed'


def test_worker_start_and_stop_are_repeatable(job_db, monkeypatch):
    monkeypatch.setattr(worker, '_run', lambda: worker._stop.wait())
    first = worker.start_worker()
    assert worker.start_worker() is first
    worker.stop_worker()
    assert not first.is_alive()
    second = worker.start_worker()
    assert second is not first and second.is_alive()
    worker.stop_worker()
