"""Experimental image inlining core. No network, mutation, or publication.

Only uploaded image attachment slots are supported in this prototype.
Caller supplies an authorized image resolver; arbitrary strings are not fetched.
"""
import base64
import copy
import hashlib
import io
import re
import warnings
from PIL import Image

FILE_URL = re.compile(r'^/api/v1/files/([A-Za-z0-9_-]{1,128})/content$')
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_IMAGES = 100


class PackError(ValueError):
    pass


def image_mime(data):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                types = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'GIF': 'image/gif', 'WEBP': 'image/webp'}
                mime = types.get(image.format)
                if not mime or image.width * image.height > 20_000_000:
                    raise ValueError('Unsupported format or more than 20 megapixels')
                image.verify()
                return mime
    except Exception as exc:
        raise PackError('Invalid or unsupported image; only bounded PNG/JPEG/GIF/WebP are accepted') from exc


def pack_export(export, resolve):
    """Return copied export plus image manifest; resolve(file_id)->bytes.

    This prototype intentionally accepts only canonical same-instance relative
    file-content paths. It does not execute URLs, follow redirects or infer access.
    """
    if not isinstance(export, list) or not export or len(export) > 100:
        raise PackError('Expected 1–100 exported chat records')
    output = copy.deepcopy(export)
    cache, manifest = {}, []
    total = 0

    def inline(url):
        nonlocal total
        if not isinstance(url, str):
            raise PackError('Image URL must be text')
        if url.startswith('data:image/'):
            # Already portable: still check syntax, signature and size.
            try:
                header, payload = url.split(',', 1)
                if not header.endswith(';base64'):
                    raise ValueError('not base64')
                if len(payload) > MAX_IMAGE_BYTES * 4 // 3 + 8:
                    raise ValueError('too large')
                data = base64.b64decode(payload, validate=True)
                if not data or len(data) > MAX_IMAGE_BYTES:
                    raise ValueError('too large or empty')
                if header != 'data:' + image_mime(data) + ';base64':
                    raise ValueError('MIME mismatch')
            except Exception as exc:
                raise PackError('Malformed or unsupported inline image') from exc
            key = ('inline', hashlib.sha256(data).hexdigest())
            if key not in cache:
                total += len(data)
                cache[key] = url
            if total > MAX_TOTAL_BYTES or len(cache) > MAX_IMAGES:
                raise PackError('Export image budget exceeded')
            return url
        match = FILE_URL.fullmatch(url)
        if not match:
            raise PackError('Unsupported image reference; no remote URL was fetched')
        file_id = match.group(1)
        key = ('file', file_id)
        if key in cache:
            return cache[key]
        if len(cache) >= MAX_IMAGES:
            raise PackError('Too many images')
        try:
            data = resolve(file_id)
        except Exception as exc:
            raise PackError('Image unavailable or not authorized: ' + file_id) from exc
        if not isinstance(data, bytes) or not data or len(data) > MAX_IMAGE_BYTES:
            raise PackError('Invalid or oversized image: ' + file_id)
        mime = image_mime(data)
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise PackError('Export image budget exceeded')
        result = 'data:' + mime + ';base64,' + base64.b64encode(data).decode('ascii')
        cache[key] = result
        manifest.append({'file_id': file_id, 'bytes': len(data), 'mime': mime,
                         'sha256': hashlib.sha256(data).hexdigest()})
        return result

    def attachments(owner):
        files = owner.get('files', [])
        if not isinstance(files, list):
            raise PackError('Malformed attachment list')
        for item in files:
            if not isinstance(item, dict):
                raise PackError('Malformed attachment')
            if item.get('type') == 'image' or str(item.get('content_type', '')).startswith('image/'):
                item['url'] = inline(item.get('url'))
            else:
                raise PackError('This prototype supports uploaded images only, not other attachments')

    for record in output:
        if not isinstance(record, dict):
            raise PackError('Malformed chat record')
        chat = record.get('chat', record)
        if not isinstance(chat, dict):
            raise PackError('Malformed chat body')
        attachments(chat)
        history = chat.get('history', {})
        if not isinstance(history, dict) or not isinstance(history.get('messages', {}), dict):
            raise PackError('Malformed history')
        messages = list(history.get('messages', {}).values())
        if not isinstance(chat.get('messages', []), list):
            raise PackError('Malformed message list')
        messages += chat.get('messages', [])
        for message in messages:
            if not isinstance(message, dict):
                raise PackError('Malformed message')
            attachments(message)
            if isinstance(message.get('content'), str) and '/api/v1/files/' in message['content']:
                raise PackError('Embedded file links in message text need separate handling; not silently portable')
            if isinstance(message.get('content'), list):
                for part in message['content']:
                    if not isinstance(part, dict) or part.get('type') not in ('image_url', 'input_image'):
                        continue
                    field = part.get('image_url')
                    if isinstance(field, dict):
                        field['url'] = inline(field.get('url'))
                    elif isinstance(field, str):
                        part['image_url'] = inline(field)
                    else:
                        raise PackError('Malformed image content')
    return output, manifest
