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

def test_delete_purges_versions_of_exact_key_only(b2_env):
    client=Mock();key='users/one/images/a.jpg'
    client.list_object_versions.return_value={'Versions':[{'Key':key,'VersionId':'v1'},{'Key':key,'VersionId':'v2'},{'Key':key+'-other','VersionId':'keep'}],'DeleteMarkers':[{'Key':key,'VersionId':'marker'}]}
    client.head_object.side_effect=ClientError({'Error':{'Code':'404'}},'HeadObject')
    B2Store(b2_env,client).delete(key,'v2')
    assert [c.kwargs['VersionId'] for c in client.delete_object.call_args_list]==['v1','v2','marker']

def test_file_upload_records_verified_version(b2_env,tmp_path):
    path=tmp_path/'media';path.write_bytes(b'real bytes')
    client=Mock();client.put_object.return_value={'VersionId':'version1'}
    client.head_object.return_value={'ContentLength':10,'Metadata':{'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}}
    result=B2Store(b2_env,client).put_file('key',path,'image/jpeg')
    assert result['version_id']=='version1' and result['size']==10

@pytest.mark.parametrize('name',['B2_KEY_ID','B2_APPLICATION_KEY'])
@pytest.mark.parametrize('suffix',[' ','\n','\r\n','\t','\u200b','\ufeff'])
def test_secret_format_is_checked_before_any_trimming(b2_env,monkeypatch,name,suffix):
    monkeypatch.setenv(name,'005-private-test-marker'+suffix)
    from autoposts.storage import safe_environment_diagnostics
    info=safe_environment_diagnostics()[name]
    assert info['defined']
    assert info['has_whitespace'] or info['has_control_or_invisible_characters']
    with pytest.raises(StorageError) as error:B2Config.from_env()
    assert error.value.code=='configuration' and 'private-test-marker' not in str(error.value)

def test_diagnostics_are_allowlisted_and_never_contain_key_fragments():
    import json
    from autoposts.storage import safe_environment_diagnostics
    env={'B2_KEY_ID':'005UNIQUE-private-keyid-identifier','B2_APPLICATION_KEY':'SECRETUNIQUE-application-private-value','B2_ENDPOINT':'https://url-user:private-url-password@s3.us-east-005.backblazeb2.com','B2_BUCKET_NAME':'autoposts-media-fernando'}
    data=safe_environment_diagnostics(env)
    serialized=json.dumps(data)
    for secret in (*env.values(), '005UNIQUE','SECRETUNIQUE','private-url-password'):
        if secret!='autoposts-media-fernando':assert secret not in serialized
    assert data['B2_KEY_ID']['character_count']==len(env['B2_KEY_ID'])
    assert data['B2_KEY_ID']['defined'] and data['B2_APPLICATION_KEY']['defined']
    assert not data['endpoint']['valid']
    assert set(data['B2_KEY_ID'])=={'defined','character_count','has_whitespace','has_line_breaks','has_surrounding_whitespace','has_non_ascii','has_control_or_invisible_characters','has_surrounding_quotes','has_variable_label'}

def test_diagnostics_report_missing_secrets_and_expected_endpoint():
    from autoposts.storage import safe_environment_diagnostics
    data=safe_environment_diagnostics({'B2_ENDPOINT':'s3.us-east-005.backblazeb2.com','B2_REGION':'us-east-005'})
    assert data['B2_KEY_ID']['defined'] is False and data['B2_KEY_ID']['character_count']==0
    assert data['B2_APPLICATION_KEY']['defined'] is False
    assert data['endpoint']['valid'] and data['endpoint']['matches_expected'] and data['endpoint']['region_matches_endpoint']

def test_diagnostics_report_wrong_endpoint_region_and_bucket():
    from autoposts.storage import safe_environment_diagnostics
    data=safe_environment_diagnostics({'B2_ENDPOINT':'s3.us-west-004.backblazeb2.com','B2_REGION':'us-east-005','B2_BUCKET_NAME':'other-bucket'})
    assert data['endpoint']['valid'] and not data['endpoint']['matches_expected']
    assert not data['endpoint']['region_matches_endpoint'] and not data['bucket']['matches_expected']

def test_explicit_b2_credentials_override_aws_environment_and_default_session(b2_env,monkeypatch):
    import boto3
    monkeypatch.setenv('AWS_ACCESS_KEY_ID','unrelated-aws-id')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY','unrelated-aws-secret')
    monkeypatch.setenv('AWS_SESSION_TOKEN','unrelated-aws-token')
    monkeypatch.setenv('AWS_DEFAULT_REGION','eu-west-1')
    monkeypatch.setenv('AWS_ENDPOINT_URL_S3','https://wrong-endpoint.invalid')
    monkeypatch.setattr(boto3,'DEFAULT_SESSION',boto3.Session(aws_access_key_id='cached-aws-id',aws_secret_access_key='cached-aws-secret',aws_session_token='cached-aws-token'))
    client=create_client(b2_env)
    try:
        credentials=client._request_signer._credentials.get_frozen_credentials()
        assert credentials.access_key==b2_env.key_id
        assert credentials.secret_key==b2_env.application_key
        assert credentials.token is None
        assert client.meta.endpoint_url==b2_env.endpoint
        assert client.meta.region_name==b2_env.region
        from urllib.parse import parse_qs,urlsplit
        signed=parse_qs(urlsplit(client.generate_presigned_url('get_object',Params={'Bucket':b2_env.bucket,'Key':'diagnostics/test.txt'})).query)
        assert signed['X-Amz-Credential'][0].split('/')[0]==b2_env.key_id
        assert signed['X-Amz-Credential'][0].split('/')[2:4]==['us-east-005','s3']
        assert 'X-Amz-Security-Token' not in signed
    finally:client.close()

def test_probe_logs_diagnostics_before_failure_without_leaking_values(b2_env,monkeypatch,capsys):
    from scripts import test_b2
    store=Mock();store.put_bytes.side_effect=StorageError('O endpoint recusou autenticação.',code='InvalidAccessKeyId')
    store.delete.side_effect=ValueError('private-cleanup-details')
    monkeypatch.setattr(test_b2,'B2Store',lambda:store)
    assert test_b2.main()==1
    out=capsys.readouterr().out
    assert out.startswith('B2_ENV_DIAGNOSTICS ')
    assert 'InvalidAccessKeyId' in out and '"cleanup_status": "failed"' in out
    for value in (b2_env.key_id,b2_env.application_key,'private-cleanup-details'):assert value not in out
    assert 'B2_ROUNDTRIP_OK' not in out

def test_probe_success_requires_content_and_confirmed_cleanup(b2_env,monkeypatch,capsys):
    from scripts import test_b2
    store=Mock();store.put_bytes.return_value={'version_id':'test-version'}
    store.get_bytes.return_value=b'Auto Posts B2 round-trip verification\n'
    monkeypatch.setattr(test_b2,'B2Store',lambda:store)
    assert test_b2.main()==0
    assert 'B2_ROUNDTRIP_OK' in capsys.readouterr().out
    store.delete.assert_called_once()
    assert store.delete.call_args.args[1]=='test-version'

def test_probe_fails_when_cleanup_is_not_confirmed(b2_env,monkeypatch,capsys):
    from scripts import test_b2
    store=Mock();store.get_bytes.return_value=b'Auto Posts B2 round-trip verification\n'
    store.delete.side_effect=StorageError('Limpeza não confirmada.',code='verification')
    monkeypatch.setattr(test_b2,'B2Store',lambda:store)
    assert test_b2.main()==1
    out=capsys.readouterr().out
    assert '"stage": "delete"' in out and 'B2_ROUNDTRIP_OK' not in out

@pytest.mark.parametrize('endpoint',['https://s3.us-east-005.backblazeb2.com:invalid','https://[invalid'])
def test_malformed_endpoint_errors_do_not_echo_input(b2_env,monkeypatch,endpoint):
    monkeypatch.setenv('B2_ENDPOINT',endpoint)
    with pytest.raises(StorageError) as error:B2Config.from_env()
    assert endpoint not in str(error.value)
