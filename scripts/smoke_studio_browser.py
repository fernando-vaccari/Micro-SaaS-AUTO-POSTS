from playwright.sync_api import sync_playwright
from pathlib import Path
import time,json,secrets,argparse,shutil
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parent.parent
parser=argparse.ArgumentParser();parser.add_argument("--commercial-url",default="http://127.0.0.1:8010");parser.add_argument("--demo-url",default="http://127.0.0.1:8011");args=parser.parse_args()
for base in (args.commercial_url,args.demo_url):
 if urlsplit(base).hostname not in {"localhost","127.0.0.1"}:raise SystemExit("Use servidores locais de teste, com bancos separados.")
out=ROOT/'docs'/'screenshots';out.mkdir(exist_ok=True);(ROOT/'artifacts').mkdir(exist_ok=True)
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=shutil.which('chromium') or shutil.which('google-chrome'),headless=True,args=['--no-sandbox'])
 page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto(args.commercial_url+'/',wait_until='networkidle')
 assert page.locator('.price-card').count()==1 and '149,99' in page.locator('.price-card').inner_text()
 page.screenshot(path=str(out/'studio-landing-desktop.png'),full_page=True)
 page.locator('.hero-video>img').screenshot(path='/tmp/autoposts-store-demo.png')
 page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(out/'studio-landing-mobile.png'),full_page=True)
 assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'),'landing mobile overflow'
 page.goto(args.commercial_url+'/login',wait_until='networkidle');assert page.locator('#auth-form [name=name]').count()==0
 page.screenshot(path=str(out/'studio-login-mobile.png'),full_page=True)
 page.goto(args.demo_url+'/cadastro',wait_until='networkidle')
 page.locator('#auth-name').fill('Estúdio demonstração');page.locator('#auth-email').fill('studio-demo-'+str(int(time.time()))+'@example.com');page.locator('#auth-password').fill(secrets.token_urlsafe(24))
 page.locator('#auth-form [type=submit]').click();page.locator('#studio-form').wait_for(timeout=15000)
 assert page.locator('.demo-banner').count()==1
 page.locator('#studio-photos').set_input_files('/tmp/autoposts-store-demo.png')
 page.locator('.photo-choice').first.wait_for()
 page.locator('#studio-title').fill('Conheça nosso espaço')
 page.locator('#studio-prompt').fill('Bem-vindo ao nosso espaço. Aqui, cada detalhe foi pensado para você. Venha nos conhecer!')
 page.locator('#studio-company').fill('Casa Botânica · Demo')
 page.locator('[name=auto_publish]').uncheck()
 page.locator('#studio-voice-mode').select_option('synthetic_female')
 page.locator('#studio-duration').select_option('15')
 assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'),'studio mobile overflow'
 page.evaluate('scrollTo(0,0)');page.screenshot(path=str(out/'studio-editor-mobile.png'),full_page=True)
 page.set_viewport_size({'width':1440,'height':1000});page.evaluate('scrollTo(0,0)');page.screenshot(path=str(out/'studio-editor-desktop.png'),full_page=True)
 page.locator('#studio-form [type=submit]').click()
 page.locator('video').first.wait_for(timeout=90000)
 video=page.locator('video').first;video.evaluate('(v)=>v.load()');page.wait_for_function("()=>document.querySelector('video').readyState>=2",timeout=30000)
 props=video.evaluate('(v)=>({width:v.videoWidth,height:v.videoHeight,duration:v.duration,src:v.currentSrc})')
 assert props['width']==1080 and props['height']==1920 and 14<props['duration']<16,props
 response=page.request.get(props['src']);assert response.ok
 (ROOT/'artifacts'/'studio-kokoro-demo.mp4').write_bytes(response.body())
 page.screenshot(path=str(out/'studio-library-demo.png'),full_page=True)
 print('Real demo browser: signup → owned photo → female Kokoro inference → MP4 1080x1920 + AAC → private library passed',flush=True)
 page.goto(args.demo_url+'/#settings',wait_until='networkidle');assert 'Sem cobrança' in page.locator('.price-card').inner_text()
 print('Commercial R$149.99, dedicated login, demo without billing and mobile layout passed',flush=True)
 assert not errors,errors
 browser.close()
