"""Cloudflare R2 S3 configuration and provider-aware private storage contracts."""
import hashlib
from unittest.mock import Mock
from botocore.exceptions import ClientError
import pytest
from autoposts import storage,core,maintenance

@pytest.fixture
def r2_env(monkeypatch):
    for name in ('AWS_PROFILE','AWS_DEFAULT_PROFILE'):monkeypatch.delenv(name,raising=False)
    for key,value in {'R2_ACCOUNT_ID':'a'*32,'R2_BUCKET_NAME':'autoposts-media','R2_ACCESS_KEY_ID':'test-only-r2-access-key','R2_SECRET_ACCESS_KEY':'test-only-r2-secret','STORAGE_BACKEND':'r2'}.items():monkeypatch.setenv(key,value)
    monkeypatch.delenv('R2_ENDPOINT',raising=False)
    return storage.R2Config.from_env()


def test_r2_sigv4_auto_region_private_endpoint(r2_env):
    assert r2_env.region=='auto' and r2_env.endpoint=='https://'+'a'*32+'.r2.cloudflarestorage.com'
    client=storage.create_client(r2_env)
    try:
        assert client.meta.config.signature_version=='s3v4'
        assert client.meta.config.s3['addressing_style']=='path'
        assert client._endpoint.http_session._verify is True
    finally:client.close()

@pytest.mark.parametrize('endpoint',['http://'+'a'*32+'.r2.cloudflarestorage.com','https://example.com','https://'+'b'*32+'.r2.cloudflarestorage.com','https://'+'a'*32+'.r2.cloudflarestorage.com/bucket'])
def test_r2_rejects_wrong_or_unsafe_endpoint(r2_env,monkeypatch,endpoint):
    monkeypatch.setenv('R2_ENDPOINT',endpoint)
    with pytest.raises(storage.StorageError):storage.R2Config.from_env()


def test_r2_upload_is_verified_and_provider_recorded(r2_env):
    client=Mock();client.put_object.return_value={};data=b'private media'
    client.head_object.return_value={'ContentLength':len(data),'Metadata':{'sha256':hashlib.sha256(data).hexdigest()}}
    result=storage.R2Store(r2_env,client).put_bytes('users/owner/images/a.jpg',data,'image/jpeg')
    assert result['provider']=='r2' and result['version_id'] is None
    assert 'ACL' not in client.put_object.call_args.kwargs


def test_r2_delete_does_not_use_unsupported_versioning(r2_env):
    client=Mock();client.head_object.side_effect=ClientError({'Error':{'Code':'404'}},'HeadObject')
    storage.R2Store(r2_env,client).delete('users/owner/videos/a.mp4')
    client.delete_object.assert_called_once();client.list_object_versions.assert_not_called()


def test_old_b2_objects_still_use_b2_after_switch_to_r2(isolated_db,r2_env,monkeypatch):
    core.execute("INSERT INTO storage_deletions(id,user_id,object_key,storage_provider,reason,created_at) VALUES('legacy','owner','legacy.mp4','b2','inactivity',?)",(core.now(),))
    b2=Mock();r2=Mock();monkeypatch.setattr(storage,'B2Store',lambda:b2);monkeypatch.setattr(storage,'R2Store',lambda:r2)
    maintenance.cleanup_remote()
    b2.delete.assert_called_once();r2.delete.assert_not_called()


def test_r2_missing_secret_is_not_reported_as_success(r2_env,monkeypatch):
    monkeypatch.delenv('R2_SECRET_ACCESS_KEY')
    with pytest.raises(storage.StorageError) as exc:storage.R2Config.from_env()
    assert exc.value.code=='configuration'


def test_cleanup_outbox_distinguishes_the_same_key_in_different_providers(isolated_db):
    with core.connect() as db:
        for provider in ('r2','b2'):
            maintenance.queue_delete(db,{'user_id':'owner','storage_key':'users/owner/images/media.jpg','storage_provider':provider},'expiry')
    assert core.one('SELECT COUNT(*) AS n FROM storage_deletions')['n']==2
    core.init_db()  # Idempotent schema upgrade preserves both requests.
    assert core.one('SELECT COUNT(*) AS n FROM storage_deletions')['n']==2
