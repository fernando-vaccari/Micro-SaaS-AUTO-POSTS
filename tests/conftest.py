"""Shared, opt-in isolated API fixtures; never start live publication workers."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from autoposts import core


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(core.settings, 'data_dir', tmp_path / 'data')
    monkeypatch.setattr(core.settings, 'base_url', 'http://127.0.0.1:8000')
    monkeypatch.setattr(core.settings, 'secure_cookies', False)
    monkeypatch.setattr(core.settings, 'app_secret', 'test-only-secret-at-least-32-characters-long')
    monkeypatch.setattr(core.settings, 'production', False)
    for key in ['instagram_app_id', 'instagram_app_secret', 'stripe_secret_key', 'stripe_webhook_secret', 'stripe_price_id']:
        monkeypatch.setattr(core.settings, key, '')
    core.init_db()
    return core


@pytest.fixture
def api_client(isolated_db):
    from autoposts.main import app, _rate_hits
    _rate_hits.clear()
    # No context manager: explicit isolation means no lifespan/background network work.
    client = TestClient(app)
    token = client.get('/api/session').json()['csrf_token']
    client.headers['X-CSRF-Token'] = token
    yield client
    client.close()


@pytest.fixture
def logged_client(api_client):
    response = api_client.post('/api/auth/register', json={'name': 'Pessoa Teste', 'email': 'pessoa@example.com', 'password': 'password-test-123'})
    assert response.status_code == 201, response.text
    return api_client
