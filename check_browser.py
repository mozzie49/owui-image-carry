"""Disposable localhost Open WebUI UI check with synthetic data only."""
import base64
import json
import os
import secrets
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
ORIGIN = 'http://127.0.0.1:8765'


def main():
    env = dict(os.environ)
    env.update({'DATA_DIR': tempfile.mkdtemp(prefix='carry-browser-'),
                'WEBUI_SECRET_KEY': 'disposable-local-ci-fixture-not-for-deployment',
                'OFFLINE_MODE': 'true', 'HF_HUB_OFFLINE': '1', 'USE_SLIM_DOCKER': 'true',
                'ENABLE_PLUGINS': 'false', 'ENABLE_OLLAMA_API': 'false', 'ENABLE_OPENAI_API': 'false',
                'ENABLE_VERSION_UPDATE_CHECK': 'false', 'DO_NOT_TRACK': 'true',
                'SCARF_NO_ANALYTICS': 'true', 'CUSTOM_NAME': '', 'WEBSOCKET_MANAGER': '',
                'CORS_ALLOW_ORIGIN': ORIGIN})
    env.pop('DATABASE_URL', None)
    log = (ROOT / 'browser-server.log').open('w')
    server = subprocess.Popen(['open-webui', 'serve', '--host', '127.0.0.1', '--port', '8765'],
                              env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        with httpx.Client(base_url=ORIGIN, timeout=20, trust_env=False) as client:
            for attempt in range(120):
                if server.poll() is not None:
                    raise RuntimeError('Disposable server exited: ' + str(server.returncode))
                try:
                    if client.get('/health').status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(2)
            else:
                raise RuntimeError('Disposable server did not become ready')
            password = secrets.token_urlsafe(24)
            signup = client.post('/api/v1/auths/signup', json={'name': 'Synthetic Migration Test',
                                 'email': 'fixture@example.invalid', 'password': password})
            assert signup.status_code == 200, (signup.status_code, signup.text[:200])
            token = signup.json()['token']
            headers = {'Authorization': 'Bearer ' + token}
            original = json.loads((ROOT / 'route-source-export.json').read_text())
            packed = json.loads((ROOT / 'route-packed-export.json').read_text())
            imported = client.post('/api/v1/chats/import', json={'chats': [{'chat': packed[0]['chat']}]}, headers=headers)
            assert imported.status_code == 200, (imported.status_code, imported.text[:200])
            chat_id = imported.json()[0]['id']
            image_url = packed[0]['chat']['history']['messages']['u1']['files'][0]['url']
            old_url = original[0]['chat']['history']['messages']['u1']['files'][0]['url']
            assert client.get(old_url, headers=headers).status_code == 404
            with sync_playwright() as p:
                browser = p.chromium.launch(channel='chrome')
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                try:
                    # Normal UI sign-in, not an injected authenticated state.
                    page.goto(ORIGIN + '/auth', wait_until='domcontentloaded')
                    page.locator('input[type=email]').fill('fixture@example.invalid')
                    page.locator('input[type=password]').fill(password)
                    page.locator('input[type=password]').press('Enter')
                    page.wait_for_url(lambda url: '/auth' not in url, timeout=30000)
                    page.goto(ORIGIN + '/c/' + chat_id, wait_until='domcontentloaded')
                    # Locate exact fixture image by DOM source; other avatars don't qualify.
                    fixture_image = page.locator('img[src="' + image_url + '"]')
                    fixture_image.wait_for(state='visible', timeout=30000)
                    page.wait_for_function('(src) => Array.from(document.images).some(i => i.src === src && i.complete && i.naturalWidth === 24 && i.naturalHeight === 16)', arg=image_url)
                    # Fresh accounts show release notes; dismiss through the real UI
                    # so the evidence screenshot does not hide the imported chat.
                    release_notes = page.get_by_text("Okay, Let's Go!", exact=True)
                    release_notes.click(timeout=10000)
                    release_notes.wait_for(state='hidden', timeout=10000)
                    assert page.get_by_text('Selected branch.', exact=True).is_visible()
                    assert page.get_by_text('Keep that image in context.', exact=True).is_visible()
                    assert page.get_by_text('First branch.', exact=True).count() == 0
                    page.screenshot(path=str(ROOT / 'browser-imported-image.png'), full_page=True)
                    (ROOT / 'browser-report.json').write_text(json.dumps({'version': '0.11.4',
                        'real_app_startup': True, 'ui_signin': True, 'real_json_import_api': True,
                        'source_asset_missing_on_destination': True, 'inline_image_rendered': True,
                        'natural_width': 24, 'natural_height': 16, 'selected_branch_rendered': True,
                        'model_called': False, 'synthetic_fixture_only': True}, indent=2))
                except Exception:
                    page.screenshot(path=str(ROOT / 'browser-failure.png'), full_page=True)
                    safe_inputs = page.locator('input').evaluate_all("els => els.map(e => ({type:e.type,name:e.name,placeholder:e.placeholder}))")
                    (ROOT / 'browser-failure.json').write_text(json.dumps({'url':page.url,'text':page.locator('body').inner_text(),'inputs':safe_inputs}, indent=2))
                    raise
                browser.close()
            print('BROWSER_IMAGE_RENDER_PASSED')
    finally:
        server.terminate()
        try:
            server.wait(timeout=20)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
        log.close()


if __name__ == '__main__':
    main()
