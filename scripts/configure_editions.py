"""Prepare independent editions without overwriting existing keys or user settings."""
import os
from pathlib import Path
import secrets
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parent.parent


def prepare():
    main=ROOT/'.env';demo=ROOT/'.env.demo'
    for destination,template in [(main,ROOT/'.env.example'),(demo,ROOT/'.env.demo.example')]:
        if not destination.exists():
            fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'w') as output:output.write(template.read_text())
    values=dotenv_values(main);data_dir=Path(values.get('DATA_DIR') or ROOT/'.data')
    if not data_dir.is_absolute():data_dir=ROOT/data_dir
    prior=data_dir/'.app-secret'
    main_secret=prior.read_text().strip() if prior.is_file() else secrets.token_urlsafe(48)
    demo_values=dotenv_values(demo);demo_dir=Path(demo_values.get('DEMO_DATA_DIR') or ROOT/'.data-demo')
    if not demo_dir.is_absolute():demo_dir=ROOT/demo_dir
    demo_prior=demo_dir/'.app-secret'
    demo_secret=demo_prior.read_text().strip() if demo_prior.is_file() else secrets.token_urlsafe(48)
    shared=values.get('AI_MEDIA_TOKEN') or secrets.token_urlsafe(40)
    for destination,names in [(main,{'APP_SECRET':main_secret,'AI_MEDIA_TOKEN':shared}),
                              (demo,{'DEMO_APP_SECRET':demo_secret,'AI_MEDIA_TOKEN':shared})]:
        text=destination.read_text();values=dotenv_values(destination)
        for key,value in names.items():
            if values.get(key):continue
            lines=text.splitlines();replaced=False
            for i,line in enumerate(lines):
                if line.startswith(key+'='):lines[i]=key+'='+value;replaced=True
            if not replaced:lines.append(key+'='+value)
            text='\n'.join(lines)+'\n'
        destination.write_text(text);destination.chmod(0o600)
    print('Arquivos .env e .env.demo preparados. Segredos gerados e valores existentes preservados; nenhum valor foi impresso.')
if __name__=='__main__':prepare()
