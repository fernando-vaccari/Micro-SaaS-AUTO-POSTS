"""Run exactly the same application in the server-enforced demonstration edition."""
import os
from pathlib import Path
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parent.parent

if __name__=='__main__':
    file=ROOT/'.env.demo'
    if not file.exists():raise SystemExit('Execute .venv/bin/python -m scripts.configure_editions primeiro.')
    values={k:v for k,v in dotenv_values(file).items() if v is not None}
    os.environ.update(values);os.environ['APP_EDITION']='demo'
    secret=values.get('DEMO_APP_SECRET','')
    if len(secret)<32:raise SystemExit('Configure DEMO_APP_SECRET estável de pelo menos 32 caracteres ou execute scripts.configure_editions.')
    os.environ['APP_SECRET']=secret
    import uvicorn
    uvicorn.run('autoposts.main:app',host=os.environ.get('AUTOPOSTS_HOST','127.0.0.1'),port=int(os.environ.get('AUTOPOSTS_PORT','8001')),workers=1,access_log=False)
