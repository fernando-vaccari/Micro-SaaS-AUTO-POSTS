"""Durable remote deletion outbox and inactivity-based retention."""
import json
import os
import time
from datetime import datetime,timedelta,timezone
from . import core,storage
_last_run=0.0
_retention_cursor=""

def queue_delete(db,row,reason='replace'):
    key=row.get('storage_key')
    if key:
        db.execute('INSERT OR IGNORE INTO storage_deletions(id,user_id,object_key,version_id,reason,created_at) VALUES(?,?,?,?,?,?)',(core.uid(),row['user_id'],key,row.get('storage_version'),reason,core.now()))

def cleanup_remote(limit=5):
    for item in core.query("SELECT * FROM storage_deletions WHERE status='pending' ORDER BY created_at LIMIT ?",(limit,)):
        try:storage.B2Store().delete(item['object_key'],item['version_id'])
        except storage.StorageError as exc:
            core.execute('UPDATE storage_deletions SET last_error=? WHERE id=?',(str(exc),item['id']));continue
        except Exception:
            core.execute('UPDATE storage_deletions SET last_error=? WHERE id=?',('Falha ao excluir objeto; credenciais não foram registradas.',item['id']));continue
        with core.connect() as db:
            db.execute("UPDATE storage_deletions SET status='completed',last_error=NULL WHERE id=?",(item['id'],))
            db.execute('INSERT INTO audit_events(user_id,event,object_id,detail,created_at) VALUES(?,?,?,?,?)',(item['user_id'],'media.remote_deleted',item['id'],item['reason'],core.now()))

def _remove_local(directory,filename):
    if not filename:return
    try:core.safe_file(directory,filename).unlink(missing_ok=True)
    except Exception:pass

def retain_media(user_id,force=False):
    """Never remove media while queued/publishing or referenced by pending work."""
    stamp=core.now()
    with core.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        user=db.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
        if not user:return
        threshold=(datetime.now(timezone.utc)-timedelta(days=max(1,int(os.environ.get('MEDIA_RETENTION_DAYS','10'))))).isoformat()
        if not force and (user['last_active_at'] or user['created_at'])>threshold:return
        posts=db.execute("SELECT * FROM posts p WHERE user_id=? AND output_path IS NOT NULL AND status IN ('ready','published','failed','draft') AND NOT EXISTS(SELECT 1 FROM media_jobs j WHERE j.post_id=p.id AND j.status IN ('pending','processing')) AND NOT EXISTS(SELECT 1 FROM automation_runs r WHERE r.post_id=p.id AND r.preview=0 AND r.status IN ('queued','generating','rendering','scheduled'))",(user_id,)).fetchall()
        for raw in posts:
            row=dict(raw);queue_delete(db,row,'account_delete' if force else 'inactivity')
            db.execute('UPDATE posts SET storage_key=NULL,output_path=NULL,media_deleted_at=?,updated_at=? WHERE id=?',(stamp,stamp,row['id']))
            db.execute('INSERT INTO audit_events(user_id,event,object_id,detail,created_at) VALUES(?,?,?,?,?)',(user_id,'media.retention',row['id'],'account_delete' if force else 'inactivity',stamp))
            _remove_local('images' if row['kind']=='image' else 'videos',row['output_path'])
        protected=set()
        if not force:
            for p in db.execute("SELECT scenes,brand_config FROM posts WHERE user_id=? AND status IN ('draft','rendering','scheduled','publishing')",(user_id,)):
                protected.update(x.get('asset_id') for x in json.loads(p['scenes']))
                protected.add(json.loads(p['brand_config'] or '{}').get('logo_asset_id'))
            for c in db.execute('SELECT brand_config FROM campaigns WHERE user_id=? AND enabled=1',(user_id,)):
                protected.add(json.loads(c['brand_config'] or '{}').get('logo_asset_id'))
        for raw in db.execute('SELECT * FROM assets WHERE user_id=? AND deleted_at IS NULL',(user_id,)).fetchall():
            row=dict(raw)
            if row['id'] in protected:continue
            queue_delete(db,row,'account_delete' if force else 'inactivity')
            db.execute('UPDATE assets SET deleted_at=?,storage_key=NULL WHERE id=?',(stamp,row['id']))
            _remove_local('uploads',row['filename'])

def run_once(force=False):
    global _last_run,_retention_cursor
    if not force and time.monotonic()-_last_run<60:return
    _last_run=time.monotonic()
    batch=core.query('SELECT id FROM users WHERE id>? ORDER BY id LIMIT 100',(_retention_cursor,))
    for u in batch:retain_media(u['id'])
    _retention_cursor=batch[-1]['id'] if len(batch)==100 else ''
    for request in core.query('SELECT user_id FROM deletion_requests LIMIT 10'):
        retain_media(request['user_id'],True)
    cleanup_remote()
    for request in core.query('SELECT user_id FROM deletion_requests LIMIT 10'):
        if not core.one("SELECT 1 FROM storage_deletions WHERE user_id=? AND status='pending'",(request['user_id'],)):
            core.execute('DELETE FROM users WHERE id=? AND deletion_requested=1',(request['user_id'],))
    core.execute('DELETE FROM recovery_tokens WHERE expires_at<?',(core.now(),))
