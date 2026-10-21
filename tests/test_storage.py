import hashlib
import io
from unittest.mock import Mock
import pytest
from botocore.exceptions import ClientError
from autoposts.storage import B2Config,B2Store,StorageError,create_client,object_key

@pytest.fixture
def b2_env(monkeypatch):
    for k,v in {'B2_ENDPOINT':'s3.us-east-005.backblazeb2.com','B2_BUCKET_NAME':'autoposts-media-fernando','B2_KEY_ID':'test-key-id','B2_APPLICATION_KEY':'test-only-application-key'}.items():monkeypatch.setenv(k,v)
    monkeypatch.delenv('B2_REGION',raising=False)
    # Tests use explicit dummy B2 credentials and never resolve an AWS identity.
    monkeypatch.delenv('AWS_PROFILE',raising=False)
    monkeypatch.delenv('AWS_DEFAULT_PROFILE',raising=False)
    return B2Config.from_env()

def test_endpoint_region_and_config_are_explicit(b2_env):
    assert b2_env.region=='us-east-005'
    assert b2_env.endpoint=='https://s3.us-east-005.backblazeb2.com'
    client=create_client(b2_env)
    assert client.meta.config.signature_version=='s3v4'
    assert client.meta.config.s3['addressing_style']=='path'
    assert client.meta.config.request_checksum_calculation=='when_required'
    assert client.meta.config.response_checksum_validation=='when_required'
    assert client._endpoint.http_session._verify is True
    client.close()

@pytest.mark.parametrize('endpoint',['http://s3.us-east-005.backblazeb2.com','https://example.com','https://s3.us-east-005.backblazeb2.com/bucket','https://user:pass@s3.us-east-005.backblazeb2.com'])
def test_rejects_unsafe_endpoint(b2_env,monkeypatch,endpoint):
    monkeypatch.setenv('B2_ENDPOINT',endpoint)
    with pytest.raises(StorageError):B2Config.from_env()

def test_checks_region_and_malformed_secrets_without_echo(b2_env,monkeypatch):
    monkeypatch.setenv('B2_REGION','us-west-004')
    with pytest.raises(StorageError):B2Config.from_env()
    monkeypatch.delenv('B2_REGION')
    monkeypatch.setenv('B2_KEY_ID','"a-secret-value"')
    with pytest.raises(StorageError) as e:B2Config.from_env()
    assert 'a-secret-value' not in str(e.value)

def test_verified_upload_and_private_urls(b2_env):
    client=Mock();data=b'hello'
    client.head_object.return_value={'ContentLength':5,'Metadata':{'sha256':hashlib.sha256(data).hexdigest()}}
    store=B2Store(b2_env,client);store.put_bytes('users/one/images/id.jpg',data,'image/jpeg')
    call=client.put_object.call_args.kwargs
    assert call['ContentLength']==5 and 'ContentMD5' in call and 'ACL' not in call
    client.head_object.assert_called_once()
    client.generate_presigned_url.return_value='https://signed.example/path'
    assert store.url('users/one/images/id.jpg',5000)=='https://signed.example/path'
    assert client.generate_presigned_url.call_args.kwargs['ExpiresIn']==3600

def test_failed_verification_is_not_success(b2_env):
    client=Mock();client.head_object.return_value={'ContentLength':0,'Metadata':{}}
    with pytest.raises(StorageError) as e:B2Store(b2_env,client).put_bytes('key',b'hello','text/plain')
    assert e.value.retryable and e.value.code=='verification'

def test_provider_error_is_sanitized(b2_env):
    client=Mock();client.put_object.side_effect=ClientError({'Error':{'Code':'InvalidAccessKeyId','Message':'secret-value-do-not-log'}},'PutObject')
    with pytest.raises(StorageError) as e:B2Store(b2_env,client).put_bytes('key',b'hello','text/plain')
    assert e.value.code=='InvalidAccessKeyId' and 'secret-value' not in str(e.value)

def test_tenant_key_and_no_path_traversal():
    assert object_key('user123','video123','video')=='users/user123/videos/video123.mp4'
    with pytest.raises(StorageError):object_key('../admin','video123','video')

def test_roundtrip_probe_cleans_up_on_read_failure(monkeypatch,b2_env):
    from scripts import test_b2
    client=Mock();store=Mock();store.get_bytes.return_value=b'wrong'
    monkeypatch.setattr(test_b2,'B2Store',lambda:store)
    assert test_b2.main()==1
    store.delete.assert_called_once()
