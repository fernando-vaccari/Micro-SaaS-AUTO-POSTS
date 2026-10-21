"""Real, opt-in Instagram and Stripe integrations.

Credentials are encrypted at rest and never returned to the browser. Tests replace
HTTP transports; this module never seeds a pretend connection or payment.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.concurrency import run_in_threadpool

from . import core

router = APIRouter()
INSTAGRAM_GRAPH = "https://graph.instagram.com"
STRIPE_API = "https://api.stripe.com/v1"
STATE_COOKIE = "autoposts_instagram_state"
OAUTH_SCOPES = "instagram_business_basic,instagram_business_content_publish"


class IntegrationError(Exception):
    """Safe-to-display provider failure; only polling can be safely retried."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def _public_https(url: str) -> bool:
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.scheme != "https" or not host or parts.username or parts.password:
            return False
        if host in {"localhost", "localhost.localdomain"} or host.endswith((".localhost", ".local", ".internal")):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return "." in host
    except ValueError:
        return False


def _callback_url() -> str:
    return core.settings.instagram_redirect_uri or core.settings.base_url.rstrip("/") + "/api/integrations/instagram/callback"


def _instagram_configured() -> bool:
    return bool(core.settings.instagram_app_id and core.settings.instagram_app_secret)


def _stripe_configured() -> bool:
    from .plans import catalog
    return bool(core.settings.stripe_secret_key and any(p['stripe_price_id'] for p in catalog().values()) and core.settings.stripe_webhook_secret)


def _state_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(core.settings.app_secret, salt="instagram-oauth-state-v1")


def _provider_json(response: httpx.Response, *, operation: str, retryable: bool = False) -> dict[str, Any]:
    if response.status_code >= 400:
        if response.status_code in (401, 403):
            message = "A autorização do provedor expirou ou não tem as permissões necessárias. Reconecte a conta."
        elif response.status_code == 429:
            message = "O provedor atingiu o limite de solicitações. Tente novamente mais tarde."
        else:
            message = f"O provedor não concluiu {operation}. Verifique sua configuração."
        raise IntegrationError(message, retryable=retryable and response.status_code >= 500)
    try:
        result = response.json()
    except (ValueError, TypeError):
        raise IntegrationError("O provedor retornou uma resposta inválida.", retryable=retryable) from None
    if not isinstance(result, dict) or result.get("error"):
        raise IntegrationError(f"O provedor recusou {operation}. Verifique a autorização da conta.")
    return result


def _graph_id(value: Any) -> str:
    result = str(value or "")
    if not result.isdigit() or len(result) > 64:
        raise IntegrationError("O Instagram retornou um identificador inválido. Reconecte a conta.")
    return result


def _account_public(account: dict[str, Any]) -> dict[str, Any]:
    return {key: account.get(key) for key in ("id", "provider", "platform_username", "external_id", "expires_at", "created_at")}


@router.get("/api/accounts")
def list_accounts(user: dict = Depends(core.current_user)):
    rows = core.query("SELECT * FROM accounts WHERE user_id = ? ORDER BY created_at DESC", (user["id"],))
    return {"accounts": [_account_public(account) for account in rows]}


@router.delete("/api/accounts/{account_id}")
def delete_account(account_id: str, user: dict = Depends(core.current_user)):
    with core.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        account = db.execute("SELECT id FROM accounts WHERE id = ? AND user_id = ?", (account_id, user["id"])).fetchone()
        if not account:
            raise HTTPException(404, "Conta não encontrada.")
        pending = db.execute("SELECT id FROM posts WHERE account_id = ? AND status IN ('scheduled', 'publishing') LIMIT 1", (account_id,)).fetchone()
        if pending:
            raise HTTPException(409, "Cancele os agendamentos desta conta antes de desconectá-la.")
        db.execute("UPDATE posts SET account_id = NULL WHERE account_id = ? AND user_id = ?", (account_id, user["id"]))
        db.execute("DELETE FROM accounts WHERE id = ? AND user_id = ?", (account_id, user["id"]))
    return {"ok": True}


@router.get("/api/integrations/instagram/authorize")
def instagram_authorize(user: dict = Depends(core.current_user)):
    if not _instagram_configured():
        raise HTTPException(503, "Configure INSTAGRAM_APP_ID e INSTAGRAM_APP_SECRET para conectar o Instagram.")
    callback = _callback_url()
    if not _public_https(callback) or not _public_https(core.settings.base_url):
        raise HTTPException(503, "Configure APP_BASE_URL e o retorno do Instagram com HTTPS público e cadastre a mesma URI no app da Meta.")
    nonce = secrets.token_urlsafe(32)
    state = _state_serializer().dumps({"user_id": user["id"], "nonce": nonce})
    params = {
        "enable_fb_login": "0", "force_authentication": "1",
        "client_id": core.settings.instagram_app_id, "redirect_uri": callback,
        "response_type": "code", "scope": OAUTH_SCOPES, "state": nonce,
    }
    from fastapi.responses import JSONResponse
    response = JSONResponse({"url": "https://www.instagram.com/oauth/authorize?" + urlencode(params)})
    response.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True, secure=core.settings.secure_cookies, samesite="lax", path="/api/integrations/instagram")
    response.headers["Cache-Control"] = "no-store"
    return response


def _oauth_redirect(success: bool) -> RedirectResponse:
    response = RedirectResponse("/?instagram=" + ("connected" if success else "error"), status_code=303)
    response.delete_cookie(STATE_COOKIE, path="/api/integrations/instagram", secure=core.settings.secure_cookies, httponly=True, samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/api/integrations/instagram/callback")
def instagram_callback(request: Request, user: dict = Depends(core.current_user)):
    if not _instagram_configured():
        raise HTTPException(503, "A integração com o Instagram ainda não está configurada.")
    try:
        stored = _state_serializer().loads(request.cookies.get(STATE_COOKIE, ""), max_age=600)
    except (BadSignature, SignatureExpired):
        raise HTTPException(400, "A autorização expirou. Inicie a conexão novamente.") from None
    supplied = request.query_params.get("state", "")
    if stored.get("user_id") != user["id"] or not supplied or not secrets.compare_digest(str(stored.get("nonce", "")).encode(), supplied.encode()):
        raise HTTPException(400, "Estado de autorização inválido. Inicie a conexão novamente.")
    if request.query_params.get("error"):
        return _oauth_redirect(False)
    code = request.query_params.get("code", "").removesuffix("#_")
    if not code or len(code) > 4096:
        raise HTTPException(400, "Código de autorização ausente ou inválido.")
    try:
        with httpx.Client(timeout=25.0, follow_redirects=False) as client:
            short = _provider_json(client.post("https://api.instagram.com/oauth/access_token", data={
                "client_id": core.settings.instagram_app_id,
                "client_secret": core.settings.instagram_app_secret,
                "grant_type": "authorization_code", "redirect_uri": _callback_url(), "code": code,
            }), operation="a autorização do Instagram")
            # Some provider versions wrap the token object in a one-item data list.
            if isinstance(short.get("data"), list) and short["data"]:
                short = short["data"][0]
            short_token = short.get("access_token")
            if not isinstance(short_token, str) or not short_token:
                raise IntegrationError("O Instagram não forneceu a autorização esperada.")
            long = _provider_json(client.get(INSTAGRAM_GRAPH + "/access_token", params={
                "grant_type": "ig_exchange_token", "client_secret": core.settings.instagram_app_secret,
                "access_token": short_token,
            }), operation="a extensão da autorização do Instagram")
            token = long.get("access_token")
            if not isinstance(token, str) or not token:
                raise IntegrationError("O Instagram não forneceu uma autorização duradoura.")
            profile = _provider_json(client.get(INSTAGRAM_GRAPH + "/" + core.settings.graph_version + "/me", params={"fields": "user_id,username"}, headers={"Authorization": "Bearer " + token}), operation="a leitura da conta do Instagram")
        external_id = _graph_id(profile.get("user_id") or profile.get("id") or short.get("user_id"))
        username = profile.get("username")
        if not isinstance(username, str) or not username or len(username) > 100:
            raise IntegrationError("O Instagram não retornou o nome da conta.")
        lifetime = int(long.get("expires_in", 60 * 24 * 60 * 60))
        if lifetime <= 0 or lifetime > 366 * 24 * 60 * 60:
            raise IntegrationError("O Instagram retornou uma validade de autorização inválida.")
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=lifetime)).isoformat()
        encrypted = core.encrypt_secret(token)
        with core.connect() as db:
            db.execute("INSERT INTO accounts (id,user_id,provider,platform_username,external_id,access_token,expires_at,created_at) VALUES (?,?,'instagram',?,?,?,?,?) ON CONFLICT(user_id,provider,external_id) DO UPDATE SET platform_username=excluded.platform_username, access_token=excluded.access_token, expires_at=excluded.expires_at, created_at=excluded.created_at", (core.uid(), user["id"], username, external_id, encrypted, expires_at, core.now()))
    except (httpx.HTTPError, IntegrationError, ValueError, TypeError, KeyError):
        # Provider text/URLs can contain credentials; never propagate them.
        return _oauth_redirect(False)
    return _oauth_redirect(True)


def _refresh_instagram_token(account: dict, token: str) -> str:
    """Refresh a still-valid long-lived token during its final seven days.

    Instagram only permits refresh after the token is at least 24 hours old.
    created_at is reset on reconnection and on successful refresh so this remains
    true for subsequent refreshes without a separate token metadata column.
    """
    expires = datetime.fromisoformat(account["expires_at"].replace("Z", "+00:00"))
    current = datetime.now(timezone.utc)
    if expires - current > timedelta(days=7):
        return token
    try:
        issued = datetime.fromisoformat(str(account.get("created_at", "")).replace("Z", "+00:00"))
        if issued.tzinfo is None or current - issued < timedelta(hours=24):
            return token
    except ValueError:
        raise IntegrationError("Não foi possível validar a autorização do Instagram. Reconecte a conta.") from None
    try:
        with httpx.Client(timeout=25.0, follow_redirects=False) as client:
            payload = _provider_json(client.get(INSTAGRAM_GRAPH + "/refresh_access_token", params={"grant_type": "ig_refresh_token", "access_token": token}), operation="a renovação da autorização do Instagram")
        refreshed = payload.get("access_token")
        lifetime = int(payload.get("expires_in", 0))
        if not isinstance(refreshed, str) or not refreshed or not (24 * 3600 < lifetime <= 366 * 24 * 3600):
            raise ValueError
        encrypted = core.encrypt_secret(refreshed)
        until = (current + timedelta(seconds=lifetime)).isoformat()
        core.execute("UPDATE accounts SET access_token=?, expires_at=?, created_at=? WHERE id=? AND user_id=?", (encrypted, until, current.isoformat(), account["id"], account["user_id"]))
    except (httpx.HTTPError, IntegrationError, ValueError, TypeError):
        raise IntegrationError("Não foi possível renovar a autorização do Instagram. Reconecte a conta antes de tentar novamente.") from None
    return refreshed


def instagram_publish_step(account: dict, video_url: str, caption: str, container_id: str | None = None, *, kind='video') -> dict:
    """Advance one persisted publishing stage, without retrying ambiguous writes."""
    if account.get("provider") != "instagram":
        raise IntegrationError("Selecione uma conta do Instagram.")
    if not _public_https(video_url):
        raise IntegrationError("O vídeo precisa de uma URL HTTPS pública para ser lido pelo Instagram.")
    expiry = account.get("expires_at")
    if expiry:
        try:
            expires = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
                raise IntegrationError("A autorização do Instagram expirou. Reconecte a conta antes de agendar.")
        except ValueError:
            raise IntegrationError("A validade da autorização é inválida. Reconecte a conta.") from None
    if len(caption) > 2200:
        raise IntegrationError("A legenda do Instagram deve ter até 2.200 caracteres.")
    account_id = _graph_id(account.get("external_id"))
    try:
        token = core.decrypt_secret(account["access_token"])
    except Exception:
        raise IntegrationError("Não foi possível abrir a autorização do Instagram. Reconecte a conta.") from None
    if expiry:
        token = _refresh_instagram_token(account, token)
    headers = {"Authorization": "Bearer " + token}
    root = INSTAGRAM_GRAPH + "/" + core.settings.graph_version
    with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=False) as client:
        if not container_id:
            try:
                payload = _provider_json(client.post(root + "/" + account_id + "/media", data=({"image_url":video_url,"caption":caption} if kind=="image" else {"media_type": "REELS", "video_url": video_url, "caption": caption, "share_to_feed": "true"}), headers=headers), operation="a criação do Reel")
                created = _graph_id(payload.get("id"))
            except httpx.HTTPError:
                raise IntegrationError("A criação do Reel não foi confirmada. Revise no Instagram antes de tentar novamente.") from None
            return {"container_id": created, "status": "processing"}
        container_id = _graph_id(container_id)
        try:
            container = _provider_json(client.get(root + "/" + container_id, params={"fields": "status_code,status"}, headers=headers), operation="o processamento do Reel", retryable=True)
        except httpx.HTTPError:
            raise IntegrationError("O Instagram está temporariamente indisponível para consultar o vídeo.", retryable=True) from None
        status = container.get("status_code")
        if status == "IN_PROGRESS":
            return {"container_id": container_id, "status": "processing"}
        if status == "PUBLISHED":
            return {"container_id": container_id, "status": "published"}
        if status in {"ERROR", "EXPIRED"}:
            raise IntegrationError("O Instagram recusou ou expirou o processamento do vídeo. Revise o formato e reconecte a conta se necessário.")
        if status != "FINISHED":
            raise IntegrationError("O Instagram retornou um estado desconhecido. Revise a publicação antes de tentar novamente.")
        try:
            published = _provider_json(client.post(root + "/" + account_id + "/media_publish", data={"creation_id": container_id}, headers=headers), operation="a publicação do Reel")
            media_id = _graph_id(published.get("id"))
        except (httpx.HTTPError, IntegrationError):
            raise IntegrationError("A publicação não foi confirmada. Confira a conta no Instagram antes de tentar novamente para evitar duplicatas.") from None
        return {"container_id": container_id, "status": "published", "media_id": media_id}


def instagram_publish_image_step(account,image_url,caption,container_id=None):
    return instagram_publish_step(account,image_url,caption,container_id,kind='image')


def _stripe_request(method: str, path: str, *, data: dict | None = None, idempotency_key: str | None = None) -> dict:
    headers = {"Stripe-Version": "2025-02-24.acacia", "Authorization": "Bearer " + core.settings.stripe_secret_key}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    try:
        with httpx.Client(timeout=25.0, follow_redirects=False) as client:
            response = client.request(method, STRIPE_API + path, data=data, headers=headers)
        return _provider_json(response, operation="a operação de cobrança")
    except httpx.HTTPError:
        raise IntegrationError("O serviço de cobrança está indisponível. Tente novamente mais tarde.") from None


def _require_stripe() -> None:
    if not _stripe_configured():
        raise HTTPException(503, "Configure STRIPE_SECRET_KEY, STRIPE_PRICE_ID e STRIPE_WEBHOOK_SECRET para ativar assinaturas.")
    if not _public_https(core.settings.base_url):
        raise HTTPException(503, "Configure APP_BASE_URL com HTTPS público antes de ativar a cobrança.")


@router.post("/api/billing/checkout")
def billing_checkout(body:dict=Body(default={}),user:dict=Depends(core.current_user)):
    from .plans import catalog
    _require_stripe()
    if user.get('stripe_subscription_id') and user.get('subscription_status') in {'active','trialing'}:
        raise HTTPException(409,'Use o portal para alterar ou cancelar sua assinatura.')
    selected=catalog().get(body.get('plan','pro'))
    if not selected or not selected['stripe_price_id']:raise HTTPException(503,'Configure o Price ID Stripe do plano selecionado.')
    with core.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        pending=db.execute('SELECT * FROM billing_checkouts WHERE user_id=? AND expires_at>?',(user['id'],core.now())).fetchone()
        if pending:
            if pending['checkout_url'] and pending['plan']==selected['id']:return {'url':pending['checkout_url']}
            raise HTTPException(409,'Há um checkout pendente. Cancele-o na tela de planos antes de escolher outro.')
    if core.settings.production:
        try:price=_stripe_request('GET','/prices/'+selected['stripe_price_id'])
        except IntegrationError as exc:raise HTTPException(503,str(exc)) from None
        recurring=price.get('recurring') or {}
        if price.get('unit_amount')!=selected['price_cents'] or price.get('currency')!='brl' or recurring.get('interval')!='month' or recurring.get('interval_count',1)!=1 or not price.get('active'):
            raise HTTPException(503,'O valor, moeda ou período do Price ID Stripe não corresponde ao plano configurado.')
    data={
      'mode':'subscription','line_items[0][price]':selected['stripe_price_id'],'line_items[0][quantity]':'1',
      'client_reference_id':user['id'],'metadata[user_id]':user['id'],'subscription_data[metadata][user_id]':user['id'],
      'subscription_data[metadata][plan]':selected['id'],'success_url':core.settings.base_url+'/?billing=success',
      'cancel_url':core.settings.base_url+'/?billing=cancelled','allow_promotion_codes':'true',
      'payment_method_collection':'always'}
    if selected['id']=='starter':
        if not user.get('email_verified'):raise HTTPException(403,'Confirme seu e-mail antes de solicitar o teste gratuito.')
        email_hash=hashlib.sha256(user['email'].strip().lower().encode()).hexdigest()
        if not core.one('SELECT 1 FROM trial_identities WHERE email_hash=?',(email_hash,)):
            data['subscription_data[trial_period_days]']='7'
            data['subscription_data[trial_settings][end_behavior][missing_payment_method]']='cancel'
    if user.get('stripe_customer_id'):data['customer']=user['stripe_customer_id']
    else:data['customer_email']=user['email']
    nonce=core.uid()
    with core.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        pending=db.execute('SELECT * FROM billing_checkouts WHERE user_id=? AND expires_at>?',(user['id'],core.now())).fetchone()
        if pending:raise HTTPException(409,'Checkout em processamento. Atualize a tela em alguns instantes.')
        db.execute('INSERT OR REPLACE INTO billing_checkouts VALUES(?,?,?,NULL,NULL,?)',(user['id'],selected['id'],nonce,(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()))
    try:
        session=_stripe_request('POST','/checkout/sessions',data=data,idempotency_key='checkout-'+user['id']+'-'+nonce)
        url=session.get('url','');checkout_id=session.get('id','')
        if not isinstance(url,str) or not url.startswith('https://checkout.stripe.com/') or not isinstance(checkout_id,str) or not re.fullmatch(r'cs_[A-Za-z0-9_]+',checkout_id):raise IntegrationError('Checkout inválido retornado pelo provedor.')
        expires=session.get('expires_at',int(time.time())+86400)
        if not isinstance(expires,int) or expires<=time.time() or expires>time.time()+86400+300:raise IntegrationError('Validade do checkout inválida.')
        core.execute('UPDATE billing_checkouts SET checkout_id=?,checkout_url=?,expires_at=? WHERE user_id=? AND nonce=?',(checkout_id,url,datetime.fromtimestamp(expires,timezone.utc).isoformat(),user['id'],nonce))
    except IntegrationError as exc:
        core.execute('DELETE FROM billing_checkouts WHERE user_id=? AND nonce=?',(user['id'],nonce))
        raise HTTPException(502,str(exc)) from None
    return {'url':url}



@router.post("/api/billing/portal")
def billing_portal(user: dict = Depends(core.current_user)):
    _require_stripe()
    if not user.get("stripe_customer_id"):
        raise HTTPException(409, "Sua conta ainda não possui uma assinatura para gerenciar.")
    try:
        session = _stripe_request("POST", "/billing_portal/sessions", data={"customer": user["stripe_customer_id"], "return_url": core.settings.base_url.rstrip("/") + "/"})
    except IntegrationError as exc:
        raise HTTPException(502, str(exc)) from None
    url = session.get("url", "")
    if not isinstance(url, str) or not url.startswith("https://billing.stripe.com/"):
        raise HTTPException(502, "O provedor não retornou um portal válido.")
    return {"url": url}


def _verify_stripe_signature(payload: bytes, signature: str, secret: str, *, timestamp: int | None = None) -> None:
    if not secret:
        raise HTTPException(503, "O webhook de cobrança não está configurado.")
    if len(signature) > 4096:
        raise HTTPException(400, "Assinatura de cobrança inválida.")
    try:
        fields = [pair.split("=", 1) for pair in signature.split(",")]
        times = [value for key, value in fields if key == "t"]
        signatures = [value for key, value in fields if key == "v1"]
        if len(times) != 1 or not signatures:
            raise ValueError
        signed_at = int(times[0])
    except (ValueError, TypeError):
        raise HTTPException(400, "Assinatura de cobrança inválida.") from None
    if abs((timestamp if timestamp is not None else int(time.time())) - signed_at) > 300:
        raise HTTPException(400, "A assinatura de cobrança expirou.")
    expected = hmac.new(secret.encode(), str(signed_at).encode() + b"." + payload, hashlib.sha256).hexdigest()
    if not any(len(candidate) == 64 and all(char in "0123456789abcdef" for char in candidate) and hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise HTTPException(400, "Assinatura de cobrança inválida.")


def _subscription_change(event: dict) -> dict | None:
    event_type = event.get("type", "")
    data = event.get("data", {})
    obj = data.get("object", {}) if isinstance(data, dict) else None
    if not isinstance(obj, dict):
        raise HTTPException(400, "Evento de cobrança inválido.")
    if event_type == "checkout.session.completed":
        if obj.get("mode") != "subscription" or not obj.get("subscription"):
            return None
        subscription_id = obj["subscription"]
    elif event_type in {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}:
        subscription_id = obj.get("id")
    elif event_type in {"invoice.paid","invoice.payment_failed"}:
        subscription_id=obj.get("subscription") or obj.get("parent",{}).get("subscription_details",{}).get("subscription")
        if not subscription_id:return None
    else:
        return None
    if not isinstance(subscription_id, str) or not subscription_id.startswith("sub_") or not subscription_id.replace("_", "").isalnum():
        raise HTTPException(400, "Assinatura inválida no evento de cobrança.")
    # Read current provider state instead of trusting possibly out-of-order events.
    try:
        subscription = _stripe_request("GET", "/subscriptions/" + subscription_id)
    except IntegrationError as exc:
        raise HTTPException(502, str(exc)) from None
    customer = subscription.get("customer")
    if isinstance(customer, dict):
        customer = customer.get("id")
    metadata = subscription.get("metadata") or {}
    user_id = metadata.get("user_id") if isinstance(metadata, dict) else None
    if not isinstance(customer, str) or not customer.startswith("cus_") or not isinstance(user_id, str):
        return None
    items = subscription.get("items", {}).get("data", [])
    from .plans import catalog
    selected=next((p for p in catalog().values() if p['stripe_price_id'] and any(isinstance(i,dict) and isinstance(i.get('price'),dict) and i['price'].get('id')==p['stripe_price_id'] for i in items)),None)
    if not selected:return None
    status=subscription.get('status','inactive')
    active=status in {'active','trialing'}
    until=subscription.get('current_period_end') or max((i.get('current_period_end',0) for i in items if isinstance(i,dict)),default=0)
    end=datetime.fromtimestamp(until,timezone.utc).isoformat() if isinstance(until,(int,float)) and 0<until<4102444800 else None
    if active and core.settings.production and not end:raise HTTPException(502,'O provedor não confirmou o período da assinatura.')
    return {'user_id':user_id,'customer':customer,'subscription_id':subscription_id,'plan':selected['id'] if active else 'free','status':status,'until':end}



@router.post("/api/billing/webhook")
async def billing_webhook(request: Request):
    if not _stripe_configured():
        raise HTTPException(503, "O webhook de cobrança não está configurado.")
    length = request.headers.get("content-length")
    if length:
        try:
            if int(length) > 1_000_000:
                raise HTTPException(413, "Evento de cobrança muito grande.")
        except ValueError:
            raise HTTPException(400, "Tamanho do evento inválido.") from None
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > 1_000_000:
            raise HTTPException(413, "Evento de cobrança muito grande.")
    payload = bytes(chunks)
    _verify_stripe_signature(payload, request.headers.get("stripe-signature", ""), core.settings.stripe_webhook_secret)
    try:
        event = json.loads(payload)
        if not isinstance(event, dict) or not isinstance(event.get("id"), str) or not event["id"].startswith("evt_"):
            raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(400, "Evento de cobrança inválido.") from None
    if core.one("SELECT id FROM webhook_events WHERE id = ?", (event["id"],)):
        return {"received": True, "duplicate": True}
    change = await run_in_threadpool(_subscription_change, event)
    with core.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT id FROM webhook_events WHERE id = ?", (event["id"],)).fetchone():
            return {"received": True, "duplicate": True}
        if change:
            user = db.execute("SELECT * FROM users WHERE id = ?", (change["user_id"],)).fetchone()
            customer_owner = db.execute("SELECT id FROM users WHERE stripe_customer_id = ? AND id != ?", (change["customer"], change["user_id"])).fetchone()
            if user and not customer_owner:
                existing_customer = user["stripe_customer_id"]
                current_sub = user["stripe_subscription_id"]
                wrong_customer = existing_customer and existing_customer != change["customer"]
                stale_other_subscription = current_sub and current_sub != change["subscription_id"] and (user["plan"] != "free" or change["plan"] == "free")
                if not wrong_customer and not stale_other_subscription:
                    db.execute("UPDATE users SET plan=?,stripe_customer_id=?,stripe_subscription_id=?,subscription_status=?,subscription_until=? WHERE id=?",(change['plan'],change['customer'],change['subscription_id'],change.get('status','active'),change.get('until'),change['user_id']))
                    db.execute('DELETE FROM billing_checkouts WHERE user_id=?',(change['user_id'],))
                    event_obj=event.get('data',{}).get('object',{})
                    amount=event_obj.get('amount_paid',event_obj.get('amount_total',event_obj.get('amount_due')))
                    if type(amount) is not int or not 0<=amount<=1_000_000_000:amount=None
                    currency=event_obj.get('currency','brl')
                    if currency not in {'brl','usd','eur'}:currency=None
                    db.execute('INSERT INTO billing_history VALUES(?,?,?,?,?,?,?,?)',(event['id'],change['user_id'],event.get('type',''),change['plan'],change.get('status'),amount,currency,core.now()))
                    if change.get('status')=='trialing':
                        email_hash=hashlib.sha256(user['email'].strip().lower().encode()).hexdigest()
                        db.execute('INSERT OR IGNORE INTO trial_identities VALUES(?,?)',(email_hash,core.now()))
        db.execute("INSERT INTO webhook_events (id, created_at) VALUES (?, ?)", (event["id"], core.now()))
    return {"received": True}

@router.post('/api/accounts/{account_id}/permissions')
def check_permissions(account_id:str,user:dict=Depends(core.current_user)):
    account=core.one('SELECT * FROM accounts WHERE id=? AND user_id=?',(account_id,user['id']))
    if not account:raise HTTPException(404,'Conta não encontrada.')
    try:
        token=core.decrypt_secret(account['access_token'])
        with httpx.Client(timeout=20.0,follow_redirects=False) as client:
            data=_provider_json(client.get(INSTAGRAM_GRAPH+'/'+core.settings.graph_version+'/'+_graph_id(account['external_id'])+'/permissions',headers={'Authorization':'Bearer '+token}),operation='a verificação de permissões')
        granted={p.get('permission') for p in data.get('data',[]) if isinstance(p,dict) and p.get('status')=='granted'}
        required={'instagram_business_basic','instagram_business_content_publish'}
        return {'ok':required.issubset(granted),'required':sorted(required),'granted':sorted(required.intersection(granted))}
    except Exception:raise HTTPException(502,'Não foi possível verificar as permissões. Confira a autorização e a revisão do aplicativo Meta.') from None


@router.post('/api/billing/checkout/cancel')
def cancel_checkout(user:dict=Depends(core.current_user)):
    pending=core.one('SELECT * FROM billing_checkouts WHERE user_id=?',(user['id'],))
    if not pending:return {'ok':True}
    if pending['checkout_id'] and pending['expires_at']>core.now():
        try:_stripe_request('POST','/checkout/sessions/'+pending['checkout_id']+'/expire')
        except IntegrationError:raise HTTPException(409,'Não foi possível expirar o checkout. Ele pode ter sido concluído; atualize a assinatura antes de continuar.') from None
    elif not pending['checkout_id'] and pending['expires_at']>core.now():raise HTTPException(409,'Aguarde a criação do checkout terminar.')
    core.execute('DELETE FROM billing_checkouts WHERE user_id=? AND nonce=?',(user['id'],pending['nonce']))
    return {'ok':True}
