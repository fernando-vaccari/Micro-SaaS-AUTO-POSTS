"""Single-instance, restart-safe render and Instagram publication worker."""
from __future__ import annotations

import fcntl
import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import IO
from urllib.parse import urlsplit

from . import core
from .media import RenderError, render_post

logger = logging.getLogger(__name__)
POLL_SECONDS = 1.0
PUBLISH_POLL_SECONDS = 15
MAX_PUBLISH_POLLS = 120
_stop = threading.Event()
_thread: threading.Thread | None = None
_lock_file: IO | None = None
_lifecycle_lock = threading.Lock()


def _later(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _fail(post_id: str, message: str, expected_status: str) -> None:
    core.execute(
        "UPDATE posts SET status='failed', last_error=?, next_attempt_at=NULL, updated_at=? "
        "WHERE id=? AND status=?",
        (message, core.now(), post_id, expected_status),
    )


def _recover_interrupted_publications() -> None:
    # A crash might occur after Meta accepted publish but before our commit. Never
    # replay that remote side effect automatically. The owner can inspect Instagram.
    core.execute(
        "UPDATE posts SET status='failed', last_error=?, next_attempt_at=NULL, updated_at=? WHERE status='publishing'",
        ("A publicação foi interrompida pelo reinício do servidor. Confira seu Instagram antes de agendar novamente para evitar duplicação.", core.now()),
    )


def _render_one() -> bool:
    post = core.one("SELECT * FROM posts WHERE status='rendering' ORDER BY created_at,id LIMIT 1")
    if not post:
        return False
    try:
        filename = render_post(post)
        core.execute(
            "UPDATE posts SET status='ready', output_path=?, last_error=NULL, updated_at=? "
            "WHERE id=? AND status='rendering'",
            (filename, core.now(), post["id"]),
        )
    except RenderError as exc:
        _fail(post["id"], str(exc), "rendering")
    except Exception:
        # Exception details can contain request credentials; only log identifiers.
        logger.error("Unexpected render failure for post %s", post["id"])
        _fail(post["id"], "Ocorreu uma falha ao renderizar o vídeo. Tente novamente ou contate o suporte.", "rendering")
    return True


def _claim_scheduled() -> None:
    with core.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        post = db.execute(
            "SELECT id FROM posts WHERE status='scheduled' AND scheduled_at<=? ORDER BY scheduled_at,id LIMIT 1",
            (core.now(),),
        ).fetchone()
        if post:
            db.execute(
                "UPDATE posts SET status='publishing', next_attempt_at=?, retry_count=0, last_error=NULL, updated_at=? "
                "WHERE id=? AND status='scheduled'",
                (core.now(), core.now(), post["id"]),
            )
        db.commit()


def _publish_one() -> bool:
    from .integrations import IntegrationError, instagram_publish_step

    _claim_scheduled()
    post = core.one(
        "SELECT * FROM posts WHERE status='publishing' AND (next_attempt_at IS NULL OR next_attempt_at<=?) "
        "ORDER BY scheduled_at,id LIMIT 1",
        (core.now(),),
    )
    if not post:
        return False
    account = core.one("SELECT * FROM accounts WHERE id=? AND user_id=?", (post["account_id"], post["user_id"]))
    if not account:
        _fail(post["id"], "A conta do Instagram não está mais conectada. Reconecte-a e agende novamente.", "publishing")
        return True
    parsed = urlsplit(core.settings.base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        _fail(post["id"], "A publicação exige APP_BASE_URL com um endereço HTTPS público.", "publishing")
        return True
    output = post.get("output_path")
    if not output or Path(output).name != output or not (core.settings.data_dir / "videos" / output).is_file():
        _fail(post["id"], "O arquivo renderizado não está disponível. Gere o vídeo novamente.", "publishing")
        return True
    if post["retry_count"] >= MAX_PUBLISH_POLLS:
        _fail(post["id"], "O Instagram excedeu o tempo de processamento. Confira sua conta antes de tentar novamente.", "publishing")
        return True
    try:
        video_url = f"{core.settings.base_url.rstrip('/')}/media/{post['public_token']}.mp4"
        result = instagram_publish_step(account, video_url, post["caption"], post["container_id"])
        if result.get("status") == "published":
            core.execute(
                "UPDATE posts SET status='published', container_id=?, media_id=?, last_error=NULL, next_attempt_at=NULL, updated_at=? "
                "WHERE id=? AND status='publishing'",
                (result["container_id"], result.get("media_id"), core.now(), post["id"]),
            )
        elif result.get("status") == "processing" and result.get("container_id"):
            # This commit happens before any next call that may publish the media.
            core.execute(
                "UPDATE posts SET container_id=?, retry_count=retry_count+1, next_attempt_at=?, updated_at=? "
                "WHERE id=? AND status='publishing'",
                (result["container_id"], _later(PUBLISH_POLL_SECONDS), core.now(), post["id"]),
            )
        else:
            _fail(post["id"], "O Instagram devolveu uma resposta inesperada. Confira sua conta antes de repetir a publicação.", "publishing")
    except IntegrationError as exc:
        if getattr(exc, "retryable", False) and post["container_id"]:
            core.execute(
                "UPDATE posts SET retry_count=retry_count+1, next_attempt_at=?, updated_at=? WHERE id=? AND status='publishing'",
                (_later(PUBLISH_POLL_SECONDS), core.now(), post["id"]),
            )
        else:
            _fail(post["id"], str(exc), "publishing")
    except Exception:
        logger.error("Unexpected publication failure for post %s", post["id"])
        _fail(post["id"], "Não foi possível confirmar a publicação. Confira seu Instagram antes de tentar novamente para evitar duplicação.", "publishing")
    return True


def run_once() -> None:
    """Process a bounded unit of work (also useful to deterministic smoke tests)."""
    _publish_one()
    if not _stop.is_set():
        _render_one()


def _run() -> None:
    while not _stop.is_set():
        try:
            run_once()
        except Exception:
            logger.error("Worker iteration failed; retrying without replaying remote side effects")
        _stop.wait(POLL_SECONDS)


def start_worker() -> threading.Thread:
    """Start after init_db; refuse a second worker for the same data directory."""
    global _thread, _lock_file
    with _lifecycle_lock:
        if _thread is not None and _thread.is_alive():
            return _thread
        core.settings.data_dir.mkdir(parents=True, exist_ok=True)
        lock = (core.settings.data_dir / "worker.lock").open("a+")
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            lock.close()
            raise RuntimeError("Um worker já usa este DATA_DIR. Inicie o servidor com apenas um processo Uvicorn.") from exc
        try:
            _recover_interrupted_publications()
            _stop.clear()
            _lock_file = lock
            _thread = threading.Thread(target=_run, name="autoposts-worker", daemon=True)
            _thread.start()
            return _thread
        except Exception:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()
            _lock_file = None
            raise


def stop_worker() -> None:
    """Finish the current bounded operation before allowing another worker."""
    global _thread, _lock_file
    with _lifecycle_lock:
        _stop.set()
        if _thread is not None:
            # FFmpeg itself has a timeout; retaining the lock until it exits avoids
            # a second process touching the same render during graceful shutdown.
            _thread.join(timeout=330)
            if _thread.is_alive():
                raise RuntimeError("O worker não terminou a operação no prazo de encerramento.")
            _thread = None
        if _lock_file is not None:
            fcntl.flock(_lock_file.fileno(), fcntl.LOCK_UN)
            _lock_file.close()
            _lock_file = None
