"""Real Open WebUI routers + SQLite via in-process ASGI, no model server.

Authentication identity is a synthetic dependency override; file authorization,
database, import/export, and continued-message preprocessing stay upstream code.
"""
import asyncio
import base64
import copy
import hashlib
import io
import json
import os
import socket
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODE = os.environ['CHECK_MODE']
run_dir = Path(tempfile.mkdtemp(prefix='owui-carry-' + MODE + '-'))
os.environ['DATA_DIR'] = str(run_dir)
os.environ['DATABASE_URL'] = 'sqlite:///' + str(run_dir / 'webui.db')
os.environ.setdefault('WEBUI_SECRET_KEY', 'synthetic-test-fixture-only-not-for-deployment')
os.environ['OFFLINE_MODE'] = 'true'
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['USE_SLIM_DOCKER'] = 'true'
os.environ['ENABLE_PLUGINS'] = 'false'
os.environ['STORAGE_PROVIDER'] = 'local'
os.environ['CUSTOM_NAME'] = ''
os.environ['WEBSOCKET_MANAGER'] = ''

from fastapi import FastAPI
from starlette.requests import Request
import httpx
from PIL import Image
from open_webui.routers import chats, files
from open_webui.models.users import Users
from open_webui.models.chats import Chats
from open_webui.models.config import Config
from open_webui.utils.auth import get_verified_user
from open_webui.utils.middleware import process_chat_payload
from pack_images import pack_export


async def main():
    # Block TCP networking during fixtures. ASGI requests stay in process.
    original_connect = socket.socket.connect
    def guarded_connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError('Outbound network is forbidden in the fixture')
        return original_connect(sock, address)
    socket.socket.connect = guarded_connect
    user = await Users.insert_new_user('fixture-user', 'Synthetic user', 'fixture@example.invalid', role='user')
    outsider = await Users.insert_new_user('other-user', 'Other synthetic user', 'other@example.invalid', role='user')
    assert user and outsider
    await Config.upsert({'user.permissions': {'chat': {'import': True, 'file_upload': True}},
                         'chat.context_compaction.enable': False, 'events.webhooks': []})
    current_user = user
    app = FastAPI()
    app.state.redis = None
    async def identity():
        return current_user
    app.dependency_overrides[get_verified_user] = identity
    app.include_router(chats.router, prefix='/api/v1/chats')
    app.include_router(files.router, prefix='/api/v1/files')
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://fixture.invalid') as client:
        if MODE == 'source':
            b = io.BytesIO()
            Image.new('RGB', (24, 16), (12, 120, 220)).save(b, format='PNG')
            raw = b.getvalue()
            r = await client.post('/api/v1/files/?process=false', files={'file': ('synthetic.png', raw, 'image/png')})
            assert r.status_code == 200, (r.status_code, r.text)
            asset = r.json()
            path = '/api/v1/files/' + asset['id'] + '/content'
            r = await client.get(path)
            assert r.status_code == 200 and r.content == raw
            current_user = outsider
            r = await client.get(path)
            assert r.status_code == 404, ('unauthorized access', r.status_code)
            current_user = user
            messages = {
                'u1': {'id': 'u1', 'role': 'user', 'content': 'Describe this image.', 'parentId': None,
                       'childrenIds': ['a1', 'a2'], 'timestamp': 1,
                       'files': [{'id': asset['id'], 'type': 'image', 'url': path}]},
                'a1': {'id': 'a1', 'role': 'assistant', 'content': 'First branch.', 'parentId': 'u1', 'childrenIds': [], 'timestamp': 2},
                'a2': {'id': 'a2', 'role': 'assistant', 'content': 'Selected branch.', 'parentId': 'u1', 'childrenIds': ['u2'], 'timestamp': 3},
                'u2': {'id': 'u2', 'role': 'user', 'content': 'Keep that image in context.', 'parentId': 'a2', 'childrenIds': [], 'timestamp': 4},
            }
            body = {'title': 'Synthetic image transfer', 'history': {'messages': messages, 'currentId': 'u2'},
                    'messages': [copy.deepcopy(messages[x]) for x in ['u1', 'a2', 'u2']]}
            r = await client.post('/api/v1/chats/import', json={'chats': [{'chat': body}]})
            assert r.status_code == 200, (r.status_code, r.text)
            r = await client.get('/api/v1/chats/all')
            assert r.status_code == 200, (r.status_code, r.text)
            exported = [json.loads(line) for line in r.text.splitlines() if line.strip()]
            assert len(exported) == 1
            image_response = await client.get(path)
            authorized_bytes = {asset['id']: image_response.content}
            packed, manifest = pack_export(exported, authorized_bytes.__getitem__)
            (ROOT / 'route-source-export.json').write_text(json.dumps(exported))
            (ROOT / 'route-packed-export.json').write_text(json.dumps(packed))
            (ROOT / 'route-source-evidence.json').write_text(json.dumps({'sha256': hashlib.sha256(raw).hexdigest(),
                'path': path, 'owner_read': True, 'other_user_read_denied': True, 'image_manifest': manifest}, indent=2))
            print('SOURCE_ROUTES_PASSED', flush=True)
        elif MODE == 'destination':
            original = json.loads((ROOT / 'route-source-export.json').read_text())
            packed = json.loads((ROOT / 'route-packed-export.json').read_text())
            evidence = json.loads((ROOT / 'route-source-evidence.json').read_text())
            missing = await client.get(evidence['path'])
            assert missing.status_code == 404
            ids = {}
            for label, exported in [('original', original), ('packed', packed)]:
                r = await client.post('/api/v1/chats/import', json={'chats': [{'chat': exported[0]['chat']}]})
                assert r.status_code == 200, (r.status_code, r.text)
                ids[label] = r.json()[0]['id']
            r = await client.get('/api/v1/chats/' + ids['packed'])
            assert r.status_code == 200, (r.status_code, r.text)
            stored = r.json()['chat']['history']
            assert set(stored['messages']) == {'u1', 'a1', 'a2', 'u2'}
            assert stored['messages']['u1']['childrenIds'] == ['a1', 'a2']
            url = stored['messages']['u1']['files'][0]['url']
            assert hashlib.sha256(base64.b64decode(url.split(',', 1)[1])).hexdigest() == evidence['sha256']
            model = {'id': 'fixture-vision', 'name': 'Fixture vision', 'owned_by': 'openai',
                     'info': {'meta': {'capabilities': {'vision': True, 'builtin_tools': False}}}}
            app.state.MODELS = {model['id']: model}
            results = {}
            for label, chat_id in ids.items():
                scope = {'type': 'http', 'app': app, 'method': 'POST', 'path': '/api/chat/completions',
                         'headers': [], 'query_string': b'', 'server': ('fixture.invalid', 80), 'scheme': 'http'}
                request = Request(scope)
                request.state.direct = False
                metadata = {'chat_id': chat_id, 'user_message_id': 'u2', 'user_id': user.id,
                            'message_id': 'fixture-response', 'params': {'function_calling': 'legacy'}}
                form = {'model': model['id'], 'messages': [{'role': 'user', 'content': 'Keep that image in context.'}],
                        'features': {}, 'stream': False}
                processed, _, _ = await process_chat_payload(request, form, user, metadata, model)
                serialized = json.dumps(processed['messages'])
                assert 'Selected branch.' in serialized and 'First branch.' not in serialized
                assert 'Keep that image in context.' in serialized
                parts = [part for message in processed['messages'] for part in
                         (message.get('content') if isinstance(message.get('content'), list) else [])
                         if isinstance(part, dict) and part.get('type') == 'image_url']
                assert len(parts) == 1, (label, processed)
                results[label] = parts[0]['image_url']['url']
            assert results['original'] == evidence['path'], results['original']
            assert results['packed'].startswith('data:image/png;base64,')
            assert hashlib.sha256(base64.b64decode(results['packed'].split(',', 1)[1])).hexdigest() == evidence['sha256']
            report = {'real_routes': True, 'isolated_databases': True, 'auth_identity_stubbed': True,
                      'real_file_access_control': True, 'source_missing_on_destination': True,
                      'branches_preserved': True, 'real_continuation_preprocessing': True,
                      'image_bytes_in_continuation_preserved': True, 'model_called': False,
                      'outbound_tcp_guard_during_fixture': True,
                      'browser_rendering_checked': False}
            (ROOT / 'route-report.json').write_text(json.dumps(report, indent=2))
            print('DESTINATION_ROUTES_PASSED', json.dumps(report), flush=True)
        else:
            raise ValueError(MODE)


asyncio.run(main())
