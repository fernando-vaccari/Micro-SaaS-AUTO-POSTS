"""Local browser regression: lost response, reload, progress and account isolation.

Requires Playwright/Chromium and an isolated demo server. Creates synthetic users
and images, never connects Instagram or starts payments. Screenshots go to artifacts/.
"""
import argparse
import asyncio
from pathlib import Path
import secrets
import shutil
import struct
from urllib.parse import urlsplit
import zlib

from playwright.async_api import async_playwright


def sample_png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    pixels = (b'\x00' + b'\xbf\xa4\x78' * 900) * 800
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 900, 800, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))


async def main(base):
    output = Path(__file__).resolve().parent.parent / 'artifacts'
    output.mkdir(exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path=shutil.which('chromium') or shutil.which('google-chrome'),
            headless=True, args=['--no-sandbox'])
        page = await browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto(base + '/cadastro', wait_until='networkidle')
        assert (await (await page.request.get(base + '/api/public/config')).json())['edition'] == 'demo'

        async def register(name):
            await page.locator('#auth-name').fill(name)
            await page.locator('#auth-email').fill('reliability-' + secrets.token_hex(6) + '@example.com')
            await page.locator('#auth-password').fill(secrets.token_urlsafe(24))
            await page.locator('#auth-form [type=submit]').click()
            await page.locator('#studio-form').wait_for(timeout=15000)

        await register('Primeira pessoa de teste')
        owner = (await (await page.request.get(base + '/api/session')).json())['user']['id']
        await page.locator('#studio-photos').set_input_files(
            {'name': 'foto-privada-teste.png', 'mimeType': 'image/png', 'buffer': sample_png()})
        await page.locator('[name=photo]:checked').wait_for()
        await page.locator('#studio-title').fill('Conteúdo de demonstração')
        script = 'Conheça nosso espaço. Cada detalhe foi pensado para você. Venha nos visitar!'
        await page.locator('#studio-prompt').fill(script)
        await page.locator('[name=auto_publish]').uncheck()
        await page.locator('[name=kind]').select_option('image')
        await page.reload(wait_until='networkidle')
        await page.locator('#studio-form').wait_for()
        assert await page.locator('#studio-prompt').input_value() == script
        assert await page.locator('[name=photo]:checked').count() == 1
        assert not await page.locator('[name=auto_publish]').is_checked()
        assert await page.locator('#studio-voice-mode').input_value() == 'none'

        keys = []
        created = {}

        async def lose_response(route):
            if route.request.method != 'POST':
                return await route.continue_()
            keys.append(route.request.headers.get('idempotency-key'))
            response = await route.fetch()
            assert response.status == 201
            created.update(await response.json())
            # The backend committed, but the browser never received confirmation.
            await route.abort('connectionreset')

        await page.route('**/api/studio', lose_response)
        await page.locator('#studio-form [type=submit]').click()
        await page.locator('#studio-form .form-error.visible').wait_for()
        await page.unroute('**/api/studio', lose_response)
        await page.reload(wait_until='networkidle')
        await page.locator('#studio-form').wait_for()

        async def replay(route):
            keys.append(route.request.headers.get('idempotency-key'))
            await route.continue_()

        await page.route('**/api/studio', replay)
        async with page.expect_response(lambda response: response.url.endswith('/api/studio')
                                       and response.request.method == 'POST') as received:
            await page.locator('#studio-form [type=submit]').click()
        response = await received.value
        assert response.status == 200 and response.headers['idempotency-replayed'] == 'true'
        assert (await response.json())['post']['id'] == created['post']['id']
        assert len(keys) == 2 and keys[0] and keys[0] == keys[1]
        await page.unroute('**/api/studio', replay)
        await page.wait_for_url('**#library')
        posts = (await (await page.request.get(base + '/api/posts')).json())['posts']
        assert len(posts) == 1
        usage = (await (await page.request.get(base + '/api/dashboard')).json())['usage']
        assert usage['images']['used'] == 1
        await page.evaluate("location.hash='studio'")
        await page.locator('#studio-progress [data-status=ready]').wait_for(timeout=30000)
        await page.evaluate('scrollTo(0,0)')
        await page.screenshot(path=str(output / 'studio-progress-desktop.png'))
        await page.set_viewport_size({'width': 390, 'height': 844})
        await page.wait_for_function("()=>document.querySelector('.sidebar').getBoundingClientRect().right<=1")
        assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
        await page.screenshot(path=str(output / 'studio-progress-mobile.png'))

        await page.set_viewport_size({'width': 1440, 'height': 1000})
        held = asyncio.Event()
        release = asyncio.Event()

        async def delayed_assets(route):
            if held.is_set() or route.request.method != 'GET':
                return await route.continue_()
            response = await route.fetch()
            held.set()
            await release.wait()
            await route.fulfill(response=response)

        await page.route('**/api/assets', delayed_assets)
        await page.locator('[data-action=refresh]').click()
        await asyncio.wait_for(held.wait(), 15)
        await page.locator('[data-action=logout]').click()
        await page.wait_for_function("()=>!document.querySelector('[data-action=logout]')")
        await page.evaluate("location.hash='signup'")
        await register('Segunda pessoa de teste')
        assert await page.locator('#studio-prompt').input_value() == ''
        assert await page.locator('.photo-choice').count() == 0
        release.set()
        await page.wait_for_timeout(300)
        assert await page.locator('.photo-choice').count() == 0
        assert await page.locator('#studio-progress section').count() == 0
        assert not await page.evaluate('(owner)=>sessionStorage.getItem("autoposts.studio."+owner)', owner)
        assert not errors, errors
        await browser.close()
        print('Browser passed: persisted draft; lost response + reload reuses one request/credit; live progress; mobile; logout and delayed previous-account response isolation.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo-url', default='http://127.0.0.1:8011')
    args = parser.parse_args()
    address = urlsplit(args.demo_url)
    if address.scheme != 'http' or address.hostname not in {'localhost', '127.0.0.1'} or address.username or address.password:
        raise SystemExit('Use somente um servidor local de demonstração com banco isolado.')
    asyncio.run(main(args.demo_url.rstrip('/')))
