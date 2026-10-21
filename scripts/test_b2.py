"""Real, bounded B2 probe. Requires GitHub secrets or securely injected environment."""
import json
import sys
from uuid import uuid4
import boto3,botocore,urllib3
from autoposts.storage import B2Store,StorageError

def main():
    print(json.dumps({'boto3':boto3.__version__,'botocore':botocore.__version__,'urllib3':urllib3.__version__}),flush=True)
    key='diagnostics/autoposts-'+uuid4().hex+'.txt'
    payload=b'Auto Posts B2 round-trip verification\n'
    stage='configuration'; attempted=False; failed=None; result={}
    try:
        store=B2Store()
        stage='upload'; attempted=True
        result=store.put_bytes(key,payload,'text/plain')
        print('Upload confirmado por HEAD.',flush=True)
        stage='read'
        if store.get_bytes(key)!=payload:raise StorageError('Conteúdo lido difere do enviado.',code='verification')
        print('Leitura e conteúdo confirmados.',flush=True)
    except StorageError as exc:failed={'status':'failed','stage':stage,'code':exc.code,'message':str(exc)}
    except Exception as exc:
        failed={'status':'failed','stage':stage,'code':type(exc).__name__,'message':'Falha inesperada no teste; nenhum detalhe de credencial foi registrado.'}
    finally:
        if attempted:
            try:store.delete(key,result.get('version_id'));print('Objeto de diagnóstico excluído.',flush=True)
            except StorageError as exc:
                failed=failed or {'status':'failed','stage':'delete','code':exc.code,'message':str(exc)}
    if failed:
        print(json.dumps(failed,ensure_ascii=False),flush=True)
        safe=(failed['message'].replace('%','%25').replace('\r','%0D').replace('\n','%0A'))
        print(f"::error title=B2 {failed['stage']} / {failed['code']}::{safe}",flush=True)
        return 1
    print('B2_ROUNDTRIP_OK: upload, leitura, conteúdo e exclusão confirmados.',flush=True)
    return 0

if __name__=='__main__':sys.exit(main())
