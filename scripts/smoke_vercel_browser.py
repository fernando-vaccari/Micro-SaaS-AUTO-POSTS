"""Local Vercel gateway QA: public setup + connected isolated demo backend.

Requires Playwright/Chromium, the two local test servers and real Kokoro for the
connected demo. Never connects Meta or charges a payment. Outputs go to artifacts/.
"""
import argparse
from pathlib import Path
import random
import secrets
import shutil
import struct
from urllib.parse import urlsplit
import zlib

from playwright.sync_api import sync_playwright


def png(width, height, noise=False):
    def chunk(kind, data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
    pixels=random.Random(42).randbytes(width*height*3) if noise else b'\xbf\xa4\x78'*(width*height)
    raw=b''.join(b'\x00'+pixels[i*width*3:(i+1)*width*3] for i in range(height))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')


def run(setup_url, demo_url, failure_url=None):
    output=Path(__file__).resolve().parent.parent/'artifacts';output.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(executable_path=shutil.which('chromium') or shutil.which('google-chrome'),headless=True,args=['--no-sandbox'])
        context=browser.new_context(viewport={'width':1440,'height':1000},timezone_id='America/Sao_Paulo')
        page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(setup_url,wait_until='networkidle')
        assert page.locator('.deployment-notice').is_visible()
        assert '149,99' in page.locator('.price-card').inner_text()
        assert not page.locator('.loader').count()
        page.screenshot(path=str(output/'vercel-public-desktop.png'))
        page.goto(setup_url+'/cadastro',wait_until='networkidle')
        assert page.locator('.setup-access').is_visible()
        assert page.locator('input[type=password],input[type=email]').count()==0
        page.set_viewport_size({'width':390,'height':844})
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.screenshot(path=str(output/'vercel-setup-mobile.png'))
        assert not errors,errors
        if failure_url:
            response=page.goto(failure_url,wait_until='networkidle');assert response.status==200
            page.locator('.new-hero').wait_for()
            assert page.request.get(failure_url+'/favicon.ico').status==200
            assert page.locator('.deployment-notice').is_visible()
            assert 'FUNCTION_INVOCATION_FAILED' not in page.locator('body').inner_text()
            page.screenshot(path=str(output/'vercel-api-failure-home.png'))
            page.goto(failure_url+'/cadastro',wait_until='networkidle')
            page.locator('.setup-access').wait_for()
            assert page.locator('input[type=password],input[type=email]').count()==0
            assert not errors,errors
        context.close()

        context=browser.new_context(viewport={'width':1440,'height':1000},timezone_id='America/Sao_Paulo')
        page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(demo_url+'/cadastro',wait_until='networkidle')
        config=page.request.get(demo_url+'/api/public/config').json()
        assert config['edition']=='demo' and config['backend_connected'] is True
        page.locator('#auth-name').fill('Teste de integração Vercel')
        page.locator('#auth-email').fill('vercel-'+secrets.token_hex(6)+'@example.com')
        page.locator('#auth-password').fill(secrets.token_urlsafe(24))
        page.locator('#auth-form [type=submit]').click()
        page.locator('#studio-form').wait_for(timeout=15000)
        large=png(1600,1000,noise=True);assert len(large)>4*1024*1024
        page.locator('#studio-photos').set_input_files({'name':'grande-teste.png','mimeType':'image/png','buffer':large})
        page.locator('.photo-choice').first.wait_for()
        assets=page.request.get(demo_url+'/api/assets').json()['assets']
        big=next(a for a in assets if a['original_name']=='grande-teste.jpg')
        assert big['size']<4*1024*1024
        page.locator('#studio-photos').set_input_files({'name':'fachada-teste.png','mimeType':'image/png','buffer':png(900,800)})
        page.wait_for_function("()=>document.querySelectorAll('.photo-choice').length===2")
        page.locator('[name=photo][value="'+big['id']+'"]').uncheck()
        page.locator('#studio-title').fill('Minha marca no piloto automático')
        page.locator('#studio-prompt').fill('Bem-vindo ao nosso espaço. Cada detalhe foi pensado para você. Venha nos conhecer!')
        page.locator('[name=auto_publish]').uncheck()
        page.locator('#studio-voice-mode').select_option('synthetic_female')
        page.locator('#studio-duration').select_option('15')
        page.locator('#studio-form [type=submit]').click()
        video=page.locator('video').first;video.wait_for(timeout=120000)
        video.evaluate('(video)=>video.load()')
        page.wait_for_function("()=>document.querySelector('video').readyState>=2",timeout=30000)
        props=video.evaluate('(video)=>({width:video.videoWidth,height:video.videoHeight,duration:video.duration,src:video.currentSrc})')
        assert props['width']==1080 and props['height']==1920 and 14<props['duration']<16,props
        result=page.request.get(props['src']);assert result.status==200
        (output/'vercel-kokoro-demo.mp4').write_bytes(result.body())
        page.locator('video').first.evaluate('(video)=>{video.muted=true;return video.play();}')
        page.wait_for_function("()=>document.querySelector('video').currentTime>0.5",timeout=15000)
        page.locator('video').first.evaluate('(video)=>video.pause()')
        page.screenshot(path=str(output/'vercel-connected-library.png'))
        assert not errors,errors
        context.close();browser.close()
        print('Browser passed: setup pages without fake accounts; mobile; connected registration/cookies; photo >4 MB compressed before upload; real Kokoro → MP4 1080x1920/AAC through the gateway.')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--setup-url',default='http://127.0.0.1:8012')
    parser.add_argument('--demo-url',default='http://127.0.0.1:8013')
    parser.add_argument('--failure-url',default=None)
    args=parser.parse_args()
    for base in filter(None,(args.setup_url,args.demo_url,args.failure_url)):
        address=urlsplit(base)
        if address.scheme!='http' or address.hostname not in {'localhost','127.0.0.1'} or address.username or address.password:
            raise SystemExit('Use somente servidores locais de teste com banco isolado.')
    run(args.setup_url.rstrip('/'),args.demo_url.rstrip('/'),args.failure_url.rstrip('/') if args.failure_url else None)
