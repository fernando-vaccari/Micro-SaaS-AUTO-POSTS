"""Private Backblaze B2 storage using its S3-compatible API.

No credential discovery, public ACLs, disabled TLS, or provider response bodies in logs.
"""
from __future__ import annotations
import base64
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from botocore.handlers import add_expect_header

class StorageError(Exception):
    def __init__(self, message: str, *, code='storage_error', retryable=False):
        super().__init__(message)
        self.code, self.retryable = code, retryable

@dataclass(frozen=True, repr=False)
class B2Config:
    endpoint: str
    region: str
    bucket: str
    key_id: str
    application_key: str

    @classmethod
    def from_env(cls):
        def variable(name):
            return os.environ.get(name, '').strip().strip('"\'').strip()
        endpoint = variable('B2_ENDPOINT')
        bucket = variable('B2_BUCKET_NAME')
        key_id = os.environ.get('B2_KEY_ID', '').strip()
        key = os.environ.get('B2_APPLICATION_KEY', '').strip()
        if not all((endpoint, bucket, key_id, key)):
            raise StorageError('Configure B2_ENDPOINT, B2_BUCKET_NAME, B2_KEY_ID e B2_APPLICATION_KEY.', code='configuration')
        for name, value in [('B2_KEY_ID', key_id), ('B2_APPLICATION_KEY', key)]:
            if any(c.isspace() for c in value) or value[0] in '\"\'' or value[-1] in '\"\'' or value.startswith(name+'='):
                raise StorageError(f'{name} deve conter somente o valor da Application Key, sem aspas, rótulo ou quebra de linha.', code='configuration')
        if not endpoint.startswith('https://'):
            endpoint = 'https://' + endpoint
        parsed = urlsplit(endpoint)
        match = re.fullmatch(r's3\.([a-z0-9-]+)\.backblazeb2\.com', parsed.hostname or '')
        if not match or parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            raise StorageError('B2_ENDPOINT deve ser o endpoint HTTPS S3 do B2, sem bucket, caminho ou credenciais.', code='configuration')
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]{4,61}[a-zA-Z0-9]', bucket):
            raise StorageError('B2_BUCKET_NAME inválido; use somente o nome do bucket, sem URL.', code='configuration')
        region = match[1]
        if os.environ.get('B2_REGION', region).strip() != region:
            raise StorageError('B2_REGION deve corresponder à região no B2_ENDPOINT.', code='configuration')
        return cls(f'https://{parsed.hostname}', region, bucket, key_id, key)

def configured():
    return all(os.environ.get(n, '').strip() for n in ('B2_ENDPOINT','B2_BUCKET_NAME','B2_KEY_ID','B2_APPLICATION_KEY'))

def _failure(exc):
    if isinstance(exc, ClientError):
        code = str(exc.response.get('Error', {}).get('Code', 'provider_error'))
        # Do not propagate message, request URL, authorization headers or key IDs.
        if code in {'InvalidAccessKeyId', 'MalformedAccessKeyId'}:
            return StorageError('B2 rejeitou o Key ID. Verifique se B2_KEY_ID é o keyID da nova Application Key S3, e não o Account ID ou o nome da chave.', code=code)
        if code in {'SignatureDoesNotMatch', 'InvalidToken'}:
            return StorageError('A assinatura foi recusada. Verifique o par keyID/applicationKey e a região do bucket.', code=code)
        if code in {'AccessDenied', 'Unauthorized'}:
            return StorageError('A chave não permite esta operação. Verifique bucket, prefixo e permissões readFiles, writeFiles e deleteFiles.', code=code)
        if code in {'NoSuchBucket','NotFound','404'}:
            return StorageError('Bucket ou objeto não encontrado no B2. Verifique bucket e região.', code=code)
        retry = code in {'RequestTimeout','SlowDown','InternalError','ServiceUnavailable','503','500'}
        return StorageError('O B2 não concluiu a operação. Consulte o código seguro e tente novamente se a falha for temporária.', code=code, retryable=retry)
    return StorageError('Falha de conexão, protocolo ou TLS com o B2. Verifique endpoint, proxy e CA confiável; a verificação TLS permanece ativa.', code=type(exc).__name__, retryable=True)

def create_client(cfg: B2Config):
    client = boto3.client('s3', endpoint_url=cfg.endpoint, region_name=cfg.region,
        aws_access_key_id=cfg.key_id, aws_secret_access_key=cfg.application_key,
        config=Config(signature_version='s3v4', s3={'addressing_style':'path'},
            request_checksum_calculation='when_required', response_checksum_validation='when_required',
            connect_timeout=10, read_timeout=30, retries={'mode':'standard','total_max_attempts':3}),
        verify=True)
    # Botocore installs this on before-call.s3. Removing it prevents the optional
    # 100-continue handshake; explicit ContentLength avoids aws-chunked payloads.
    client.meta.events.unregister('before-call.s3', add_expect_header)
    return client

def object_key(user_id: str, media_id: str, kind: str):
    if not all(re.fullmatch(r'[A-Za-z0-9_-]{1,80}', v) for v in [user_id, media_id]) or kind not in {'video','image'}:
        raise StorageError('Identificador de mídia inválido.', code='configuration')
    return f"users/{user_id}/{'videos' if kind=='video' else 'images'}/{media_id}.{'mp4' if kind=='video' else 'jpg'}"

class B2Store:
    def __init__(self, config=None, client=None):
        self.config = config or B2Config.from_env()
        self.client = client or create_client(self.config)

    def put_bytes(self, key, data: bytes, content_type):
        digest = hashlib.sha256(data).hexdigest()
        try:
            self.client.put_object(Bucket=self.config.bucket, Key=key, Body=data,
                ContentLength=len(data), ContentType=content_type,
                ContentMD5=base64.b64encode(hashlib.md5(data).digest()).decode(), Metadata={'sha256':digest})
            self._confirm(key,len(data),digest)
        except (BotoCoreError, ClientError) as exc: raise _failure(exc) from None
        return {'key':key,'size':len(data),'sha256':digest}

    def put_file(self, key, path: Path, content_type):
        digest=hashlib.sha256(); md5=hashlib.md5()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024*1024),b''): digest.update(chunk); md5.update(chunk)
        size=path.stat().st_size
        try:
            with path.open('rb') as stream:
                self.client.put_object(Bucket=self.config.bucket, Key=key, Body=stream, ContentLength=size,
                    ContentType=content_type,ContentMD5=base64.b64encode(md5.digest()).decode(),Metadata={'sha256':digest.hexdigest()})
            self._confirm(key,size,digest.hexdigest())
        except (BotoCoreError,ClientError) as exc: raise _failure(exc) from None
        return {'key':key,'size':size,'sha256':digest.hexdigest()}

    def _confirm(self,key,size,digest):
        result=self.client.head_object(Bucket=self.config.bucket,Key=key)
        if result['ContentLength']!=size or result.get('Metadata',{}).get('sha256')!=digest:
            raise StorageError('O upload não foi confirmado pelo B2.',code='verification',retryable=True)

    def get_bytes(self,key, maximum=1024*1024):
        try:
            result=self.client.get_object(Bucket=self.config.bucket,Key=key)
            with result['Body'] as body:
                data=body.read(maximum+1)
            if len(data)>maximum: raise StorageError('Arquivo excede o limite.',code='size')
            return data
        except (BotoCoreError,ClientError) as exc: raise _failure(exc) from None

    def delete(self,key):
        try:self.client.delete_object(Bucket=self.config.bucket,Key=key)
        except (BotoCoreError,ClientError) as exc:raise _failure(exc) from None

    def url(self,key,seconds=900):
        try:return self.client.generate_presigned_url('get_object',Params={'Bucket':self.config.bucket,'Key':key},ExpiresIn=max(60,min(int(seconds),3600)))
        except (BotoCoreError,ClientError) as exc:raise _failure(exc) from None
