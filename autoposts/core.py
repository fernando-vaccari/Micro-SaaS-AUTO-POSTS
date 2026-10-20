"""Configuration, SQLite persistence and session primitives for AUTOPOSTS."""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import os
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from fastapi import HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env', override=False)
SESSION_AGE = 60 * 60 * 24 * 30
SESSION_COOKIE = 'autoposts_session'
CSRF_COOKIE = 'autoposts_csrf'
FREE_POSTS = 3
PRO_POSTS = 100


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return uuid4().hex


def is_public_https(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname or ''
        if parsed.scheme != 'https' or not hostname or parsed.username or parsed.password:
            return False
        if hostname.lower() in {'localhost', 'testserver'} or hostname.endswith(('.local', '.localhost', '.internal')):
            return False
        try:
            return ipaddress.ip_address(hostname).is_global
        except ValueError:
            return '.' in hostname
    except ValueError:
        return False


@dataclass
class Settings:
    data_dir: Path
    base_url: str
    app_secret: str
    production: bool
    secure_cookies: bool
    instagram_app_id: str
    instagram_app_secret: str
    instagram_redirect_uri: str
    graph_version: str
    stripe_secret_key: str
    stripe_webhook_secret: str
    stripe_price_id: str


def load_settings() -> Settings:
    data_dir = Path(os.environ.get('DATA_DIR', str(ROOT / '.data'))).expanduser().resolve()
    production = os.environ.get('APP_ENV', 'development').lower() == 'production'
    base_url = os.environ.get('APP_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
    app_secret = os.environ.get('APP_SECRET', '')
    if production:
        if len(app_secret) < 32:
            raise RuntimeError('APP_SECRET deve ter pelo menos 32 caracteres no modo production.')
        if not is_public_https(base_url):
            raise RuntimeError('APP_BASE_URL deve ser uma URL HTTPS pública no modo production.')
    if not app_secret:
        data_dir.mkdir(parents=True, exist_ok=True)
        secret_file = data_dir / '.app-secret'
        try:
            with open(secret_file, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as handle:
                handle.write(secrets.token_urlsafe(48))
        except FileExistsError:
            pass
        app_secret = secret_file.read_text().strip()
    if len(app_secret) < 32:
        raise RuntimeError('APP_SECRET deve ter pelo menos 32 caracteres.')
    return Settings(
        data_dir=data_dir, base_url=base_url, app_secret=app_secret,
        production=production, secure_cookies=base_url.startswith('https://'),
        instagram_app_id=os.environ.get('INSTAGRAM_APP_ID', ''),
        instagram_app_secret=os.environ.get('INSTAGRAM_APP_SECRET', ''),
        instagram_redirect_uri=os.environ.get('INSTAGRAM_REDIRECT_URI', base_url + '/api/integrations/instagram/callback'),
        graph_version=os.environ.get('INSTAGRAM_GRAPH_VERSION', 'v25.0'),
        stripe_secret_key=os.environ.get('STRIPE_SECRET_KEY', ''),
        stripe_webhook_secret=os.environ.get('STRIPE_WEBHOOK_SECRET', ''),
        stripe_price_id=os.environ.get('STRIPE_PRICE_ID', ''),
    )


settings = load_settings()


class ManagedConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, traceback):
        try:
            return super().__exit__(exc_type, exc, traceback)
        finally:
            self.close()


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(settings.data_dir / 'autoposts.db', timeout=15, factory=ManagedConnection)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    db.execute('PRAGMA busy_timeout = 15000')
    return db


def query(sql: str, params=()) -> list[dict]:
    with connect() as db:
        return [dict(row) for row in db.execute(sql, params).fetchall()]


def one(sql: str, params=()) -> dict | None:
    with connect() as db:
        row = db.execute(sql, params).fetchone()
        return dict(row) if row else None


def execute(sql: str, params=()) -> None:
    with connect() as db:
        db.execute(sql, params)


def init_db() -> None:
    for directory in [settings.data_dir, settings.data_dir / 'uploads', settings.data_dir / 'videos', settings.data_dir / 'tmp']:
        directory.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute('PRAGMA journal_mode = WAL')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
            password_hash TEXT NOT NULL, plan TEXT NOT NULL DEFAULT 'free',
            stripe_customer_id TEXT, stripe_subscription_id TEXT, created_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS users_customer ON users(stripe_customer_id) WHERE stripe_customer_id IS NOT NULL;
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL, expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS accounts (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider TEXT NOT NULL, platform_username TEXT NOT NULL, external_id TEXT NOT NULL,
            access_token TEXT NOT NULL, expires_at TEXT, created_at TEXT NOT NULL,
            UNIQUE(user_id, provider, external_id)
        );
        CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            filename TEXT NOT NULL, original_name TEXT NOT NULL, media_type TEXT NOT NULL,
            kind TEXT NOT NULL, size INTEGER NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL, caption TEXT NOT NULL, scenes TEXT NOT NULL,
            duration INTEGER NOT NULL, theme TEXT NOT NULL DEFAULT 'violet', status TEXT NOT NULL DEFAULT 'draft',
            scheduled_at TEXT, account_id TEXT REFERENCES accounts(id) ON DELETE SET NULL,
            output_path TEXT, public_token TEXT NOT NULL UNIQUE, container_id TEXT,
            media_id TEXT, last_error TEXT, retry_count INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS posts_owner_created ON posts(user_id, created_at);
        CREATE INDEX IF NOT EXISTS posts_jobs ON posts(status, scheduled_at, next_attempt_at);
        CREATE TABLE IF NOT EXISTS post_usage (
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            month TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id, month)
        );
        CREATE TABLE IF NOT EXISTS webhook_events (id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
        ''')
        db.execute('DELETE FROM sessions WHERE expires_at < ?', (now(),))


def serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.app_secret, salt=salt)


def encrypt_secret(value: str) -> str:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.app_secret.encode()).digest())
    return Fernet(key).encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.app_secret.encode()).digest())
    return Fernet(key).decrypt(value.encode()).decode()


def public_user(user: dict) -> dict:
    return {key: user[key] for key in ['id', 'email', 'name', 'plan', 'created_at']}


def optional_user(request: Request) -> dict | None:
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        return None
    try:
        data = serializer('session').loads(cookie, max_age=SESSION_AGE)
        session_id = hashlib.sha256(data['sid'].encode()).hexdigest()
    except (BadSignature, SignatureExpired, KeyError, TypeError):
        return None
    return one('SELECT users.* FROM users JOIN sessions ON users.id = sessions.user_id WHERE sessions.id = ? AND sessions.expires_at > ?', (session_id, now()))


def current_user(request: Request) -> dict:
    user = optional_user(request)
    if not user:
        raise HTTPException(401, 'Entre na sua conta para continuar.')
    return user


def set_session(response: Response, user_id: str) -> None:
    from datetime import timedelta
    session_id = secrets.token_urlsafe(32)
    execute('INSERT INTO sessions(id,user_id,created_at,expires_at) VALUES(?,?,?,?)', (
        hashlib.sha256(session_id.encode()).hexdigest(), user_id, now(),
        (datetime.now(timezone.utc) + timedelta(seconds=SESSION_AGE)).isoformat(),
    ))
    response.set_cookie(SESSION_COOKIE, serializer('session').dumps({'sid': session_id}),
                        max_age=SESSION_AGE, httponly=True, secure=settings.secure_cookies, samesite='lax', path='/')


def clear_session(request: Request, response: Response) -> None:
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        try:
            data = serializer('session').loads(cookie, max_age=SESSION_AGE)
            execute('DELETE FROM sessions WHERE id = ?', (hashlib.sha256(data['sid'].encode()).hexdigest(),))
        except (BadSignature, SignatureExpired, KeyError, TypeError):
            pass
    response.delete_cookie(SESSION_COOKIE, path='/', secure=settings.secure_cookies, httponly=True, samesite='lax')


def csrf_token(request: Request, response: Response) -> str:
    try:
        token = serializer('csrf').loads(request.cookies.get(CSRF_COOKIE, ''), max_age=SESSION_AGE)
        if not isinstance(token, str):
            raise BadSignature('invalid payload')
    except (BadSignature, SignatureExpired):
        token = secrets.token_urlsafe(32)
        response.set_cookie(CSRF_COOKIE, serializer('csrf').dumps(token), max_age=SESSION_AGE,
                            httponly=True, secure=settings.secure_cookies, samesite='lax', path='/')
    return token


def valid_csrf(request: Request) -> bool:
    try:
        token = serializer('csrf').loads(request.cookies.get(CSRF_COOKIE, ''), max_age=SESSION_AGE)
        header = request.headers.get('x-csrf-token', '')
        return isinstance(token, str) and bool(header) and hmac.compare_digest(token, header)
    except (BadSignature, SignatureExpired):
        return False


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return 'scrypt$' + salt.hex() + '$' + digest.hex()


def password_matches(password: str, stored: str) -> bool:
    try:
        algorithm, salt, expected = stored.split('$')
        if algorithm != 'scrypt':
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def usage(user: dict) -> dict:
    month = datetime.now(timezone.utc).strftime('%Y-%m')
    row = one('SELECT count FROM post_usage WHERE user_id = ? AND month = ?', (user['id'], month))
    return {'used': row['count'] if row else 0, 'limit': PRO_POSTS if user['plan'] == 'pro' else FREE_POSTS, 'plan': user['plan']}


def owned_post(post_id: str, user: dict) -> dict:
    post = one('SELECT * FROM posts WHERE id = ? AND user_id = ?', (post_id, user['id']))
    if not post:
        raise HTTPException(404, 'Post não encontrado.')
    return post


def public_account(account: dict) -> dict:
    return {key: account.get(key) for key in ['id', 'provider', 'platform_username', 'external_id', 'expires_at', 'created_at']}


def safe_file(directory: str, filename: str) -> Path:
    base = (settings.data_dir / directory).resolve()
    path = (base / filename).resolve()
    if path.parent != base or not path.is_file():
        raise HTTPException(404, 'Arquivo não encontrado.')
    return path


def public_post(post: dict) -> dict:
    import json
    keys = ['id', 'title', 'caption', 'duration', 'theme', 'status', 'scheduled_at', 'account_id',
            'media_id', 'last_error', 'retry_count', 'created_at', 'updated_at']
    result = {key: post.get(key) for key in keys}
    result['scenes'] = json.loads(post['scenes'])
    result['video_url'] = f"/api/posts/{post['id']}/video" if post['output_path'] and (settings.data_dir / 'videos' / post['output_path']).is_file() else None
    return result
