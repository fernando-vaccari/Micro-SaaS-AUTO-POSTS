"""Additive, idempotent SQLite migrations; never reset existing tenant data."""
import json
from datetime import datetime, timezone

def add_columns(db,table,columns):
    present={r[1] for r in db.execute(f'PRAGMA table_info({table})')}
    for name,definition in columns.items():
        if name not in present:db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')

def init_extensions(db):
    add_columns(db,'users',{'email_verified':'INTEGER NOT NULL DEFAULT 0','last_active_at':'TEXT','subscription_status':"TEXT NOT NULL DEFAULT 'inactive'",'subscription_until':'TEXT','deletion_requested':'INTEGER NOT NULL DEFAULT 0','billing_provider':"TEXT NOT NULL DEFAULT 'stripe'",'mp_preapproval_id':'TEXT','mp_status':'TEXT'})
    db.execute('UPDATE users SET last_active_at=created_at WHERE last_active_at IS NULL')
    add_columns(db,'posts',{'kind':"TEXT NOT NULL DEFAULT 'video'",'creative_config':"TEXT NOT NULL DEFAULT '{}'",'generated_at':'TEXT','media_expires_at':'TEXT','render_count':'INTEGER NOT NULL DEFAULT 0','storage_provider':"TEXT NOT NULL DEFAULT 'b2'",'storage_key':'TEXT','storage_version':'TEXT','storage_size':'INTEGER','storage_sha256':'TEXT','media_deleted_at':'TEXT','brand_config':"TEXT NOT NULL DEFAULT '{}'"})
    db.execute("UPDATE posts SET generated_at=updated_at WHERE output_path IS NOT NULL AND generated_at IS NULL")
    db.execute('UPDATE posts SET render_count=1 WHERE render_count=0 AND output_path IS NOT NULL')
    add_columns(db,'assets',{'storage_provider':"TEXT NOT NULL DEFAULT 'b2'",'storage_key':'TEXT','storage_version':'TEXT','deleted_at':'TEXT'})
    db.executescript('''
    CREATE TABLE IF NOT EXISTS voice_profiles(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,name TEXT NOT NULL,filename TEXT NOT NULL,duration REAL NOT NULL,size INTEGER NOT NULL,storage_key TEXT,storage_version TEXT,consented_at TEXT NOT NULL,revoked_at TEXT,created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS voices_owner ON voice_profiles(user_id,revoked_at);
    CREATE TABLE IF NOT EXISTS mp_events(id TEXT PRIMARY KEY,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS mp_payments(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,status TEXT NOT NULL,period_end TEXT NOT NULL,amount INTEGER NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS mp_checkouts(user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,nonce TEXT NOT NULL,preapproval_id TEXT,checkout_url TEXT,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS storage_deletions(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,object_key TEXT NOT NULL UNIQUE,version_id TEXT,status TEXT NOT NULL DEFAULT 'pending',reason TEXT NOT NULL,last_error TEXT,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS schema_versions(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS media_jobs(
      id TEXT PRIMARY KEY, post_id TEXT NOT NULL UNIQUE REFERENCES posts(id) ON DELETE CASCADE,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, status TEXT NOT NULL DEFAULT 'pending',
      attempts INTEGER NOT NULL DEFAULT 0,max_attempts INTEGER NOT NULL DEFAULT 3,lease_token TEXT,lease_until TEXT,
      next_attempt_at TEXT,local_filename TEXT,result_key TEXT,last_error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS media_jobs_due ON media_jobs(status,next_attempt_at,lease_until);
    CREATE INDEX IF NOT EXISTS media_jobs_owner ON media_jobs(user_id,created_at);
    CREATE TABLE IF NOT EXISTS image_usage(user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,month TEXT NOT NULL,count INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(user_id,month));
    CREATE TABLE IF NOT EXISTS recovery_tokens(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,purpose TEXT NOT NULL,expires_at TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS recovery_expiry ON recovery_tokens(expires_at);
    CREATE TABLE IF NOT EXISTS audit_events(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT,event TEXT NOT NULL,object_id TEXT,detail TEXT,created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS audit_owner ON audit_events(user_id,created_at);
    CREATE TABLE IF NOT EXISTS billing_history(id TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id) ON DELETE SET NULL,event_type TEXT NOT NULL,plan TEXT,status TEXT,amount INTEGER,currency TEXT,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS billing_checkouts(user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,plan TEXT NOT NULL,nonce TEXT NOT NULL,checkout_id TEXT,checkout_url TEXT,expires_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS trial_identities(email_hash TEXT PRIMARY KEY,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS studio_requests(
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      request_key TEXT NOT NULL,request_hash TEXT NOT NULL,
      post_id TEXT REFERENCES posts(id) ON DELETE SET NULL,campaign_id TEXT,created_at TEXT NOT NULL,
      PRIMARY KEY(user_id,request_key));
    CREATE TABLE IF NOT EXISTS persistent_rate_limits(key TEXT PRIMARY KEY,count INTEGER NOT NULL,expires_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS deletion_requests(user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,created_at TEXT NOT NULL,last_error TEXT);
    ''')
    add_columns(db,'voice_profiles',{'storage_provider':"TEXT NOT NULL DEFAULT 'b2'"})
    add_columns(db,'storage_deletions',{'storage_provider':"TEXT NOT NULL DEFAULT 'b2'"})
    # Preserve every legacy cleanup request while allowing the same key in two providers.
    unique_keys=[]
    for index in db.execute('PRAGMA index_list(storage_deletions)').fetchall():
        if index['unique']:
            unique_keys.append([r['name'] for r in db.execute('PRAGMA index_info("'+index['name']+'")').fetchall()])
    if ['object_key'] in unique_keys:
        db.execute('ALTER TABLE storage_deletions RENAME TO storage_deletions_legacy')
        db.execute("CREATE TABLE storage_deletions(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,object_key TEXT NOT NULL,version_id TEXT,status TEXT NOT NULL DEFAULT 'pending',reason TEXT NOT NULL,last_error TEXT,created_at TEXT NOT NULL,storage_provider TEXT NOT NULL DEFAULT 'b2',UNIQUE(storage_provider,object_key))")
        db.execute('INSERT INTO storage_deletions SELECT id,user_id,object_key,version_id,status,reason,last_error,created_at,storage_provider FROM storage_deletions_legacy')
        db.execute('DROP TABLE storage_deletions_legacy')
    stamp=datetime.now(timezone.utc).isoformat()
    if not db.execute("SELECT 1 FROM schema_versions WHERE version='saas-2'").fetchone():
        db.execute("UPDATE users SET subscription_status='active' WHERE plan='pro' AND stripe_subscription_id IS NOT NULL")
        db.execute("INSERT INTO schema_versions VALUES('saas-2',?)",(stamp,))

def campaign_extensions(db):
    add_columns(db,'campaigns',{'creative_config':"TEXT NOT NULL DEFAULT '{}'",'kind':"TEXT NOT NULL DEFAULT 'video'",'duration':'INTEGER NOT NULL DEFAULT 45','weekdays':"TEXT NOT NULL DEFAULT '[0,1,2,3,4,5,6]'",'brand_config':"TEXT NOT NULL DEFAULT '{}'",'company_name':"TEXT NOT NULL DEFAULT ''",'objective':"TEXT NOT NULL DEFAULT ''"})
