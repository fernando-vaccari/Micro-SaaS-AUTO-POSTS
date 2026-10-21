"""Explicit CI smoke video; importing this module has no side effects."""
from pathlib import Path
from uuid import uuid4
from .render_job import render_payload

def main():
    owner='demo-'+uuid4().hex
    post={'id':'autoposts-demo','user_id':owner,'title':'Sua marca presente','caption':'Prévia local, sem publicação.','kind':'video','duration':6,'theme':'ocean','scenes':[{'text':'Seu negócio merece destaque.'},{'text':'Crie conteúdo com consistência.'},{'text':'Salve esta ideia.'}]}
    result=render_payload({'post':post,'user_id':owner,'assets':[]},Path('artifacts'))
    print(f'MP4 real de demonstração: {result}. Sem upload ou publicação.')

if __name__=='__main__':main()
