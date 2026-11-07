"""Small real private R2 roundtrip, with no credential values in output."""
import json
import os
import sys
from uuid import uuid4
from autoposts.storage import R2Store,StorageError


def main():
    facts={name:{'defined':bool(os.environ.get(name,'')),'has_whitespace':any(c.isspace() for c in os.environ.get(name,''))} for name in ('R2_ACCESS_KEY_ID','R2_SECRET_ACCESS_KEY','R2_BUCKET_NAME')}
    print('R2_ENV_DIAGNOSTICS '+json.dumps(facts),flush=True)
    key='diagnostics/autoposts-'+uuid4().hex+'.txt';attempted=False;store=None;error=None
    try:
        store=R2Store();attempted=True
        data=b'Auto Posts private Cloudflare R2 verification\n'
        store.put_bytes(key,data,'text/plain')
        if store.get_bytes(key)!=data:raise StorageError('Conteúdo lido difere do enviado.',code='verification')
    except StorageError as exc:error=str(exc)
    except Exception:error='Falha inesperada. Detalhes privados foram omitidos.'
    finally:
        if attempted:
            try:store.delete(key)
            except Exception:error=error or 'A exclusão do objeto de diagnóstico não foi confirmada.'
    if error:
        print('::error title=R2 roundtrip::'+error.replace('%','%25').replace('\n','%0A').replace('\r','%0D'),flush=True)
        return 1
    print('R2_ROUNDTRIP_OK: upload, leitura, conteúdo e exclusão confirmados.',flush=True)
    return 0
if __name__=='__main__':sys.exit(main())
