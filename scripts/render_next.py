"""One trusted remote job: claim -> render -> verified B2 upload -> fenced result."""
import json
import os
from pathlib import Path
import tempfile
import urllib.request
from urllib.parse import urlsplit
from scripts.render_job import render_payload
from autoposts.storage import B2Store,object_key

def chamar_api(path,data=None):
    base=os.environ.get('AUTOPOSTS_API_URL','').rstrip('/')
    secret=os.environ.get('AUTOPOSTS_API_SECRET','')
    parsed=urlsplit(base)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or len(secret)<32:raise RuntimeError('Configure AUTOPOSTS_API_URL HTTPS e AUTOPOSTS_API_SECRET seguro.')
    request=urllib.request.Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers={'Authorization':'Bearer '+secret,'Accept':'application/json','Content-Type':'application/json'},method='POST' if data is not None else 'GET')
    with urllib.request.urlopen(request,timeout=30) as response:
        body=response.read(1024*1024+1)
        if len(body)>1024*1024:raise RuntimeError('Resposta excedeu o limite.')
        return json.loads(body)

def main():
    job=chamar_api('/api/jobs/claim',{}).get('job')
    if not job:print('Nenhum trabalho disponível.');return
    try:
        with tempfile.TemporaryDirectory(prefix='autoposts-job-') as directory:
            path=render_payload(job,directory)
            post=job['post'];kind=post.get('kind','video')
            key=object_key(job['user_id'],post['id']+'-'+post['public_token'][:12],kind)
            result=B2Store().put_file(key,path,'image/jpeg' if kind=='image' else 'video/mp4')
            chamar_api('/api/jobs/'+job['id']+'/result',{'lease_token':job['lease_token'],'status':'completed','size':result['size'],'sha256':result['sha256'],'version_id':result.get('version_id')})
        print('Trabalho concluído: upload verificado e confirmação aceita pelo servidor.')
    except Exception:
        try:chamar_api('/api/jobs/'+job['id']+'/result',{'lease_token':job['lease_token'],'status':'failed','error':'Falha de geração ou armazenamento no processador remoto.'})
        except Exception:pass
        # Never print provider exceptions, user topics, signed URLs or tokens.
        raise RuntimeError('O trabalho não foi concluído; consulte o estado no painel. Credenciais não foram registradas.') from None

if __name__=='__main__':main()
