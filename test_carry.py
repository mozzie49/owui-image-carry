import io
import json
import tempfile
import unittest
from pathlib import Path
import httpx
from PIL import Image
from carry import source_origin, fetch_image, local_resolver
from pack_images import PackError


class CarryTest(unittest.TestCase):
    def test_origin_validation(self):
        self.assertEqual(source_origin('https://example.com/'), 'https://example.com')
        for value in ['http://example.com', 'https://user:pass@example.com', 'https://example.com/a',
                      'https://example.com/?key=x', 'https://example.com/#x', 'https://example.com:bad']:
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


if __name__ == '__main__':
    unittest.main()
