import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import httpx
from PIL import Image
from carry import source_origin, fetch_image, local_resolver, encode_bounded
from unittest.mock import patch
from pack_images import PackError
from test_pack_images import fixture, png


class CarryTest(unittest.TestCase):
    def test_bounded_encoding_preserves_unicode_and_exact_limit(self):
        value = {'message': '中文🙂', 'images': ['fixture', 'fixture']}
        expected = json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')
        self.assertEqual(encode_bounded(value, len(expected)), expected)
        with self.assertRaises(PackError):
            encode_bounded(value, len(expected) - 1)

    def test_bounded_encoding_stops_before_serializing_remaining_images(self):
        def fragments(_):
            yield '['
            yield 'x' * 20
            self.fail('Serialization continued beyond the output budget')
        with patch('carry.json.JSONEncoder.iterencode', side_effect=fragments):
            with self.assertRaises(PackError):
                encode_bounded(['repeated-image'] * 100, 10)

    def test_repeated_images_count_toward_serialized_budget(self):
        image = 'data:image/png;base64,' + 'A' * 100
        with self.assertRaises(PackError):
            encode_bounded([image] * 100, 1000)

    def test_origin_validation(self):
        self.assertEqual(source_origin('https://example.com/'), 'https://example.com')
        self.assertEqual(source_origin('http://127.0.0.1:8080'), 'http://127.0.0.1:8080')
        self.assertEqual(source_origin('http://[::1]:8080'), 'http://[::1]:8080')
        for value in ['http://example.com', 'https://user:pass@example.com', 'https://example.com/a',
                      'https://example.com/?key=x', 'https://example.com/#x', 'https://example.com:bad',
                      'http://localhost:8080', 'http://127.0.0.1.evil.example', 'http://192.168.1.1']:
            with self.subTest(value=value), self.assertRaises((PackError, ValueError)):
                source_origin(value)

    def test_redirect_is_not_followed(self):
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(302, headers={'location': 'https://other.invalid/steal'})
        with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=False) as client:
            with self.assertRaises(PackError):
                fetch_image(client, 'https://source.invalid', 'synthetic-token', 'file-id')
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.host, 'source.invalid')

    def test_bytes_and_header_target(self):
        def handle(request):
            self.assertEqual(str(request.url), 'https://source.invalid/api/v1/files/file-id/content')
            self.assertEqual(request.headers['authorization'], 'Bearer synthetic-token')
            return httpx.Response(200, stream=httpx.ByteStream(b'fixture-bytes'))
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            self.assertEqual(fetch_image(client, 'https://source.invalid', 'synthetic-token', 'file-id'), b'fixture-bytes')

    def test_unavailable_http_fails(self):
        for status in [401, 403, 404, 500]:
            with self.subTest(status=status), httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status))) as client:
                with self.assertRaises(PackError):
                    fetch_image(client, 'https://source.invalid', 'synthetic-token', 'file-id')

    def test_asset_map_containment(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            mapping = root / 'assets.json'
            mapping.write_text(json.dumps({'x': '../escape.png'}))
            with self.assertRaises(PackError):
                local_resolver(mapping)('x')
            (root / 'image.png').write_bytes(b'local-fixture')
            mapping.write_text(json.dumps({'x': 'image.png'}))
            self.assertEqual(local_resolver(mapping)('x'), b'local-fixture')

    def test_cli_private_output_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'image.png').write_bytes(png())
            (root / 'assets.json').write_text(json.dumps({'test-image': 'image.png'}))
            (root / 'input.json').write_text(json.dumps(fixture()))
            command = [sys.executable, str(Path(__file__).with_name('carry.py')), str(root / 'input.json'),
                       str(root / 'output.json'), '--asset-map', str(root / 'assets.json')]
            r = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            before = (root / 'output.json').read_bytes()
            if os.name == 'posix':
                self.assertEqual((root / 'output.json').stat().st_mode & 0o777, 0o600)
            r = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertEqual((root / 'output.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
