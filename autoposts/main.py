"""FastAPI application: account sessions, media library and publishing workspace."""
from __future__ import annotations

import io
import json
import os
import secrets
import shutil
import sqlite3
import threading
import time
import warnings
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, field_validator, model_validator

from . import core
from .core import (clear_session, connect, csrf_token, current_user, execute, init_db,
                   is_public_https, now, one, optional_user, owned_post, password_hash,
                   password_matches, public_account, public_post, public_user, query,
                   safe_file, set_session, settings, uid, usage, valid_csrf)

User = Annotated[dict, Depends(current_user)]
MAX_UPLOAD = 10 * 1024 * 1024
IMAGE_PIXELS = 20_000_000
_rate_hits: dict[tuple[str, str], deque] = defaultdict(deque)
_rate_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from .worker import start_worker, stop_worker
    from .automation import init_automation, start_automation, stop_automation
    init_automation()
    try:
        start_worker()
        start_automation()
        yield
    finally:
        stop_automation()
        stop_worker()


app = FastAPI(title='AUTOPOSTS', version='1.0.0', lifespan=lifespan,
              docs_url='/api/docs' if not settings.production else None,
              redoc_url=None)


@app.middleware('http')
async def browser_security(request: Request, call_next):
    if request.url.path.startswith('/api/') and request.method in {'POST', 'PUT', 'PATCH'}:
        body_limit = MAX_UPLOAD + 65536 if request.url.path == '/api/assets' else 1024 * 1024
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > body_limit:
                return JSONResponse({'detail': 'O arquivo ou requisição excede o tamanho permitido.'}, status_code=413)
        request._body = bytes(body)
    if request.url.path.startswith('/api/') and request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and request.url.path != '/api/billing/webhook':
        configured = urlsplit(settings.base_url)
        expected_origin = f'{configured.scheme}://{configured.netloc}'
        origin = request.headers.get('origin')
        if (origin and origin != expected_origin) or request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail': 'Origem da requisição não permitida.'}, status_code=403)
        if not valid_csrf(request):
            return JSONResponse({'detail': 'Sessão de segurança expirada. Recarregue a página e tente novamente.'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
    if request.url.path.startswith('/api/') or request.url.path.startswith('/media/'):
        response.headers['Cache-Control'] = 'no-store'
    if settings.production:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response


def auth_rate_limit(request: Request, kind: str, maximum: int, window: int) -> None:
    ip = request.client.host if request.client else 'unknown'
    key = (kind, ip)
    timestamp = time.monotonic()
    with _rate_lock:
        if len(_rate_hits) > 10000:
            stale = [key for key, values in _rate_hits.items() if not values or values[-1] < timestamp - 3600]
            for old in stale:
                _rate_hits.pop(old, None)
        hits = _rate_hits[key]
        while hits and hits[0] < timestamp - window:
            hits.popleft()
        if len(hits) >= maximum:
            raise HTTPException(429, 'Muitas tentativas. Aguarde alguns minutos antes de tentar novamente.', headers={'Retry-After': str(window)})
        hits.append(timestamp)


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=128)

    @field_validator('email')
    @classmethod
    def email_format(cls, value: str) -> str:
        import re
        value = value.strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('Informe um email válido.')
        return value


class Registration(Credentials):
    name: str = Field(min_length=2, max_length=80)

    @field_validator('name')
    @classmethod
    def name_value(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError('Informe seu nome.')
        return value


class Scene(BaseModel):
    text: str = Field(default='', max_length=420)
    asset_id: str | None = Field(default=None, max_length=64)

    @field_validator('text')
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode='after')
    def content_required(self):
        if not self.text and not self.asset_id:
            raise ValueError('Adicione texto ou uma imagem à cena.')
        return self


class PostInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    caption: str = Field(default='', max_length=2200)
    scenes: list[Scene] = Field(min_length=1, max_length=6)
    duration: int = Field(default=12, ge=6, le=60, strict=True)
    theme: Literal['violet', 'ocean', 'ember'] = 'violet'

    @field_validator('title')
    @classmethod
    def title_value(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('Informe um título.')
        return value


class ScheduleInput(BaseModel):
    scheduled_at: datetime
    account_id: str = Field(min_length=1, max_length=64)

    @field_validator('scheduled_at')
    @classmethod
    def aware_date(cls, value: datetime) -> datetime:
        if not value.tzinfo or value.utcoffset() is None:
            raise ValueError('Informe o fuso horário do agendamento.')
        return value.astimezone(timezone.utc)


def verify_assets(data: PostInput, user: dict) -> None:
    for scene in data.scenes:
        if scene.asset_id and not one('SELECT id FROM assets WHERE id = ? AND user_id = ?', (scene.asset_id, user['id'])):
            raise HTTPException(400, 'Uma imagem selecionada não existe na sua biblioteca.')


def ensure_editable(post: dict) -> None:
    if post['status'] not in {'draft', 'ready', 'failed'}:
        raise HTTPException(409, 'Este post não pode ser editado durante processamento ou após publicação. Cancele o agendamento primeiro.')


@app.get('/health')
def health():
    try:
        one('SELECT 1 AS alive')
    except sqlite3.Error:
        return JSONResponse({'status': 'error', 'database': 'error', 'ffmpeg': bool(shutil.which('ffmpeg'))}, status_code=503)
    ffmpeg = bool(shutil.which('ffmpeg'))
    return JSONResponse({'status': 'ok' if ffmpeg else 'degraded', 'database': 'ok', 'ffmpeg': ffmpeg}, status_code=200 if ffmpeg else 503)


@app.get('/api/session')
def session(request: Request, response: Response):
    user = optional_user(request)
    return {'user': public_user(user) if user else None, 'csrf_token': csrf_token(request, response),
            'integrations': {'instagram': bool(settings.instagram_app_id and settings.instagram_app_secret and is_public_https(settings.base_url)),
                             'stripe': bool(settings.stripe_secret_key and settings.stripe_price_id and settings.stripe_webhook_secret and is_public_https(settings.base_url)),
                             'ai': bool(os.environ.get('AI_API_KEY'))},
            'limits': {'free_posts': core.FREE_POSTS, 'pro_posts': core.PRO_POSTS}}


@app.post('/api/auth/register', status_code=201)
def register(data: Registration, request: Request, response: Response):
    auth_rate_limit(request, 'register', 10, 3600)
    user_id = uid()
    digest = password_hash(data.password)
    try:
        execute('INSERT INTO users(id,email,name,password_hash,created_at) VALUES(?,?,?,?,?)',
                (user_id, data.email, data.name, digest, now()))
    except sqlite3.IntegrityError:
        raise HTTPException(409, 'Este email já possui uma conta. Entre para continuar.')
    clear_session(request, response)
    set_session(response, user_id)
    return {'user': public_user(one('SELECT * FROM users WHERE id = ?', (user_id,)))}


@app.post('/api/auth/login')
def login(data: Credentials, request: Request, response: Response):
    auth_rate_limit(request, 'login', 20, 600)
    user = one('SELECT * FROM users WHERE email = ?', (data.email,))
    if not user:
        password_hash(data.password)  # Keep credential checks comparable for unknown accounts.
        raise HTTPException(401, 'Email ou senha incorretos.')
    if not password_matches(data.password, user['password_hash']):
        raise HTTPException(401, 'Email ou senha incorretos.')
    clear_session(request, response)
    set_session(response, user['id'])
    return {'user': public_user(user)}


@app.post('/api/auth/logout')
def logout(request: Request, response: Response):
    clear_session(request, response)
    return {'ok': True}


@app.get('/api/dashboard')
def dashboard(user: User):
    posts = query('SELECT * FROM posts WHERE user_id = ? ORDER BY created_at DESC LIMIT 100', (user['id'],))
    groups = query('SELECT status, COUNT(*) AS count FROM posts WHERE user_id = ? GROUP BY status', (user['id'],))
    counts = {row['status']: row['count'] for row in groups}
    accounts = query('SELECT * FROM accounts WHERE user_id = ? ORDER BY created_at DESC', (user['id'],))
    return {'stats': {'total': sum(counts.values()), 'scheduled': counts.get('scheduled', 0),
                      'published': counts.get('published', 0), 'rendering': counts.get('rendering', 0)},
            'posts': [public_post(post) for post in posts], 'accounts': [public_account(account) for account in accounts],
            'usage': usage(user)}


@app.get('/api/posts')
def posts(user: User):
    return {'posts': [public_post(post) for post in query('SELECT * FROM posts WHERE user_id = ? ORDER BY created_at DESC LIMIT 500', (user['id'],))]}


@app.post('/api/posts', status_code=201)
def create_post(data: PostInput, user: User):
    verify_assets(data, user)
    post_id = uid()
    timestamp = now()
    month = datetime.now(timezone.utc).strftime('%Y-%m')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current = db.execute('SELECT plan FROM users WHERE id = ?', (user['id'],)).fetchone()
        limit = core.PRO_POSTS if current['plan'] == 'pro' else core.FREE_POSTS
        row = db.execute('SELECT count FROM post_usage WHERE user_id = ? AND month = ?', (user['id'], month)).fetchone()
        if row and row['count'] >= limit:
            raise HTTPException(403, f'Você atingiu o limite de {limit} vídeos neste mês. O limite renova no próximo mês UTC.')
        db.execute('INSERT INTO posts(id,user_id,title,caption,scenes,duration,theme,public_token,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (post_id, user['id'], data.title, data.caption, json.dumps([scene.model_dump() for scene in data.scenes]),
                    data.duration, data.theme, secrets.token_urlsafe(32), timestamp, timestamp))
        db.execute('INSERT INTO post_usage(user_id,month,count) VALUES(?,?,1) ON CONFLICT(user_id,month) DO UPDATE SET count=count+1', (user['id'], month))
    return {'post': public_post(owned_post(post_id, user))}


@app.get('/api/posts/{post_id}')
def get_post(post_id: str, user: User):
    return {'post': public_post(owned_post(post_id, user))}


@app.put('/api/posts/{post_id}')
def edit_post(post_id: str, data: PostInput, user: User):
    verify_assets(data, user)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM posts WHERE id = ? AND user_id = ?', (post_id, user['id'])).fetchone()
        if not row:
            raise HTTPException(404, 'Post não encontrado.')
        post = dict(row)
        ensure_editable(post)
        db.execute("UPDATE posts SET title=?,caption=?,scenes=?,duration=?,theme=?,status='draft',output_path=NULL,public_token=?,last_error=NULL,container_id=NULL,media_id=NULL,scheduled_at=NULL,account_id=NULL,retry_count=0,next_attempt_at=NULL,updated_at=? WHERE id=?",
                   (data.title, data.caption, json.dumps([scene.model_dump() for scene in data.scenes]), data.duration, data.theme,
                    secrets.token_urlsafe(32), now(), post_id))
    if post['output_path']:
        try:
            safe_file('videos', post['output_path']).unlink(missing_ok=True)
        except HTTPException:
            pass
    return {'post': public_post(owned_post(post_id, user))}


@app.delete('/api/posts/{post_id}')
def delete_post(post_id: str, user: User):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM posts WHERE id = ? AND user_id = ?', (post_id, user['id'])).fetchone()
        if not row:
            raise HTTPException(404, 'Post não encontrado.')
        post = dict(row)
        if post['status'] in {'rendering', 'publishing', 'scheduled'}:
            raise HTTPException(409, 'Aguarde o processamento ou cancele o agendamento antes de excluir.')
        db.execute('DELETE FROM posts WHERE id = ?', (post_id,))
    if post['output_path']:
        try:
            safe_file('videos', post['output_path']).unlink(missing_ok=True)
        except HTTPException:
            pass
    return {'ok': True}


@app.post('/api/posts/{post_id}/render')
def render(post_id: str, user: User):
    if not shutil.which('ffmpeg'):
        raise HTTPException(503, 'FFmpeg não está instalado no servidor. Execute a instalação do ambiente.')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM posts WHERE id = ? AND user_id = ?', (post_id, user['id'])).fetchone()
        if not row:
            raise HTTPException(404, 'Post não encontrado.')
        ensure_editable(dict(row))
        db.execute("UPDATE posts SET status='rendering',output_path=NULL,last_error=NULL,container_id=NULL,media_id=NULL,public_token=?,retry_count=0,next_attempt_at=NULL,updated_at=? WHERE id=?",
                   (secrets.token_urlsafe(32), now(), post_id))
    return {'post': public_post(owned_post(post_id, user))}


@app.post('/api/posts/{post_id}/schedule')
def schedule(post_id: str, data: ScheduleInput, user: User):
    if not is_public_https(settings.base_url):
        raise HTTPException(503, 'Configure APP_BASE_URL com o endereço HTTPS público da aplicação antes de agendar. O Instagram precisa baixar o vídeo desse endereço.')
    current_time = datetime.now(timezone.utc)
    if data.scheduled_at <= current_time:
        raise HTTPException(400, 'Escolha uma data futura para o agendamento.')
    if data.scheduled_at > current_time + timedelta(days=365):
        raise HTTPException(400, 'Agende para uma data nos próximos 365 dias.')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM posts WHERE id = ? AND user_id = ?', (post_id, user['id'])).fetchone()
        if not row:
            raise HTTPException(404, 'Post não encontrado.')
        post = dict(row)
        if post['status'] != 'ready' or not post['output_path']:
            raise HTTPException(409, 'Gere o vídeo e aguarde ficar pronto antes de agendar.')
        safe_file('videos', post['output_path'])
        account = db.execute('SELECT * FROM accounts WHERE id = ? AND user_id = ? AND provider = ?', (data.account_id, user['id'], 'instagram')).fetchone()
        if not account:
            raise HTTPException(400, 'Conecte uma conta do Instagram válida para agendar.')
        if account['expires_at'] and account['expires_at'] <= now():
            raise HTTPException(400, 'A conexão com o Instagram expirou. Conecte a conta novamente.')
        db.execute("UPDATE posts SET status='scheduled',scheduled_at=?,account_id=?,last_error=NULL,retry_count=0,next_attempt_at=NULL,updated_at=? WHERE id=?",
                   (data.scheduled_at.isoformat(), data.account_id, now(), post_id))
    return {'post': public_post(owned_post(post_id, user))}


@app.post('/api/posts/{post_id}/unschedule')
def unschedule(post_id: str, user: User):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM posts WHERE id = ? AND user_id = ?', (post_id, user['id'])).fetchone()
        if not row:
            raise HTTPException(404, 'Post não encontrado.')
        if row['status'] != 'scheduled':
            raise HTTPException(409, 'Somente posts agendados podem ser cancelados antes da publicação.')
        db.execute("UPDATE posts SET status='ready',scheduled_at=NULL,account_id=NULL,updated_at=? WHERE id=?", (now(), post_id))
    return {'post': public_post(owned_post(post_id, user))}


@app.get('/api/posts/{post_id}/video')
def video(post_id: str, user: User):
    post = owned_post(post_id, user)
    if not post['output_path']:
        raise HTTPException(404, 'O vídeo ainda não está pronto.')
    return FileResponse(safe_file('videos', post['output_path']), media_type='video/mp4', filename=f"{post['id']}.mp4", content_disposition_type='inline')


@app.get('/media/{public_token}.mp4')
def public_video(public_token: str):
    post = one('SELECT output_path FROM posts WHERE public_token = ? AND output_path IS NOT NULL', (public_token,))
    if not post:
        raise HTTPException(404, 'Vídeo não encontrado.')
    return FileResponse(safe_file('videos', post['output_path']), media_type='video/mp4')


def asset_public(asset: dict) -> dict:
    result = {key: asset[key] for key in ['id', 'original_name', 'media_type', 'kind', 'size', 'created_at']}
    result['url'] = f"/api/assets/{asset['id']}/file"
    return result


@app.get('/api/assets')
def assets(user: User):
    return {'assets': [asset_public(asset) for asset in query('SELECT * FROM assets WHERE user_id = ? ORDER BY created_at DESC', (user['id'],))]}


@app.post('/api/assets', status_code=201)
async def upload_asset(user: User, file: UploadFile = File(...)):
    totals = one('SELECT COUNT(*) AS count,COALESCE(SUM(size),0) AS size FROM assets WHERE user_id = ?', (user['id'],))
    if totals['count'] >= 100 or totals['size'] >= 250 * 1024 * 1024:
        raise HTTPException(403, 'Sua biblioteca atingiu o limite de 100 imagens ou 250 MB.')
    raw = bytearray()
    while chunk := await file.read(65536):
        raw.extend(chunk)
        if len(raw) > MAX_UPLOAD:
            await file.close()
            raise HTTPException(413, 'A imagem deve ter no máximo 10 MB.')
    await file.close()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in {'JPEG', 'PNG', 'WEBP'}:
                    raise ValueError('unsupported')
                if image.width * image.height > IMAGE_PIXELS or max(image.size) > 10000:
                    raise ValueError('too large')
                image.load()
                from PIL import ImageOps
                image = ImageOps.exif_transpose(image)
                if 'A' in image.getbands():
                    background = Image.new('RGB', image.size, '#14141c')
                    background.paste(image, mask=image.getchannel('A'))
                    image = background
                else:
                    image = image.convert('RGB')
                image.thumbnail((2160, 3840), Image.Resampling.LANCZOS)
                clean = io.BytesIO()
                image.save(clean, format='JPEG', quality=90, optimize=True)
                payload = clean.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(400, 'Envie uma imagem JPEG, PNG ou WEBP válida com até 20 megapixels.')
    asset_id = uid()
    filename = asset_id + '.jpg'
    path = settings.data_dir / 'uploads' / filename
    original_name = Path((file.filename or 'imagem').replace('\\', '/')).name[:180]
    try:
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            totals = db.execute('SELECT COUNT(*) AS count,COALESCE(SUM(size),0) AS size FROM assets WHERE user_id = ?', (user['id'],)).fetchone()
            if totals['count'] >= 100 or totals['size'] + len(payload) > 250 * 1024 * 1024:
                raise HTTPException(403, 'Sua biblioteca atingiu o limite de 100 imagens ou 250 MB.')
            path.write_bytes(payload)
            db.execute('INSERT INTO assets(id,user_id,filename,original_name,media_type,kind,size,created_at) VALUES(?,?,?,?,?,?,?,?)',
                       (asset_id, user['id'], filename, original_name, 'image/jpeg', 'image', len(payload), now()))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {'asset': asset_public(one('SELECT * FROM assets WHERE id = ?', (asset_id,)))}


@app.get('/api/assets/{asset_id}/file')
def asset_file(asset_id: str, user: User):
    asset = one('SELECT * FROM assets WHERE id = ? AND user_id = ?', (asset_id, user['id']))
    if not asset:
        raise HTTPException(404, 'Imagem não encontrada.')
    return FileResponse(safe_file('uploads', asset['filename']), media_type=asset['media_type'])


from .integrations import router as integration_router
from .automation import router as automation_router
app.include_router(integration_router)
app.include_router(automation_router)
app.mount('/', StaticFiles(directory=Path(__file__).parent / 'static', html=True), name='frontend')
