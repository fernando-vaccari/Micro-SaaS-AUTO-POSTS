"""Server-side edition selection; a browser parameter can never unlock billing."""
import os
from fastapi import HTTPException


def demo():return os.environ.get('APP_EDITION','saas')=='demo'

def allow_publishing():return not demo() or os.environ.get('DEMO_ALLOW_PUBLISHING','true')=='true'

def require_publishing():
    if not allow_publishing():raise HTTPException(403,'Publicações reais estão desativadas nesta demonstração. Crie prévias e acompanhe a biblioteca.')

def require_billing():
    if demo():raise HTTPException(403,'Esta é a edição de demonstração. Cobranças estão desativadas no servidor.')
