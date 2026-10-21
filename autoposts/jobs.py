"""Persistent media outbox with atomic claims, fenced leases and bounded retries."""
import json
import secrets
from datetime import datetime,timedelta,timezone
from pathlib import Path
from . import core,storage

LEASE_SECONDS=900

def enqueue(post_id,db=None,reset=False):
    if db is None:
        with core.connect() as connection:return enqueue(post_id,connection,reset)
    post=db.execute('SELECT id,user_id FROM posts WHERE id=?',(post_id,)).fetchone()
    if not post:return
    stamp=core.now()
    db.execute("INSERT OR IGNORE INTO media_jobs(id,post_id,user_id,created_at,updated_at) VALUES(?,?,?,?,?)",(core.uid(),post_id,post['user_id'],stamp,stamp))
    if reset:
        db.execute("UPDATE media_jobs SET status='pending',attempts=0,lease_token=NULL,lease_until=NULL,next_attempt_at=NULL,local_filename=NULL,last_error=NULL,result_key=NULL,updated_at=? WHERE post_id=? AND status!='processing'",(stamp,post_id))

def claim(post_id=None):
    stamp=core.now()
    with core.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        stale=db.execute("SELECT post_id FROM media_jobs WHERE status='processing' AND lease_until<=? AND attempts>=max_attempts",(stamp,)).fetchall()
        for row in stale:
            db.execute("UPDATE posts SET status='failed',last_error='Tentativas esgotadas após tarefa interrompida.',updated_at=? WHERE id=? AND status='rendering'",(stamp,row['post_id']))
        db.execute("UPDATE media_jobs SET status='failed',last_error='Tentativas esgotadas após tarefa interrompida.',updated_at=? WHERE status='processing' AND lease_until<=? AND attempts>=max_attempts",(stamp,stamp))
        sql="""SELECT j.* FROM media_jobs j JOIN posts p ON p.id=j.post_id JOIN users u ON u.id=j.user_id
          WHERE p.status='rendering' AND u.deletion_requested=0 AND j.attempts<j.max_attempts AND
          ((j.status='pending' AND (j.next_attempt_at IS NULL OR j.next_attempt_at<=?)) OR (j.status='processing' AND j.lease_until<=?))"""
        params=[stamp,stamp]
        if post_id:sql+=' AND j.post_id=?';params.append(post_id)
        row=db.execute(sql+' ORDER BY j.created_at LIMIT 1',params).fetchone()
        if not row:return None
        token=secrets.token_urlsafe(32);until=(datetime.now(timezone.utc)+timedelta(seconds=LEASE_SECONDS)).isoformat()
        db.execute("UPDATE media_jobs SET status='processing',attempts=attempts+1,lease_token=?,lease_until=?,updated_at=? WHERE id=?",(token,until,stamp,row['id']))
        return dict(db.execute('SELECT * FROM media_jobs WHERE id=?',(row['id'],)).fetchone())

def complete(job,filename,result=None):
    stamp=core.now();result=result or {}
    with core.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        updated=db.execute("UPDATE media_jobs SET status='completed',result_key=?,last_error=NULL,lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=? AND status='processing' AND lease_token=? AND lease_until>?",(result.get('key'),stamp,job['id'],job['lease_token'],stamp))
        if not updated.rowcount:return False
        db.execute("UPDATE posts SET status='ready',render_count=MAX(render_count,1),output_path=?,storage_key=?,storage_version=?,storage_size=?,storage_sha256=?,last_error=NULL,media_deleted_at=NULL,updated_at=? WHERE id=? AND status='rendering'",(filename,result.get('key'),result.get('version_id'),result.get('size'),result.get('sha256'),stamp,job['post_id']))
    return True

def fail(job,error,retryable=False):
    retry=retryable and job['attempts']<job['max_attempts']
    next_time=(datetime.now(timezone.utc)+timedelta(seconds=30*2**(job['attempts']-1))).isoformat() if retry else None
    with core.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        updated=db.execute("UPDATE media_jobs SET status=?,last_error=?,next_attempt_at=?,lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=? AND status='processing' AND lease_token=?",('pending' if retry else 'failed',str(error)[:500],next_time,core.now(),job['id'],job['lease_token']))
        if updated.rowcount:
            db.execute("UPDATE posts SET status=?,last_error=?,updated_at=? WHERE id=? AND status='rendering'",('rendering' if retry else 'failed',str(error)[:500],core.now(),job['post_id']))

def execute_job(job,render_function=None):
    from . import media
    post=core.one('SELECT * FROM posts WHERE id=? AND user_id=?',(job['post_id'],job['user_id']))
    if not post:return
    kind=post.get('kind','video')
    directory='images' if kind=='image' else 'videos'
    try:
        cached=job.get('local_filename')
        if cached and Path(cached).name==cached and (core.settings.data_dir/directory/cached).is_file():filename=cached
        else:
            renderer=render_function or (media.render_image if kind=='image' else media.render_post)
            filename=renderer(post)
            core.execute("UPDATE media_jobs SET local_filename=? WHERE id=? AND lease_token=?",(filename,job['id'],job['lease_token']))
        result=None
        if storage.backend()=='b2':
            result=storage.B2Store().put_file(storage.object_key(post['user_id'],post['id']+'-'+post['public_token'][:12],kind),core.settings.data_dir/directory/filename,'image/jpeg' if kind=='image' else 'video/mp4')
        return complete(job,filename,result)
    except storage.StorageError as exc:fail(job,str(exc),exc.retryable)
    except media.RenderError as exc:fail(job,str(exc))
    except Exception:fail(job,'Falha ao gerar ou armazenar o arquivo. O resultado não foi marcado como concluído.')

def public_job(row):
    return {k:row[k] for k in ['id','post_id','status','attempts','max_attempts','last_error','next_attempt_at','created_at','updated_at']}
