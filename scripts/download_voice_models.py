"""Pinned official Kokoro ONNX weights, verified by SHA-256; no model execution."""
import hashlib
import json
import os
from pathlib import Path
import urllib.request


def digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):result.update(chunk)
    return result.hexdigest()


def download(directory=None):
    directory=Path(directory or os.environ.get('KOKORO_MODEL_DIR','.models/kokoro'))
    directory.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((Path(__file__).resolve().parent.parent/'ai_worker'/'kokoro-models.json').read_text())
    for name,entry in manifest.items():
        destination=directory/name
        if destination.is_file() and digest(destination)==entry['sha256']:continue
        temporary=directory/(name+'.download')
        try:
            total=0
            with urllib.request.urlopen(entry['url'],timeout=45) as response,temporary.open('wb') as target:
                while chunk:=response.read(1024*1024):
                    total+=len(chunk)
                    if total>entry['size']:raise RuntimeError('Arquivo excedeu o tamanho esperado.')
                    target.write(chunk)
            if total!=entry['size'] or digest(temporary)!=entry['sha256']:raise RuntimeError('Checksum do modelo divergente; arquivo não será utilizado.')
            temporary.replace(destination)
        finally:temporary.unlink(missing_ok=True)
    return directory

if __name__=='__main__':
    download();print('Modelos Kokoro de origem oficial confirmados por SHA-256.')
