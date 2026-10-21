"""Bounded renderer for a leased API job, or an explicitly local demo."""
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from uuid import uuid4
from PIL import Image
from autoposts import core,media,storage

def render_payload(job,output):
    post=dict(job['post']);owner=job['user_id']
    if post['user_id']!=owner or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',owner):raise ValueError('Invalid tenant in job')
    old=core.settings.data_dir
    try:
        with tempfile.TemporaryDirectory() as directory:
            core.settings.data_dir=Path(directory);core.init_db()
            core.execute('INSERT INTO users(id,email,name,password_hash,created_at) VALUES(?,?,?,?,?)',(owner,uuid4().hex+'@renderer.invalid','Remote renderer','not-a-login',core.now()))
            for asset in job.get('assets',[]):
                if asset['user_id']!=owner or not asset.get('storage_key','').startswith(f'users/{owner}/images/') or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',asset['id']):raise ValueError('Invalid asset ownership')
                data=storage.B2Store().get_bytes(asset['storage_key'],10*1024*1024)
                filename=asset['id']+'.jpg';path=Path(directory)/'uploads'/filename;path.write_bytes(data)
                with Image.open(path) as image:image.verify()
                core.execute('INSERT INTO assets(id,user_id,filename,original_name,media_type,kind,size,created_at) VALUES(?,?,?,?,?,?,?,?)',(asset['id'],owner,filename,filename,'image/jpeg','image',len(data),core.now()))
            kind=post.get('kind','video')
            filename=media.render_image(post) if kind=='image' else media.render_post(post)
            output=Path(output);output.mkdir(parents=True,exist_ok=True)
            destination=output/filename
            shutil.copyfile(Path(directory)/('images' if kind=='image' else 'videos')/filename,destination)
            return destination
    finally:core.settings.data_dir=old

def main():
    job_id=os.environ.get('AUTOPOSTS_JOB_ID','demo-'+uuid4().hex)
    topic=os.environ.get('AUTOPOSTS_TOPIC','Três prioridades para organizar seu dia.').strip()
    duration=int(os.environ.get('AUTOPOSTS_DURATION','45'))
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',job_id) or not topic or len(topic)>500 or not 6<=duration<=60:raise ValueError('Invalid demo input')
    owner='demo-'+uuid4().hex
    post={'id':job_id,'user_id':owner,'title':topic[:120],'caption':topic,'duration':duration,'theme':'ocean','kind':'video','scenes':[{'text':topic[:200]},{'text':'Organize suas prioridades e coloque a ideia em prática.'},{'text':'Salve para consultar depois.'}]}
    result=render_payload({'post':post,'user_id':owner,'assets':[]},'artifacts')
    print(f'Prévia local gerada: {result.name}. Não representa uma tarefa concluída no servidor ou upload ao B2.')

if __name__=='__main__':main()
