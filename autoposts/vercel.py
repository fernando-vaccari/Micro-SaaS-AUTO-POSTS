"""Vercel web entrypoint: no local database, secrets file, scheduler or AI model.

The persistent application remains autoposts.main:app on its CPU host. Forward
requests once, preserving cookies, CSRF, signed webhooks and idempotency keys.
"""
import asyncio
import ipaddress
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .catalog import public_catalog
from .public_pages import router as legal_router

STATIC = Path(__file__).parent / 'static'
MAX_UPLOAD = 4 * 1024 * 1024
MAX_BODY = MAX_UPLOAD + 65536
MAX_RESPONSE = 4 * 1024 * 1024
PROXY_DEADLINE = 50
HOP_HEADERS = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
               'te', 'trailer', 'transfer-encoding', 'upgrade', 'host', 'content-length'}
app = FastAPI(title='AUTOPOSTS Web', docs_url=None, redoc_url=None, openapi_url=None)


def backend_origin(request):
    value = os.environ.get('AUTOPOSTS_BACKEND_URL', '').strip()
    if not value:
        return None, 'BACKEND_NOT_CONFIGURED'
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or '').lower().rstrip('.')
        if (parsed.scheme != 'https' or not host or parsed.username or parsed.password
                or parsed.path not in ('', '/') or '?' in value or '#' in value
                or parsed.port not in (None, 443) or any(c.isspace() for c in value)):
            raise ValueError('origin')
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if '.' not in host or re.fullmatch(r'[0-9.]+', host) or host.endswith(('.localhost', '.local', '.internal')):
                raise ValueError('host') from None
            if not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in host.split('.')):
                raise ValueError('hostname')
        else:
            if not address.is_global:
                raise ValueError('address')
        frontends = {request.url.hostname}
        for key in ('VERCEL_URL', 'VERCEL_PROJECT_PRODUCTION_URL', 'VERCEL_BRANCH_URL'):
            configured = os.environ.get(key)
            if configured:
                frontends.add(urlsplit('https://' + configured.removeprefix('https://')).hostname)
        if host in {h.lower().rstrip('.') for h in frontends if h}:
            return None, 'BACKEND_PROXY_LOOP'
        return f'https://{parsed.netloc}', None
    except ValueError:
        return None, 'BACKEND_CONFIGURATION_INVALID'


def unavailable(code='BACKEND_UNAVAILABLE', status=503):
    return JSONResponse({'detail': 'O estúdio está temporariamente indisponível. Tente novamente mais tarde.',
                         'code': code}, status_code=status)


@app.middleware('http')
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(self), geolocation=()'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://*.backblazeb2.com https://*.r2.cloudflarestorage.com; media-src 'self' blob: https://*.backblazeb2.com https://*.r2.cloudflarestorage.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
    if request.url.scheme == 'https':
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith(('/api', '/media')) or response.headers.get('content-type', '').startswith('text/html') else 'public, max-age=0, must-revalidate'
    return response


def public_setup(request, code):
    """Public pages can load, but there are no local accounts or pretend sessions."""
    path = request.url.path
    if request.method not in ('GET', 'HEAD'):
        return unavailable(code)
    if path == '/api/session':
        return JSONResponse({'user': None, 'csrf_token': None, 'service_ready': False,
                             'integrations': {'instagram': False, 'stripe': False, 'mercadopago': False, 'ai': False}})
    if path == '/api/plans':
        try:
            return JSONResponse({'plans': public_catalog()})
        except RuntimeError:
            return unavailable('PUBLIC_CATALOG_CONFIGURATION_INVALID')
    if path == '/api/public/config':
        return JSONResponse({'edition': 'demo' if os.environ.get('APP_EDITION') == 'demo' else 'saas',
                             'production': True, 'backend_connected': False, 'service_ready': False,
                             'deployment_status': code, 'publishing_enabled': False, 'billing_enabled': False,
                             'max_upload_bytes': MAX_UPLOAD, 'media_ttl_hours': 10,
                             'operator': os.environ.get('LEGAL_OPERATOR_NAME', ''),
                             'contact': os.environ.get('LEGAL_CONTACT_EMAIL', '')})
    return unavailable(code)


def client():
    # Each invocation owns its transport. No cookies or user data are shared.
    return httpx.AsyncClient(timeout=httpx.Timeout(45, connect=10), follow_redirects=False)


async def forward_request(request: Request):
    origin, error = backend_origin(request)
    if not origin:
        return public_setup(request, error)
    if request.headers.get('x-autoposts-gateway') == 'vercel':
        return unavailable('BACKEND_PROXY_LOOP')
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY:
            return JSONResponse({'detail': 'O envio excede o limite deste endereço. Use arquivos de até 4 MB.',
                                 'code': 'UPLOAD_TOO_LARGE'}, status_code=413)
    hop = HOP_HEADERS | {'accept-encoding', 'x-autoposts-gateway-token', 'x-autoposts-client-ip'} | {h.strip().lower() for h in request.headers.get('connection', '').split(',')}
    headers = [(name, value) for name, value in request.headers.items() if name.lower() not in hop]
    headers.extend([('x-autoposts-gateway', 'vercel'), ('accept-encoding', 'identity')])
    gateway_secret = os.environ.get('AUTOPOSTS_GATEWAY_SECRET', '')
    if len(gateway_secret) >= 32:
        client_ip = request.client.host if request.client else ''
        if os.environ.get('VERCEL') == '1':
            client_ip = request.headers.get('x-vercel-forwarded-for', client_ip).split(',')[0].strip()
        try:
            client_ip = str(ipaddress.ip_address(client_ip))
        except ValueError:
            pass
        else:
            headers.extend([('x-autoposts-gateway-token', gateway_secret), ('x-autoposts-client-ip', client_ip)])
    destination = origin + request.url.path
    if request.url.query:
        destination += '?' + request.url.query
    try:
        async with client() as transport:
            async with transport.stream(request.method, destination, content=bytes(body), headers=headers) as upstream:
                if upstream.status_code >= 500:
                    return unavailable()
                output = bytearray()
                async for chunk in upstream.aiter_bytes():
                    output.extend(chunk)
                    if len(output) > MAX_RESPONSE:
                        return unavailable('BACKEND_RESPONSE_TOO_LARGE', 502)
                payload = bytes(output)
                if upstream.status_code == 200 and request.url.path in ('/api/public/config', '/api/studio/config'):
                    try:
                        settings = json.loads(payload)
                        if not isinstance(settings, dict):
                            raise ValueError('config')
                    except (ValueError, UnicodeDecodeError):
                        return unavailable('BACKEND_RESPONSE_INVALID')
                    if request.url.path == '/api/public/config':
                        settings['backend_connected'] = True
                        settings['max_upload_bytes'] = MAX_UPLOAD
                    else:
                        settings['max_photo_upload_bytes'] = MAX_UPLOAD
                        settings['max_voice_upload_bytes'] = MAX_UPLOAD
                    payload = json.dumps(settings).encode()
                result = Response(payload, status_code=upstream.status_code)
                response_hop = HOP_HEADERS | {'content-encoding', 'x-autoposts-gateway-token', 'x-autoposts-client-ip'} | {h.strip().lower() for h in upstream.headers.get('connection', '').split(',')}
                # Preserve both session and CSRF Set-Cookie headers, never concatenate them.
                result.raw_headers.extend((name, value) for name, value in upstream.headers.raw
                                          if name.decode('latin-1').lower() not in response_hop)
                return result
    except (httpx.HTTPError, httpx.InvalidURL):
        return unavailable()


async def proxy(request: Request):
    try:
        async with asyncio.timeout(PROXY_DEADLINE):
            return await forward_request(request)
    except TimeoutError:
        return unavailable('BACKEND_TIMEOUT')


app.add_api_route('/api/{path:path}', proxy, methods=['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
app.add_api_route('/media/{path:path}', proxy, methods=['GET', 'HEAD'])


@app.get('/health')
async def health(request: Request):
    origin, error = backend_origin(request)
    if not origin:
        return JSONResponse({'status': 'degraded', 'frontend': 'ok', 'service_ready': False, 'code': error}, status_code=503)
    return await proxy(request)


app.include_router(legal_router)


@app.get('/login', include_in_schema=False)
@app.get('/cadastro', include_in_schema=False)
def access_page():
    return FileResponse(STATIC / 'index.html')


app.mount('/', StaticFiles(directory=STATIC, html=True), name='frontend')
