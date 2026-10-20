"""Provider contracts exercised without publishing or charging real accounts."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autoposts import core, integrations


@pytest.fixture
def integration_app(tmp_path, monkeypatch):
    configured = replace(core.settings, data_dir=tmp_path, base_url="https://app.example.com", secure_cookies=False,
                         app_secret="integration-test-secret-32-characters-minimum", instagram_app_id="12345",
                         instagram_app_secret="test-instagram-secret", instagram_redirect_uri="https://app.example.com/api/integrations/instagram/callback",
                         stripe_secret_key="sk_test_not_a_real_key", stripe_webhook_secret="whsec_test_only",
                         stripe_price_id="price_test_pro")
    monkeypatch.setattr(core, "settings", configured)
    core.init_db()
    for identity in ("owner", "other"):
        core.execute("INSERT INTO users (id,email,name,password_hash,created_at) VALUES (?,?,?,?,?)",
                     (identity, identity + "@example.com", identity, "not-a-real-password-hash", core.now()))
    active_user = {"id": "owner"}
    app = FastAPI()
    app.include_router(integrations.router)
    app.dependency_overrides[core.current_user] = lambda: core.one("SELECT * FROM users WHERE id=?", (active_user["id"],))
    with TestClient(app, base_url="https://app.example.com", follow_redirects=False) as client:
        yield client, active_user


def mock_provider(monkeypatch, handler):
    original = httpx.Client
    def make_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)
    monkeypatch.setattr(integrations.httpx, "Client", make_client)


def account(*, remaining_days=60, age_days=0):
    row = {"id": "account1", "user_id": "owner", "provider": "instagram", "platform_username": "criador",
           "external_id": "17841400000000000", "access_token": core.encrypt_secret("test-provider-token"),
           "expires_at": (datetime.now(timezone.utc) + timedelta(days=remaining_days)).isoformat(),
           "created_at": (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat()}
    core.execute("INSERT INTO accounts (id,user_id,provider,platform_username,external_id,access_token,expires_at,created_at) VALUES (:id,:user_id,:provider,:platform_username,:external_id,:access_token,:expires_at,:created_at)", row)
    return row


def signature(payload, *, timestamp=None, key="whsec_test_only"):
    timestamp = timestamp if timestamp is not None else int(time.time())
    digest = hmac.new(key.encode(), str(timestamp).encode() + b"." + payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def subscription_payload(status="active", **changes):
    body = {"id": "sub_test1", "customer": "cus_test1", "metadata": {"user_id": "owner"}, "status": status,
            "items": {"data": [{"price": {"id": "price_test_pro"}}]}}
    body.update(changes)
    return body


def webhook(client, event_id="evt_test1", event_type="customer.subscription.updated"):
    payload = json.dumps({"id": event_id, "type": event_type, "data": {"object": {"id": "sub_test1"}}}).encode()
    return client.post("/api/billing/webhook", content=payload, headers={"Stripe-Signature": signature(payload), "Content-Type": "application/json"})


def test_accounts_never_expose_tokens_and_are_tenant_scoped(integration_app):
    client, active = integration_app
    row = account()
    response = client.get("/api/accounts")
    assert response.status_code == 200
    assert response.json()["accounts"][0]["platform_username"] == "criador"
    assert "access_token" not in response.text
    assert "test-provider-token" not in response.text
    active["id"] = "other"
    assert client.get("/api/accounts").json() == {"accounts": []}
    assert client.delete("/api/accounts/" + row["id"]).status_code == 404
    assert core.one("SELECT id FROM accounts WHERE id=?", (row["id"],))


def test_oauth_authorize_missing_configuration(integration_app, monkeypatch):
    client, _ = integration_app
    monkeypatch.setattr(core.settings, "instagram_app_secret", "")
    assert client.get("/api/integrations/instagram/authorize").status_code == 503


def test_oauth_rejects_non_public_callback(integration_app, monkeypatch):
    client, _ = integration_app
    monkeypatch.setattr(core.settings, "instagram_redirect_uri", "http://127.0.0.1/callback")
    assert client.get("/api/integrations/instagram/authorize").status_code == 503


def test_oauth_state_is_user_bound(integration_app):
    client, active = integration_app
    authorization = client.get("/api/integrations/instagram/authorize")
    state = parse_qs(urlsplit(authorization.json()["url"]).query)["state"][0]
    active["id"] = "other"
    response = client.get("/api/integrations/instagram/callback", params={"state": state, "code": "test-code"})
    assert response.status_code == 400
    assert core.query("SELECT * FROM accounts") == []


def test_oauth_exchanges_token_encrypts_and_redirects(integration_app, monkeypatch):
    client, _ = integration_app
    authorization = client.get("/api/integrations/instagram/authorize")
    auth_query = parse_qs(urlsplit(authorization.json()["url"]).query)
    assert "instagram_business_content_publish" in auth_query["scope"][0]
    calls = []
    def provider(request):
        calls.append(request.url.path)
        if request.url.path == "/oauth/access_token":
            assert request.method == "POST"
            return httpx.Response(200, json={"access_token": "short-test-token", "user_id": "17841400000000000"})
        if request.url.path == "/access_token":
            return httpx.Response(200, json={"access_token": "long-test-token", "expires_in": 5184000})
        if request.url.path.endswith("/me"):
            assert request.headers["authorization"] == "Bearer long-test-token"
            return httpx.Response(200, json={"user_id": "17841400000000000", "username": "criador"})
        raise AssertionError("Unexpected provider call")
    mock_provider(monkeypatch, provider)
    response = client.get("/api/integrations/instagram/callback", params={"state": auth_query["state"][0], "code": "test-code"})
    assert response.status_code == 303
    assert response.headers["location"] == "/?instagram=connected"
    row = core.one("SELECT * FROM accounts WHERE user_id='owner'")
    assert row["access_token"] != "long-test-token"
    assert core.decrypt_secret(row["access_token"]) == "long-test-token"
    assert len(calls) == 3
    # A callback cannot be replayed after its one-time cookie was cleared.
    assert client.get("/api/integrations/instagram/callback", params={"state": auth_query["state"][0], "code": "test-code"}).status_code == 400


def test_create_container_returns_before_publishing(integration_app, monkeypatch):
    row = account()
    calls = []
    def provider(request):
        calls.append(request)
        assert request.url.path.endswith("/media")
        return httpx.Response(200, json={"id": "123456789"})
    mock_provider(monkeypatch, provider)
    result = integrations.instagram_publish_step(row, "https://app.example.com/media/token.mp4", "Olá mundo")
    assert result == {"container_id": "123456789", "status": "processing"}
    assert len(calls) == 1
    assert b"media_type=REELS" in calls[0].content


def test_finished_container_publishes_once(integration_app, monkeypatch):
    row = account()
    calls = []
    def provider(request):
        calls.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json={"status_code": "FINISHED"})
        assert request.url.path.endswith("/media_publish")
        return httpx.Response(200, json={"id": "987654321"})
    mock_provider(monkeypatch, provider)
    result = integrations.instagram_publish_step(row, "https://app.example.com/media/token.mp4", "caption", "123456789")
    assert result["media_id"] == "987654321"
    assert calls == ["GET", "POST"]


def test_already_published_container_never_republishes(integration_app, monkeypatch):
    row = account()
    def provider(request):
        assert request.method == "GET"
        return httpx.Response(200, json={"status_code": "PUBLISHED"})
    mock_provider(monkeypatch, provider)
    assert integrations.instagram_publish_step(row, "https://app.example.com/media/token.mp4", "caption", "123456789")["status"] == "published"


def test_publish_timeout_is_not_retryable_and_redacts_provider_details(integration_app, monkeypatch):
    row = account()
    def provider(request):
        if request.method == "GET":
            return httpx.Response(200, json={"status_code": "FINISHED"})
        raise httpx.ReadTimeout("secret-token-in-unsafe-error", request=request)
    mock_provider(monkeypatch, provider)
    with pytest.raises(integrations.IntegrationError) as captured:
        integrations.instagram_publish_step(row, "https://app.example.com/media/token.mp4", "caption", "123456789")
    assert not captured.value.retryable
    assert "secret-token" not in str(captured.value)
    assert "duplicatas" in str(captured.value)


def test_poll_timeout_is_safe_to_retry(integration_app, monkeypatch):
    row = account()
    def provider(request):
        raise httpx.ReadTimeout("unsafe-provider-details", request=request)
    mock_provider(monkeypatch, provider)
    with pytest.raises(integrations.IntegrationError) as captured:
        integrations.instagram_publish_step(row, "https://app.example.com/media/token.mp4", "caption", "123456789")
    assert captured.value.retryable
    assert "unsafe-provider" not in str(captured.value)


def test_near_expiry_token_is_refreshed_and_persisted_encrypted(integration_app, monkeypatch):
    row = account(remaining_days=3, age_days=50)
    def provider(request):
        if request.url.path == "/refresh_access_token":
            return httpx.Response(200, json={"access_token": "refreshed-test-token", "expires_in": 5184000})
        assert request.headers["Authorization"] == "Bearer refreshed-test-token"
        return httpx.Response(200, json={"id": "123456789"})
    mock_provider(monkeypatch, provider)
    integrations.instagram_publish_step(row, "https://app.example.com/media/token.mp4", "caption")
    stored = core.one("SELECT * FROM accounts WHERE id=?", (row["id"],))
    assert core.decrypt_secret(stored["access_token"]) == "refreshed-test-token"
    assert datetime.fromisoformat(stored["expires_at"]) > datetime.now(timezone.utc) + timedelta(days=59)


def test_expired_authorization_needs_reconnection(integration_app):
    row = account(remaining_days=-1, age_days=80)
    with pytest.raises(integrations.IntegrationError, match="expirou"):
        integrations.instagram_publish_step(row, "https://app.example.com/media/token.mp4", "caption")


def test_stripe_rejects_bad_and_expired_signatures(integration_app):
    client, _ = integration_app
    payload = b'{"id":"evt_test"}'
    assert client.post("/api/billing/webhook", content=payload, headers={"Stripe-Signature": "t=1,v1=bad"}).status_code == 400
    assert client.post("/api/billing/webhook", content=payload, headers={"Stripe-Signature": signature(payload, timestamp=int(time.time()) - 600)}).status_code == 400
    assert core.query("SELECT * FROM webhook_events") == []


def test_stripe_active_subscription_and_replay_guard(integration_app, monkeypatch):
    client, _ = integration_app
    calls = []
    def provider(request):
        calls.append(request)
        assert request.method == "GET" and request.url.path.endswith("/subscriptions/sub_test1")
        return httpx.Response(200, json=subscription_payload())
    mock_provider(monkeypatch, provider)
    assert webhook(client).status_code == 200
    assert core.one("SELECT plan FROM users WHERE id='owner'")["plan"] == "pro"
    duplicate = webhook(client)
    assert duplicate.json()["duplicate"] is True
    assert len(calls) == 1


def test_stripe_cancellation_revokes_pro(integration_app, monkeypatch):
    client, _ = integration_app
    core.execute("UPDATE users SET plan='pro',stripe_customer_id='cus_test1',stripe_subscription_id='sub_test1' WHERE id='owner'")
    mock_provider(monkeypatch, lambda request: httpx.Response(200, json=subscription_payload("canceled")))
    assert webhook(client, event_type="customer.subscription.deleted").status_code == 200
    assert core.one("SELECT plan FROM users WHERE id='owner'")["plan"] == "free"


def test_foreign_stripe_price_cannot_grant_plan(integration_app, monkeypatch):
    client, _ = integration_app
    mock_provider(monkeypatch, lambda request: httpx.Response(200, json=subscription_payload(items={"data": [{"price": {"id": "price_some_other_product"}}]})))
    assert webhook(client).status_code == 200
    assert core.one("SELECT plan FROM users WHERE id='owner'")["plan"] == "free"


def test_checkout_redirect_does_not_grant_plan(integration_app, monkeypatch):
    client, _ = integration_app
    def provider(request):
        assert request.url.path.endswith("/checkout/sessions")
        assert b"subscription_data%5Bmetadata%5D%5Buser_id%5D=owner" in request.content
        return httpx.Response(200, json={"url": "https://checkout.stripe.com/c/pay_test"})
    mock_provider(monkeypatch, provider)
    assert client.post("/api/billing/checkout").json()["url"].startswith("https://checkout.stripe.com/")
    assert core.one("SELECT plan FROM users WHERE id='owner'")["plan"] == "free"


def test_untrusted_unicode_oauth_state_is_rejected(integration_app):
    client, _ = integration_app
    assert client.get("/api/integrations/instagram/authorize").status_code == 200
    response = client.get("/api/integrations/instagram/callback", params={"state": "estado-inválido", "code": "unused"})
    assert response.status_code == 400


def test_untrusted_unicode_signature_is_rejected(integration_app):
    client, _ = integration_app
    payload = b'{"id":"evt_test"}'
    # ASGI headers are bytes; a non-ASCII/latin1 signature must fail closed, not 500.
    response = client.post("/api/billing/webhook", content=payload, headers={b"Stripe-Signature": f"t={int(time.time())},v1=".encode() + b"\xe1"})
    assert response.status_code == 400
