import base64
import copy
import io
import unittest
from unittest.mock import patch
from PIL import Image
from pack_images import pack_export, PackError


def png():
    b = io.BytesIO()
    Image.new('RGB', (2, 2), 'blue').save(b, format='PNG')
    return b.getvalue()


def fixture(url='/api/v1/files/test-image/content'):
    message = {'id': 'one', 'role': 'user', 'content': 'Do not change me',
               'files': [{'type': 'image', 'url': url}]}
    return [{'chat': {'title': 'Fixture', 'history': {'messages': {'one': message}, 'currentId': 'one'},
                      'messages': [copy.deepcopy(message)]}}]


class PackImagesTest(unittest.TestCase):
    def test_both_histories_preserved_without_mutation(self):
        original = fixture()
        before = copy.deepcopy(original)
        calls = []
        def resolve(key):
            calls.append(key)
            return png()
        result, manifest = pack_export(original, resolve)
        self.assertEqual(original, before)
        self.assertEqual(calls, ['test-image'])
        self.assertEqual(len(manifest), 1)
        for message in [result[0]['chat']['history']['messages']['one'], result[0]['chat']['messages'][0]]:
            self.assertEqual(base64.b64decode(message['files'][0]['url'].split(',')[1]), png())
            self.assertEqual(message['content'], 'Do not change me')

    def test_unavailable_aborts_and_preserves_input(self):
        original = fixture()
        before = copy.deepcopy(original)
        def unavailable(_):
            raise PermissionError('fake access denial')
        with self.assertRaisesRegex(PackError, 'unavailable or not authorized'):
            pack_export(original, unavailable)
        self.assertEqual(original, before)

    def test_external_and_ambiguous_references_never_resolved(self):
        for url in ['https://evil.example/image.png', '//evil.example/x', '/api/v1/files/../content',
                    '/api/v1/files/a/content?token=secret', '/api/v1/files/a%2Fb/content', 'javascript:alert(1)']:
            with self.subTest(url=url):
                calls = []
                with self.assertRaises(PackError):
                    pack_export(fixture(url), lambda x: calls.append(x))
                self.assertEqual(calls, [])

    def test_inline_is_validated_without_fetch(self):
        url = 'data:image/png;base64,' + base64.b64encode(png()).decode()
        result, manifest = pack_export(fixture(url), lambda _: self.fail('must not fetch'))
        self.assertEqual(result, fixture(url))
        self.assertEqual(manifest, [])

    def test_bad_inline_rejected(self):
        for url in ['data:image/png;base64,!!!', 'data:image/svg+xml;base64,PHN2Zz4=',
                    'data:image/jpeg;base64,' + base64.b64encode(png()).decode()]:
            with self.subTest(url=url), self.assertRaises(PackError):
                pack_export(fixture(url), lambda _: self.fail('must not fetch'))

    def test_non_image_and_size_rejected(self):
        for data in [b'<html>not an image', b'', None]:
            with self.subTest(data=data), self.assertRaises(PackError):
                pack_export(fixture(), lambda _: data)
        with patch('pack_images.MAX_IMAGE_BYTES', 2), self.assertRaises(PackError):
            pack_export(fixture(), lambda _: png())

    def test_budget_rejected(self):
        with patch('pack_images.MAX_TOTAL_BYTES', 2), self.assertRaises(PackError):
            pack_export(fixture(), lambda _: png())

    def test_non_image_attachment_not_silently_omitted(self):
        original = fixture()
        original[0]['chat']['history']['messages']['one']['files'][0]['type'] = 'file'
        with self.assertRaisesRegex(PackError, 'uploaded images only'):
            pack_export(original, lambda _: png())

    def test_content_parts(self):
        original = fixture()
        parts = [{'type': 'image_url', 'image_url': {'url': '/api/v1/files/test-image/content', 'detail': 'high'}},
                 {'type': 'input_image', 'image_url': '/api/v1/files/test-image/content'},
                 {'type': 'text', 'text': 'Keep this'}]
        original[0]['chat']['history']['messages']['one']['content'] = parts
        result, manifest = pack_export(original, lambda _: png())
        out = result[0]['chat']['history']['messages']['one']['content']
        self.assertEqual(out[0]['image_url']['detail'], 'high')
        self.assertTrue(out[1]['image_url'].startswith('data:image/png;'))
        self.assertEqual(out[2], parts[2])
        self.assertEqual(len(manifest), 1)

    def test_markdown_file_reference_is_explicitly_unsupported(self):
        original = fixture()
        original[0]['chat']['messages'][0]['content'] = '![x](/api/v1/files/test-image/content)'
        with self.assertRaisesRegex(PackError, 'separate handling'):
            pack_export(original, lambda _: png())

    def test_malformed_exports(self):
        for obj in [None, {}, [], [1], [{'chat': []}], [{'chat': {'history': []}}]]:
            with self.subTest(obj=obj), self.assertRaises(PackError):
                pack_export(obj, lambda _: png())


if __name__ == '__main__':
    unittest.main()
