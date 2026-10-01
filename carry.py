"""Read-only source image packer for Open WebUI JSON exports (experimental)."""
import argparse
import getpass
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from pack_images import pack_export, PackError, MAX_IMAGE_BYTES

MAX_JSON_BYTES = 50 * 1024 * 1024
MAX_OUTPUT_BYTES = 150 * 1024 * 1024


def read_json(path):
    with Path(path).open('rb') as f:
        data = f.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        raise PackError('JSON input exceeds 50 MiB')
    return json.loads(data.decode('utf-8-sig'))


def source_origin(value):
    p = urlsplit(value)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise PackError('Source must be an HTTPS origin without credentials, query or fragment')
    if p.path not in ('', '/'):
        raise PackError('This experimental version supports root-mounted instances only')
    # Force invalid ports to fail before any credential prompt or connection.
    _ = p.port
    return p.scheme + '://' + p.netloc


def fetch_image(client, origin, token, file_id):
    # file_id is validated by the core. No URL from message text is followed.
    url = origin + '/api/v1/files/' + file_id + '/content'
    with client.stream('GET', url, headers={'Authorization': 'Bearer ' + token,
                                          'Accept-Encoding': 'identity'}) as response:
        if response.status_code != 200:
            raise PackError('Source returned HTTP ' + str(response.status_code) + ' for image ' + file_id)
        if response.headers.get('content-encoding', 'identity').lower() not in ('', 'identity'):
            raise PackError('Encoded image response refused')
        length = response.headers.get('content-length')
        if length and int(length) > MAX_IMAGE_BYTES:
            raise PackError('Image exceeds 10 MiB')
        parts, size = [], 0
        for chunk in response.iter_raw():
            size += len(chunk)
            if size > MAX_IMAGE_BYTES:
                raise PackError('Image exceeds 10 MiB')
            parts.append(chunk)
        return b''.join(parts)


def local_resolver(map_path):
    map_path = Path(map_path).resolve(strict=True)
    mapping = read_json(map_path)
    if not isinstance(mapping, dict):
        raise PackError('Asset map must be an object of file IDs to relative paths')
    def resolve(file_id):
        value = mapping[file_id]
        if not isinstance(value, str) or not value or Path(value).is_absolute() or '..' in Path(value).parts:
            raise PackError('Asset path must stay inside the asset-map directory')
        candidate = map_path.parent / value
        if candidate.is_symlink():
            raise PackError('Symlink assets are not accepted')
        path = candidate.resolve(strict=True)
        if not path.is_relative_to(map_path.parent):
            raise PackError('Asset path escaped its directory')
        with path.open('rb') as f:
            return f.read(MAX_IMAGE_BYTES + 1)
    return resolve


def main():
    p = argparse.ArgumentParser(description='Experimental Open WebUI image-portable JSON export. Source read-only.')
    p.add_argument('input', help='Existing Open WebUI JSON export; keep an unchanged backup')
    p.add_argument('output', help='New output JSON; existing files are never overwritten')
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--source', help='HTTPS origin of the source Open WebUI instance')
    group.add_argument('--asset-map', help='Local JSON mapping of file IDs to relative image paths')
    args = p.parse_args()
    try:
        exported = read_json(args.input)
        output = Path(args.output)
        if output.exists():
            raise PackError('Output already exists; choose a new filename')
        if args.asset_map:
            packed, manifest = pack_export(exported, local_resolver(args.asset_map))
        else:
            origin = source_origin(args.source)
            print('Only image bytes will be read from ' + origin + '. No source chats will be changed.')
            print('Enter an EXISTING source API token. It is not saved. No token is created by this tool.')
            token = getpass.getpass('Source API token: ')
            if not token or any(c in token for c in '\r\n'):
                raise PackError('Invalid or empty token')
            with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
                packed, manifest = pack_export(exported, lambda key: fetch_image(client, origin, token, key))
            token = None
        data = json.dumps(packed, ensure_ascii=False, indent=2).encode('utf-8')
        if len(data) > MAX_OUTPUT_BYTES:
            raise PackError('Packed export exceeds 150 MiB')
        # Exclusive create only after the complete transformation succeeds.
        with output.open('xb') as f:
            f.write(data)
        print('Created ' + str(output) + '; embedded ' + str(len(manifest)) + ' distinct source images.')
        print('This file contains private chats and images. Keep it private; test import on a disposable destination first.')
    except (PackError, OSError, ValueError, KeyError, httpx.HTTPError) as exc:
        # Deliberately omit chained network exception details/headers/tokens.
        print('Packing failed: ' + str(exc) if isinstance(exc, PackError) else 'Packing failed: invalid input, file access or connection failure.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
